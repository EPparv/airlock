"""Encrypted, immutable Agent Skills packages. Import is not execution permission."""
import base64,copy,hashlib,io,json,re,secrets,stat,zipfile
from pathlib import PurePosixPath,Path
from .core import Denied,canonical

MAX_PACKAGE=16*1024*1024
MAX_FILES=400
TEXT_SUFFIX={'.md','.txt','.json','.csv','.yaml','.yml','.py','.js','.mjs','.sh','.toml'}

def safe_path(name):
    if not isinstance(name,str) or len(name)>240 or '\\' in name or '\x00' in name or any(ord(c)<32 for c in name):raise Denied('The package contains an unsafe path.')
    p=PurePosixPath(name)
    if p.is_absolute() or not p.parts or any(x in ('..','.') or x.startswith('.') or ':' in x for x in name.split('/')):raise Denied('The package contains an unsafe path.')
    return p.as_posix()

def unzip(raw,limit=MAX_PACKAGE):
    if not isinstance(raw,bytes) or len(raw)>limit:raise Denied('Choose a skill package up to 16 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist()
            if len(entries)>MAX_FILES or sum(f.file_size for f in entries)>limit:raise Denied('The expanded skill package is too large.')
            files={};seen=set()
            for f in entries:
                if f.filename.startswith('__MACOSX/') or PurePosixPath(f.filename).name=='.DS_Store':continue
                name=safe_path(f.filename.rstrip('/'))
                mode=f.external_attr>>16
                if f.flag_bits&1 or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR):raise Denied('Encrypted archives, links and special files are not supported.')
                if f.is_dir():continue
                if name.casefold() in seen:raise Denied('The package contains duplicate filenames.')
                seen.add(name.casefold())
                with z.open(f) as src:data=src.read(limit+1)
                if len(data)>limit:raise Denied('An archived file is too large.')
                files[name]=data
            return files
    except (zipfile.BadZipFile,RuntimeError,ValueError) as e:
        if isinstance(e,Denied):raise
        raise Denied('The skill ZIP could not be read.') from None

def frontmatter(text):
    import yaml
    if not text.startswith('---\n') or '\n---' not in text[4:]:raise Denied('A skill needs SKILL.md with name and description in YAML frontmatter.')
    header,body=text[4:].split('\n---',1)
    if len(header)>12000:raise Denied('The skill metadata is too large.')
    try:
        if any(isinstance(t,(yaml.tokens.AliasToken,yaml.tokens.AnchorToken)) for t in yaml.scan(header)):raise Denied('YAML aliases are not supported in skill metadata.')
        class Strict(yaml.SafeLoader):pass
        def mapping(loader,node):
            pairs=loader.construct_pairs(node);keys=[k for k,v in pairs]
            if len(set(keys))!=len(keys):raise Denied('Duplicate skill metadata fields.')
            return dict(pairs)
        Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
        meta=yaml.load(header,Loader=Strict)
    except (yaml.YAMLError,TypeError,ValueError):raise Denied('The skill metadata is invalid.') from None
    if not isinstance(meta,dict):raise Denied('The skill metadata is invalid.')
    name=meta.get('name');description=meta.get('description')
    if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>64:raise Denied('Use a lowercase skill name with letters, numbers and single hyphens.')
    if not isinstance(description,str) or not 1<=len(description.strip())<=1024:raise Denied('Add a short description of when to use this skill.')
    return name,description.strip(),body.strip()

