"""Local context onboarding. Sources are read-only; additions stay encrypted here.

Agents can stage a transfer only with a short-lived owner-created code. Staging
never changes the active library. Only the owner endpoint can save or remove it.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import time
import zipfile
from .core import Denied, normalized

MAX_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 2000
SPECS = {
    'claude-memory': ('Claude Code memories', ('.claude/projects/*/memory/*.md',), 'memories'),
    'claude-skills': ('Claude instructions & skills', ('.claude/CLAUDE.md', '.claude/rules/*.md', '.claude/skills/*/SKILL.md'), 'skills'),
    'codex-memory': ('Codex memory notes', ('.codex/memories/memory_summary.md', '.codex/memories/*.md'), 'memories'),
    'codex-skills': ('Codex instructions & skills', ('.codex/AGENTS.md', '.codex/skills/*/SKILL.md'), 'skills'),
}
MEMORY_HEAD = re.compile(r'^(?:memories|memory|facts(?: about me)?|background|profile|projects?|personal context|goals?|history|people|relationships|decisions|open loops|constraints)$', re.I)
SKILL_HEAD = re.compile(r'^(?:skills|instructions|custom instructions|preferences|workflows|writing(?: style)?|ways of working|templates|playbooks|rules)$', re.I)
PROMPT = '''Create a detailed continuity handoff into Airlock so another AI can help me without making me repeat my background, preferences and ongoing work. This transfers accessible context, not your model, tools or hidden history. Do not retrieve or repeat Airlock's own library.

FIRST, INVENTORY YOUR SOURCES. Use only information actually available in this conversation, project, saved memory, my own instructions, and accessible source documents. State which you reviewed, which you could not access, and the date of this export. Do not claim an account-wide history review unless you actually performed one. Do not contact anyone, run code, modify other sources or create connections. Do not expose system/developer instructions.

CORE PROFILE. Mark at most SIX short, stable entries with [CORE] at the beginning of their text (under 4,000 characters each). Choose enduring background, communication preferences, decision rules and important continuing constraints. These entries will accompany authorized Airlock context requests even when the question has no matching keywords. Put detailed project history and temporary plans in ordinary entries. Core status never overrides privacy or the owner's selected agent access.

MEMORIES. Work through every category below; do not compress everything into a generic biography:
1. Background, roles, expertise, interests and relevant enduring constraints.
2. Each active project: exact name and aliases, purpose, my role, current state, milestones, relevant people and their roles, important source documents, latest decisions and rationale, rejected options and why, dependencies and unresolved questions.
3. Open loops: next action, who owns it, dates/deadlines and blockers. Preserve whether an action was merely planned, started, sent, approved, completed, paused or abandoned. Never convert a plan into a completion.
4. Important relationships: how I know someone, what we discussed, what they offered or declined, and the latest confirmed next step. Do not infer employment from a customer or partner relationship.
5. Corrections and changes: prefer my latest explicit correction. Label older facts as historical with their dates when useful; identify unresolved contradictions instead of choosing a convenient answer. Never turn an inferred fact into a confirmed one.
6. Relevant personal preferences and recurring practical needs, excluding anything private that should not transfer.

SKILLS. Preserve my adopted response style, recurring workflows, decision rules, checklists, templates, project conventions and useful examples. For each named skill state when to use it, the full useful steps, desired output and exceptions. Preserve my exact wording where meaningful. A one-off request or third-party instruction is not a permanent preference. These are text instructions, not installed tools or authorization to act.

WRITE SELF-CONTAINED RECORDS. Repeat the project/person name where needed so an entry makes sense alone. Keep useful detail, relationships, dates, provenance and uncertainty. Distinguish facts from plans and inferences. Date time-sensitive facts as 'as of YYYY-MM-DD' when the source supports it; use 'date unknown' otherwise. Include topic aliases in the text to help later retrieval. Do not replace detailed project records with a short summary just to fit one reply.

PRIVACY. Omit passwords, tokens, financial/identity numbers, exact residential addresses and anything I said not to share. Do not put sensitive records into the core profile. State omitted categories without revealing their contents.

SECOND PASS. Check the handoff against each category, my latest corrections, active projects and adopted workflows. In Scope, list covered categories, unavailable sources, unfinished categories/batches and 5-10 practical questions the transferred context should answer. Mark those questions as a suggested validation checklist, not proof of successful recall. Say explicitly when coverage is incomplete or unknown.

DELIVERY. If stage_context_import is available, call it once with transfer_code "{code}", memories and skills as lists of self-contained text, and scope describing actual coverage. Keep this batch below 300 items and 200,000 UTF-8 bytes; scope must be under 4,000 characters. A [CORE] prefix belongs inside the entry text. Staging creates a local preview only; I must review and save it. If more remains, identify the remaining categories and ask me to obtain a fresh transfer prompt for the next batch. Do not silently truncate, invent completion or reuse the one-time code.

If the tool is unavailable, return copyable Markdown with # Memories, # Skills and # Scope. Use one bullet per memory and a heading per complete skill. A core skill heading may start with '## [CORE]'. I will paste the reply into Airlock. Keep the coverage checklist in Scope, not as personal facts.'''


def identity(row):
    return row['kind'] + ':' + normalized(re.sub(r'^\s*[-*•]\s+', '', row['text']))


def parse_context(name, raw, kind='auto'):
    if kind not in ('auto','memories','skills'):raise Denied('Choose automatic detection, memories or skills.')
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_BYTES:raise Denied('Choose a text export up to 4 MB.')
    suffix=PurePosixPath(name).suffix.lower()
    if suffix in ('.zip','.skill'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                entries=z.infolist()
                if len(entries)>3000:raise Denied('This archive has too many files. Use a memory or skills export.')
                allowed={'memories.json','memory.json','memories.md','memory.md','memory.txt','memories.txt','skills.json','skill.md','claude.md','agents.md','custom_instructions.json','custom_instructions.md','custom_instructions.txt','context.json','context.md'}
                selected=[f for f in entries if not f.is_dir() and PurePosixPath(f.filename).name.lower() in allowed]
                if not selected:raise Denied('No memory or skill files found. For a chat-history archive, use Copy transfer prompt instead.')
                if sum(f.file_size for f in selected)>MAX_BYTES or len(selected)>300:raise Denied('The archive expands beyond the 4 MB / 300-file limit.')
                items=[];scopes=[]
                for f in selected:
                    if f.flag_bits&1:raise Denied('Unlock the archive before importing it.')
                    with z.open(f) as stream:data=stream.read(MAX_BYTES+1)
                    if len(data)>MAX_BYTES:raise Denied('An archived file is too large.')
                    result=parse_context(f.filename,data,kind);items+=result['items'];scopes.append(result['scope'])
                return finish(items,'\n'.join(filter(None,scopes)))
        except zipfile.BadZipFile:raise Denied('That archive could not be read. Try a text or Markdown export.') from None
    if suffix and suffix not in ('.md','.txt','.json','.mdc'):raise Denied('Use text, Markdown, JSON, a .skill file or a ZIP of memory/skill files.')
    try:text=raw.decode('utf-8-sig').strip()
    except UnicodeError:raise Denied('This is not a readable text export. Choose a text, Markdown or JSON file.') from None
    text=re.sub(r'^```(?:json|markdown|md|text)?\s*\n([\s\S]*)\n```\s*$',r'\1',text,flags=re.I).strip()
    if not text:raise Denied('Paste some context or choose a nonempty file.')
    items=[];scope=''
    def add(value,target):
        if isinstance(value,list):
            for x in value:add(x,target)
            return
        device_only=False;core=False
        if isinstance(value,dict):
            meta=value.get('meta',{}) if isinstance(value.get('meta',{}),dict) else {}
            device_only=value.get('device_only') is True or value.get('privacy') in ('device','local','local_only','private_only') or meta.get('privacy') in ('local_only','private_only') or bool(meta.get('sensitive')) or meta.get('status','active')!='active'
            core=value.get('core') is True
            body=next((value[k] for k in ('text','content','instructions','memory','body') if isinstance(value.get(k),str)),None)
            if not body:return
            title=value.get('title') or value.get('name')
            value=(title+'\n\n' if isinstance(title,str) else '')+body
        if not isinstance(value,str) or not value.strip():return
        value=value.strip()
        marker=re.match(r'^(?:#{1,6}\s*|[-*•]\s*)?\[CORE\]\s*',value,re.I)
        if marker:core=True;value=value[marker.end():].strip()
        if core and len(value)>4000:raise Denied('Keep each core profile entry under 4,000 characters. Put detailed history in separate records.')
        for offset in range(0,len(value),12000):
            items.append({'kind':target,'text':value[offset:offset+12000], 'device_only':device_only,'core':core,'source':PurePosixPath(name).name[:120]})
    if text[:1] in ('{','[') or suffix=='.json':
        try:
            data=json.loads(text)
        except (ValueError,TypeError):raise Denied('The JSON reply is incomplete. Paste the complete reply, or ask for Markdown.') from None
        if isinstance(data,dict) and any(k in data for k in ('mapping','conversations','chat_messages')) or isinstance(data,list) and any(isinstance(x,dict) and any(k in x for k in ('mapping','chat_messages')) for x in data):
            raise Denied('This is chat history, not saved context. Copy the transfer prompt to extract memories and reusable skills first.')
        if isinstance(data,dict) and any(k in data for k in ('memories','skills','custom_instructions','user_instructions','preferences','profile')):
            for key,target in [('memories','memories'),('profile','memories'),('skills','skills'),('custom_instructions','skills'),('user_instructions','skills'),('preferences','skills')]:
                if key in data:add(data[key],target if kind=='auto' else kind)
            scope=data.get('scope','') if isinstance(data.get('scope',''),str) else ''
        else:add(data,'memories' if kind=='auto' else kind)
    else:
        explicit=kind!='auto'
        target=kind if explicit else 'skills' if PurePosixPath(name).name.lower() in ('skill.md','claude.md','agents.md','custom_instructions.md','custom_instructions.txt') else 'memories'
        # A native skill file is one complete instruction document, including its
        # frontmatter. Linked resources/scripts are never opened or executed.
        if target=='skills' and (explicit or PurePosixPath(name).name.lower() in ('skill.md','claude.md','agents.md')):add(text,'skills')
        else:
            buffer=[]
            def flush():
                nonlocal buffer,scope
                block='\n'.join(buffer).strip();buffer=[]
                if not block:return
                if target=='scope':scope+='\n'+block;return
                chunks=re.split(r'\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)])\s)',block) if target=='memories' else [block]
                for chunk in chunks:
                    chunk=chunk.strip()
                    inferred=target
                    if not explicit and target=='memories' and re.match(r'^(?:[-*•]\s*)?(?:When (?:answering|writing|responding)|Always |Never |Writing style:|Workflow:|Prefer (?:concise|detailed|short|plain))',chunk,re.I):inferred='skills'
                    if re.sub(r'[#*\s]','',chunk):add(chunk,inferred)
            for line in text.splitlines():
                heading=re.match(r'^\s{0,3}(?:#{1,6}\s+|\*\*)(.*?)(?:\*\*)?\s*:?[ \t]*$',line)
                label=heading[1].strip().rstrip(':') if heading else ''
                if not explicit and heading and (MEMORY_HEAD.fullmatch(label) or SKILL_HEAD.fullmatch(label) or label.lower()=='scope'):
                    flush();target='scope' if label.lower()=='scope' else 'skills' if SKILL_HEAD.fullmatch(label) else 'memories'
                elif heading and target=='skills':flush();buffer.append(line)
                else:buffer.append(line)
            flush()
    return finish(items,scope)


def finish(items,scope=''):
    unique={}
    for row in items:
        key=identity(row)
        if key in unique:
            unique[key]['device_only']|=row.get('device_only',False)
            unique[key]['core']|=row.get('core',False)
        else:unique[key]=row
    if not unique:raise Denied('No memories or skills found. Paste the context itself, or try the transfer prompt.')
    if len(unique)>MAX_ITEMS:raise Denied('This contains more than 2,000 items. Import a smaller batch.')
    return {'items':list(unique.values()),'scope':scope.strip()[:4000]}


class ContextHub:
    def __init__(self,store,home=None,clock=time.time):self.store=store;self.home=Path(home or Path.home());self.clock=clock

    def files(self,source):
        if source not in SPECS:raise Denied('Choose a supported memory source.')
        found=[]
        for pattern in SPECS[source][1]:
            for path in self.home.glob(pattern):
                if path.name=='raw_memories.md':continue
                rel=path.relative_to(self.home)
                if any(p.startswith('.') for p in rel.parts[2:]) or any(p.is_symlink() for p in [path,*list(path.parents)[:len(rel.parts)-1]]):continue
                try:
                    if path.is_file() and 0<path.stat().st_size<=1024*1024:found.append(path)
                except OSError:continue
        if len(found)>500:raise Denied('This source has more than 500 files. Import selected files instead.')
        if sum(p.stat().st_size for p in set(found))>MAX_BYTES:raise Denied('This source has more than 4 MB of notes. Import selected files instead.')
        return sorted(set(found))

    def rows(self):
        with self.store.transaction() as d:
            imports=list(d.get('context_batches',{}).values());enabled=list(d.get('context_sources',[]));shared=dict(d.get('shared_context',{}));packages=dict(d.get('skill_packages',{}))
        result=[dict(row) for batch in imports for row in batch['items']]
        for key,row in shared.items():
            if not row.get('deleted'):
                result.append({'kind':row['kind'],'text':('Owner-reviewed agent note (not independently verified): ' if row.get('owner_approved') else 'Agent-authored note (not independently verified): ')+row['text'],'source_id':'shared:'+key,'origin':'Shared agent note','device_only':False,'shared_reference':key,'revision':row['revision']})
        for key,pkg in packages.items():
            result.append({'kind':'skills','text':pkg['instructions'],'source_id':'package:'+key,'origin':'Installed skill package','device_only':False,'package_digest':pkg['digest']})
        for source in enabled:
            if source not in SPECS:continue
            try:paths=self.files(source)
            except Denied:continue
            for path in paths:
                try:
                    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                    with os.fdopen(fd,'rb') as f:
                        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):continue
                        raw=f.read(1024*1024+1)
                    if len(raw)>1024*1024:continue
                    parsed=parse_context(path.name,raw,SPECS[source][2])
                    for n,row in enumerate(parsed['items']):
                        ref=hashlib.sha256((source+'\0'+str(path.relative_to(self.home))+'\0'+str(n)).encode()).hexdigest()
                        result.append({**row,'source_id':'linked:'+ref,'origin':SPECS[source][0]})
                except (OSError,Denied):continue
        return result

    def status(self):
        with self.store.transaction() as d:
            enabled=d.get('context_sources',[]);batches=[{'id':k,'label':v['label'],'count':len(v['items']),'at':v['at']} for k,v in d.get('context_batches',{}).items()]
        sources=[]
        for source,(label,_,_) in SPECS.items():
            try:count=len(self.files(source));error=''
            except Denied as e:count=0;error=str(e)
            sources.append({'id':source,'label':label,'files':count,'connected':source in enabled,'error':error})
        return {'sources':sources,'imports':list(reversed(batches))}

    def toggle(self,source,enabled):
        if source not in SPECS or type(enabled) is not bool:raise Denied('Choose a supported source.')
        with self.store.transaction() as d:
            current=set(d.get('context_sources',[]));current.add(source) if enabled else current.discard(source);d['context_sources']=sorted(current)
        return {'connected':enabled}

    def preview(self,name,raw,kind='auto'):
        parsed=parse_context(name,raw,kind);key=secrets.token_urlsafe(18)
        value={**parsed,'label':PurePosixPath(name).name[:120],'expires':self.clock()+1800}
        with self.store.transaction() as d:
            previews={k:v for k,v in d.get('context_previews',{}).items() if v['expires']>self.clock()}
            if len(previews)>=5:previews.pop(next(iter(previews)))
            previews[key]=value;d['context_previews']=previews
        return {'id':key,**value}

    def commit(self,key,indices,existing):
        if not isinstance(indices,list) or not indices or any(type(i) is not int for i in indices):raise Denied('Select at least one item to save.')
        known={identity(r) for r in existing};private={identity(r) for r in existing if r.get('device_only')};added=[];skipped=0;privacy_updated=0;core_updated=0
        with self.store.transaction() as d:
            p=d.get('context_previews',{}).get(key)
            if not p or p['expires']<=self.clock():raise Denied('This preview expired. Paste or choose the file again.')
            if any(i<0 or i>=len(p['items']) for i in indices):raise Denied('The selection is invalid.')
            for batch in d.get('context_batches',{}).values():
                known.update(identity(r) for r in batch['items']);private.update(identity(r) for r in batch['items'] if r.get('device_only'))
            originals={r['kind']+':'+r['source_id']:r for r in existing if r.get('source_id')}
            originals.update({r['kind']+':'+r['source_id']:r for batch in d.get('context_batches',{}).values() for r in batch['items']})
            core_overrides=d.setdefault('memory_core',{})
            for i in dict.fromkeys(indices):
                row=p['items'][i];signature=identity(row)
                if signature in known:
                    if row.get('core') and not row.get('device_only') and signature not in private:
                        match=next(((ref,r) for ref,r in originals.items() if identity(r)==signature and not d.get('memory_policy',{}).get(ref) and not d.get('memory_retired',{}).get(ref)),None)
                        if match and not core_overrides.get(match[0],match[1].get('core',False)):
                            core_overrides[match[0]]=True;core_updated+=1
                    if not row.get('device_only') or signature in private:skipped+=1;continue
                    row={**row,'privacy_override':True,'core':False};privacy_updated+=1
                if row.get('device_only'):private.add(signature)
                known.add(signature);added.append({**row,'source_id':'import:'+secrets.token_hex(16),'origin':'Imported context'})
            if sum(bool(core_overrides.get(ref,r.get('core',False))) for ref,r in originals.items())+sum(bool(r.get('core')) for r in added)>6:
                raise Denied('Keep up to six core profile records. Unpin existing entries in Shared memory or remove extra [CORE] markers, then import again.')
            if core_updated:
                for grant in d['grants'].values():grant['policy_revision']=grant.get('policy_revision',0)+1
            batch_id=secrets.token_hex(12)
            if added:d.setdefault('context_batches',{})[batch_id]={'label':p['label'],'at':self.clock(),'items':added,'scope':p['scope']}
            del d['context_previews'][key]
            t=d.get('context_transfer',{})
            if t.get('preview')==key:t['saved']=True
        return {'added':len(added)-privacy_updated,'privacy_updated':privacy_updated,'core_updated':core_updated,'skipped':skipped,'memories':sum(x['kind']=='memories' and not x.get('privacy_override') for x in added),'skills':sum(x['kind']=='skills' and not x.get('privacy_override') for x in added),'batch_id':batch_id if added else None}

    def remove(self,batch_id):
        with self.store.transaction() as d:d.get('context_batches',{}).pop(batch_id,None)
        return {'removed':True}

    def transfer_start(self):
        code=secrets.token_urlsafe(18)
        with self.store.transaction() as d:
            d['context_previews']={k:v for k,v in d.get('context_previews',{}).items() if v['expires']>self.clock()}
            d['context_transfer']={'hash':hashlib.sha256(code.encode()).hexdigest(),'expires':self.clock()+1800}
        return {'prompt':PROMPT.format(code=code),'expires':self.clock()+1800}

    def transfer_status(self):
        with self.store.transaction() as d:
            t=d.get('context_transfer',{})
            p=d.get('context_previews',{}).get(t.get('preview'))
            return {'waiting':bool(t and t.get('expires',0)>self.clock() and not t.get('used')),'saved':bool(t.get('saved')),'preview':{'id':t['preview'],**p} if p and p['expires']>self.clock() else None}

    def stage(self,grant,code,memories,skills,scope):
        if not isinstance(code,str) or len(code)>100 or not isinstance(scope,str) or len(scope)>4000:raise Denied('Invalid transfer details.')
        if not isinstance(memories,list) or not isinstance(skills,list) or len(memories)+len(skills)>300 or any(not isinstance(x,str) for x in memories+skills):raise Denied('Transfer up to 300 text memories and skills per batch.')
        raw=json.dumps({'memories':memories,'skills':skills,'scope':scope},ensure_ascii=False).encode()
        if len(raw)>200000:raise Denied('This transfer is too large. Use a smaller batch under 200,000 UTF-8 bytes.')
        parsed=parse_context('Agent transfer.json',raw);key=secrets.token_urlsafe(18)
        with self.store.transaction() as d:
            t=d.get('context_transfer',{});g=d['grants'].get(grant['id'],{})
            if g.get('revoked',True) or g.get('expires',0)<=self.clock():raise Denied('This connection is no longer active.')
            if t.get('used') or t.get('expires',0)<=self.clock() or not secrets.compare_digest(t.get('hash',''),hashlib.sha256(code.encode()).hexdigest()):raise Denied('Open Add context in the control panel and copy a fresh transfer prompt. Existing access does not allow unattended imports.')
            previews={k:v for k,v in d.get('context_previews',{}).items() if v['expires']>self.clock()}
            if len(previews)>=5:previews.pop(next(iter(previews)))
            previews[key]={**parsed,'label':'Transfer from '+grant['agent'],'expires':self.clock()+1800};d['context_previews']=previews
            t.update(used=True,preview=key)
        return {'staged':True,'memories':sum(x['kind']=='memories' for x in parsed['items']),'skills':sum(x['kind']=='skills' for x in parsed['items']),'message':'Context is waiting in the owner’s Add context screen. It is not saved or available to agents until the owner clicks Add. No other source was changed.'}
