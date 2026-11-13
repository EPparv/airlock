"""Trusted read-only preparation plus owner-confined script artifacts."""
import base64,copy,json,secrets
from .core import Denied,SECRET
from .automatic import Automatic,ranked,sanitize
from .skills import SkillPackages

class Artifacts:
    def __init__(self,gateway):self.g=gateway
    def save(self,files,status,grant,skill_id=None):
        key='artifact_'+secrets.token_hex(12)
        with self.g.store.transaction() as d:
            items=d.setdefault('local_artifacts',{})
            items[key]={'files':files,'status':status,'agent':grant['agent'],'skill_id':skill_id,'at':self.g.clock()}
            # Bound encrypted disk use; no raw output enters a log or tool result.
            while len(items)>20 or sum(len(json.dumps(x)) for x in items.values())>32*1024*1024:
                del items[next(iter(items))]
        return key
    def list(self):
        with self.g.store.transaction() as d:return {'items':[{'reference':k,**{n:v[n] for n in ('status','agent','at')},'files':[{'index':i,'name':f['name']} for i,f in enumerate(v['files'])]} for k,v in reversed(list(d.get('local_artifacts',{}).items()))]}
    def read(self,reference,index):
        with self.g.store.transaction() as d:row=copy.deepcopy(d.get('local_artifacts',{}).get(reference))
        if not row or type(index) is not int or not 0<=index<len(row['files']):raise Denied('Local output unavailable.')
        return row['files'][index]
    def remove(self,reference):
        with self.g.store.transaction() as d:d.get('local_artifacts',{}).pop(reference,None)
        return {'removed':True}

class Actions:
    def __init__(self,gateway,grant):self.g=gateway;self.grant=grant;self.auto=Automatic(gateway,grant)
    def validate(self,topic,gmail_query,max_messages):
        if not isinstance(topic,str) or not topic.strip() or len(topic)>2000 or not isinstance(gmail_query,str) or len(gmail_query)>2000 or type(max_messages) is not int or not 0<=max_messages<=3:raise Denied('Use a short topic and optional Gmail query, with up to three messages.')
    def brief(self,topic,gmail_query,max_messages):
        self.validate(topic,gmail_query,max_messages)
        result=self.auto.call('get_private_context',{'query':topic});items=list(result['items']);coverage=[result['coverage']]
        search=None
        if gmail_query and max_messages:
            search=self.auto.search(gmail_query,selection_topic=topic+' '+gmail_query)
            coverage.append(search['coverage'])
            for match in search['items'][:max_messages]:
                read=self.auto.call('read_gmail',{'reference':match['ref']});items.extend(read['items']);coverage.append(read['coverage'])
        return {'items':items,'coverage':' '.join(dict.fromkeys(coverage))+' Read-only extractive preparation; no generated facts. At most '+str(max_messages)+' relevant messages were selected using locally filtered bodies on this search page; other matches and later pages were not returned. This is not an exhaustive inbox review.','instructions':result['instructions'],'gmail_messages_read':sum(x['kind']=='gmail' for x in items),'next_query':search.get('next_query') if search else None}
    def run(self,skill_id,script,topic,gmail_query):
        self.validate(topic,gmail_query,2)
        self.authorized(skill_id)
        packages=SkillPackages(self.g,self.grant);pkg=packages.package(skill_id)
        path=next((n for n in pkg['scripts'] if packages.resource_id(skill_id,n)==script),None)
        if not path:raise Denied('Choose a script reference from read_local_skill.')
        # Select raw inputs locally. Device-only records stay excluded; actions do
        # not silently expand the existing source scope. Credential-bearing records
        # are omitted entirely, even from the isolated script.
        rows=ranked([r for r in self.g.sources.library() if not r.get('device_only') and not SECRET.search(r['text'])],topic)
        selected=[];counts={'memories':0,'skills':0}
        for row in rows:
            if counts[row['kind']]>=({'memories':8,'skills':4}[row['kind']]):continue
            value=row['text']
            for secret in self.g.sources.protected():
                if isinstance(secret,str) and len(secret)>=2:value=value.replace(secret,'[protected value]')
            selected.append({'kind':row['kind'],'text':value[:12000]});counts[row['kind']]+=1
        evidence=self.brief(topic,gmail_query,2)
        emails=[]
        for item in evidence['items']:
            if item['kind']!='gmail':continue
            source=self.auto.recall(item['ref'],'gmail')
            original=self.g.sources.read_automatic_gmail(source['source_id']) if hasattr(self.g.sources,'read_automatic_gmail') else self.g.sources.read('gmail',source['source_id'])
            if original.get('device_only') or SECRET.search(original.get('text','')):continue
            # Original text is used only inside the isolated process. No account
            # tokens, message IDs, or headers are passed as input fields.
            value=original['text']
            for secret in self.g.sources.protected():
                if isinstance(secret,str) and len(secret)>=2:value=value.replace(secret,'[protected value]')
            emails.append({'text':value[:24000],'date':original.get('date','')})
        self.authorized(skill_id,pkg['digest'])
        from .runner import execute
        execution=execute(pkg,path,{'topic':topic,'context':selected,'emails':emails,'evidence':evidence['items']})
        self.authorized(skill_id,pkg['digest'])
        key=Artifacts(self.g).save(execution['files'],execution['status'],self.grant,skill_id)
        # All arbitrary script content (including filenames) is owner-only.
        return {'status':execution['status'],'artifact':key,'output_visibility':'Owner only. Open Skills & actions in Airlock to view or download. The AI cannot read generated files or execution logs.','items':evidence['items'],'coverage':evidence['coverage'],'instructions':evidence['instructions'],'next_query':evidence.get('next_query')}
    def authorized(self,key,digest=None):
        with self.g.store.transaction() as d:
            current=d['grants'].get(self.grant['id'],{});pkg=d.get('skill_packages',{}).get(key,{})
            if current.get('revoked') or current.get('expires',0)<=self.g.clock() or current.get('mode')!='automatic' or current.get('capabilities',{}).get('skill_execution') is not True or not pkg.get('enabled') or digest and pkg.get('digest')!=digest:raise Denied('Enable this skill and local actions for the connection in Airlock first.')