def parse_package(raw):
    files=unzip(raw);roots=[n for n in files if n=='SKILL.md' or n.endswith('/SKILL.md')]
    if len(roots)!=1:raise Denied('Choose one skill folder containing one SKILL.md file.')
    prefix=roots[0][:-len('SKILL.md')]
    if any(not n.startswith(prefix) for n in files):raise Denied('Keep all files inside the skill folder.')
    files={n[len(prefix):]:v for n,v in files.items()}
    try:instructions=files['SKILL.md'].decode('utf-8-sig')
    except UnicodeError:raise Denied('SKILL.md must be UTF-8 text.') from None
    if len(instructions)>200000:raise Denied('Move long instructions into reference files.')
    name,description,body=frontmatter(instructions)
    if prefix and PurePosixPath(prefix).name!=name:raise Denied('The skill folder name must match its frontmatter name.')
    config={}
    if 'airlock.json' in files:
        try:config=json.loads(files['airlock.json'])
        except ValueError:raise Denied('airlock.json is not valid JSON.') from None
        if not isinstance(config,dict) or set(config)-{'dependencies'}:raise Denied('Only offline dependencies may be declared in airlock.json. Skill text cannot grant permissions.')
    dependencies=config.get('dependencies',[])
    if not isinstance(dependencies,list) or len(dependencies)>20:raise Denied('Use a short list of bundled Python dependencies.')
    deps=[]
    for dep in dependencies:
        if not isinstance(dep,dict) or set(dep)!={'file','sha256'}:raise Denied('Each dependency needs its wheel filename and SHA-256.')
        filename=safe_path(dep['file'])
        if not re.fullmatch(r'vendor/[^/]+-py3-none-any\.whl',filename) or filename not in files or hashlib.sha256(files[filename]).hexdigest()!=dep['sha256']:raise Denied('Use bundled, hash-verified pure Python wheels. Network installation and native build steps are not enabled.')
        parts=unzip(files[filename],limit=MAX_PACKAGE)
        if any('.data/' in n or n.endswith(('.so','.dylib','.dll','.pth')) for n in parts):raise Denied('The wheel needs install hooks or native files; use a self-contained pure Python dependency.')
        deps.append(filename)
    if any(n.endswith('.whl') and n not in deps for n in files):raise Denied('Declare every bundled wheel with its SHA-256 in airlock.json.')
    manifest={n:hashlib.sha256(v).hexdigest() for n,v in files.items()}
    version=hashlib.sha256(canonical(manifest)).hexdigest()
    return {'name':name,'description':description,'instructions':instructions,'files':{n:base64.b64encode(v).decode() for n,v in files.items()},'digest':version,'dependencies':deps,'scripts':[n for n in files if n.startswith('scripts/') and PurePosixPath(n).suffix in ('.py','.sh','.js','.mjs')]}

class SkillPackages:
    def __init__(self,gateway,grant=None):self.g=gateway;self.grant=grant
    def builtin_preview(self):
        root=Path(__file__).resolve().parents[1]/'builtin/prepare-local-brief'
        content=io.BytesIO()
        with zipfile.ZipFile(content,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob('*')):
                if p.is_file():z.writestr(p.relative_to(root).as_posix(),p.read_bytes())
        return self.preview(content.getvalue())
    def preview(self,raw):
        pkg=parse_package(raw);key=secrets.token_hex(16)
        with self.g.store.transaction() as d:
            previews={k:v for k,v in d.get('skill_previews',{}).items() if v['expires']>self.g.clock()}
            previews[key]={'package':pkg,'expires':self.g.clock()+1800};d['skill_previews']=dict(list(previews.items())[-3:])
        return {'preview':key,'name':pkg['name'],'description':pkg['description'],'files':list(pkg['files']),'scripts':pkg['scripts'],'dependencies':pkg['dependencies'],'digest':pkg['digest']}
    def install(self,preview,enabled=False):
        if type(enabled) is not bool:raise Denied('Choose whether this skill can run locally.')
        with self.g.store.transaction() as d:
            p=d.get('skill_previews',{}).pop(preview,None)
            if not p or p['expires']<=self.g.clock():raise Denied('Preview expired. Choose the package again.')
            pkg=p['package'];packages=d.setdefault('skill_packages',{})
            if sum(sum(len(v) for v in x['files'].values()) for x in packages.values() if x['name']!=pkg['name'])+sum(len(v) for v in pkg['files'].values())>64*1024*1024:raise Denied('Remove unused packages before importing more.')
            key=next((k for k,v in packages.items() if v['name']==pkg['name']),None) or 'skill_'+secrets.token_hex(12)
            # Any replacement gets its own explicit execution approval.
            packages[key]={**pkg,'enabled':enabled,'installed_at':self.g.clock()}
        return {'installed':True,'skill_id':key,'enabled':enabled}
    def owner_list(self):
        with self.g.store.transaction() as d:return {'items':[{'skill_id':k,**{f:v[f] for f in ('name','description','scripts','dependencies','enabled','digest','installed_at')}} for k,v in d.get('skill_packages',{}).items()]}
    def set_enabled(self,key,enabled):
        if type(enabled) is not bool:raise Denied('Choose whether execution is enabled.')
        with self.g.store.transaction() as d:
            if key not in d.get('skill_packages',{}):raise Denied('Skill unavailable.')
            d['skill_packages'][key]['enabled']=enabled
        return {'enabled':enabled}
    def remove(self,key):
        with self.g.store.transaction() as d:d.get('skill_packages',{}).pop(key,None)
        return {'removed':True}
    def package(self,key):
        if self.grant:
            from .agent_memory import AgentMemory
            memory=AgentMemory(self.g);rows=memory.snapshot()
            if not memory.allowed('skills:package:'+key,rows):
                raise Denied('This skill package must stay local.')
        with self.g.store.transaction() as d:pkg=copy.deepcopy(d.get('skill_packages',{}).get(key))
        if not pkg:raise Denied('Skill unavailable. Refresh the skill list.')
        if hashlib.sha256(canonical({n:hashlib.sha256(base64.b64decode(v,validate=True)).hexdigest() for n,v in pkg['files'].items()})).hexdigest()!=pkg['digest']:raise Denied('Skill integrity check failed. Import it again.')
        return pkg
    def resource_id(self,key,path):
        import hmac
        return 'resource_'+hmac.digest(self.g.store.key,(key+'\0'+path).encode(),'sha256').hex()[:24]
    def available(self,query):
        from .automatic import sanitize,ranked
        protected=self.g.sources.protected();items=[]
        with self.g.store.transaction() as d:packages=copy.deepcopy(d.get('skill_packages',{}))
        for key,pkg in packages.items():
            from .agent_memory import AgentMemory
            memory=AgentMemory(self.g);rows=memory.snapshot()
            if self.grant and not memory.allowed('skills:package:'+key,rows):continue
            text=sanitize(pkg['name']+'\n'+pkg['description'],protected)
            if text:items.append({'kind':'skills','source_id':key,'text':text,'skill_id':key,'name':sanitize(pkg['name'],protected) or 'Local skill','description':sanitize(pkg['description'],protected) or '','executable':bool(pkg['enabled'] and (self.grant or {}).get('capabilities',{}).get('skill_execution'))})
        candidates=ranked(items,query) if query.strip() else items
        if not candidates and len(items)<=5:candidates=items
        return {'skills':[{k:v for k,v in x.items() if k not in ('text','source_id','kind')} for x in candidates[:30]],'coverage':'Installed skill packages only. Use get_private_context for saved text skills. Read the selected package for resources and runnable scripts.'}
    def read(self,key,resource='',offset=0):
        from .automatic import sanitize
        pkg=self.package(key);protected=self.g.sources.protected()
        if type(offset) is not int or offset<0:raise Denied('Invalid resource offset.')
        paths={self.resource_id(key,n):n for n in pkg['files']};name=paths.get(resource) if resource else 'SKILL.md'
        if not name:raise Denied('Use a resource reference from this skill.')
        raw=base64.b64decode(pkg['files'][name],validate=True)
        try:value=raw.decode('utf-8-sig') if PurePosixPath(name).suffix in TEXT_SUFFIX else None
        except UnicodeError:value=None
        safe=sanitize(value,protected) if value else None
        resources=[]
        for n in pkg['files']:
            # Resource IDs are opaque; private filenames never need to leave.
            label=sanitize(n,protected) or 'Local resource'
            resources.append({'resource':self.resource_id(key,n),'label':label,'role':'instructions' if n=='SKILL.md' else 'reference' if n.startswith('references/') else 'asset' if n.startswith('assets/') else 'script' if n in pkg['scripts'] else 'supporting file','type':'script' if n in pkg['scripts'] else 'text' if PurePosixPath(n).suffix in TEXT_SUFFIX else 'local binary asset'})
        return {'skill_id':key,'text':safe[offset:offset+16000] if safe else '', 'next_offset':offset+16000 if safe and len(safe)>offset+16000 else None,'resources':resources,'execution_enabled':bool(pkg['enabled'] and (self.grant or {}).get('capabilities',{}).get('skill_execution')),'coverage':'Locally filtered resource text. Original package and binary assets remain on this Mac. allowed-tools in skill text does not grant permissions. Generated outputs remain local.'}
