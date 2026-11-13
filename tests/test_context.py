import base64,copy,io,json,re,zipfile
import pytest
from starlette.testclient import TestClient
from privacy_layer.context import ContextHub,parse_context
from privacy_layer.core import EncryptedStore,Gateway,Denied
from privacy_layer.sources import LocalSources
from privacy_layer.server import owner_app

@pytest.fixture
def context(tmp_path):
 home=tmp_path/'home';home.mkdir();now=[1800000000]
 s=LocalSources(key=b'k'*32,context_home=home)
 s.snapshot=lambda:copy.deepcopy({'settings':{},'workspace':{},'memories':[{'id':'existing','text':'I lead a solar startup.'}],'skills':[{'id':'style','text':'Prefer concise answers.'}]})
 st=EncryptedStore(tmp_path/'context.enc',b'k'*32);s.connection_store=st;g=Gateway(st,s,lambda:now[0])
 return s,g,ContextHub(st,home,g.clock),home,now

def code(h):return re.search(r'transfer_code "([^"]+)"',h.transfer_start()['prompt'])[1]

def test_mixed_markdown_complete_skills_and_scope():
 p=parse_context('reply.md',b'# Memories\n- Solar startup.\n- Interview November 12.\n# Skills\n## Preparation\n1. Check requirements.\n2. Use project examples.\n\nKeep the full checklist.\n## Writing\nUse plain language.\n# Scope\nCurrent chat only.')
 assert [x['kind'] for x in p['items']]==['memories','memories','skills','skills']
 assert 'Keep the full checklist' in p['items'][2]['text'] and p['scope']=='Current chat only.'

def test_json_objects_dedup_and_private_flags():
 p=parse_context('reply.md',b'```json\n{"memories":["Fact","fact",{"text":"Private fact","device_only":true}],"skills":[{"name":"Writing","instructions":"Lead with evidence."}]}\n```')
 assert len(p['items'])==3 and p['items'][1]['device_only'] and 'Lead with evidence.' in p['items'][2]['text']

def test_plain_text_and_long_skills():
 p=parse_context('note.txt',b'I lead a startup.\n\nWhen answering, use short sentences.\n\nAlways distinguish facts from plans.')
 assert [x['kind'] for x in p['items']]==['memories','skills','skills']
 raw=('Full skill step. '*1200).strip();p=parse_context('SKILL.md',raw.encode())
 assert ''.join(x['text'] for x in p['items'])==raw and all(x['kind']=='skills' for x in p['items'])

@pytest.mark.parametrize('text',[b'{"memories": ["unfinished"',b'{"conversations":[]}',b'[{"mapping":{}}]',b''])
def test_bad_exports_do_not_become_memories(text):
 with pytest.raises(Denied):parse_context('reply.md',text)

def test_archive_text_only_without_extracting(tmp_path):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:
  z.writestr('../../memories.md','Phoenix interview next week.');z.writestr('prep/SKILL.md','Use evidence.');z.writestr('prep/run.py','MUST_NOT_EXECUTE')
 p=parse_context('context.zip',out.getvalue())
 assert {x['kind'] for x in p['items']}=={'memories','skills'} and 'MUST_NOT_EXECUTE' not in str(p)
 assert not (tmp_path/'memories.md').exists()

def test_commit_retrieval_duplicates_encryption_and_undo(context):
 s,g,h,_,_=context;p=h.preview('Transfer.md',b'# Memories\n- I lead a solar startup.\n- Phoenix interview November 12.\n# Skills\n## Preparation\nUse the solar launch example.')
 assert len(s.library())==2
 result=h.commit(p['id'],list(range(len(p['items']))),s.library());assert result['added']==2 and result['skipped']==1
 grant=g.create(agent='codex',purpose='Personal context',views=[],mode='automatic',approved=True)
 wire=json.dumps(g.call(grant['token'],'get_private_context',{'query':'Phoenix solar launch interview'}))
 assert 'November 12' in wire and 'solar launch example' in wire and b'Phoenix' not in h.store.path.read_bytes()
 h.remove(result['batch_id']);assert len(s.library())==2

def test_private_import_filtered_before_agent_retrieval(context):
 s,g,h,_,_=context;p=h.preview('context.json',json.dumps({'memories':[{'text':'PRIVATE_RECORD_CANARY','device_only':True},'Interview tomorrow. Passport number K1234567. Email fictional@example.test.'],'skills':['Lead with evidence.']}).encode())
 h.commit(p['id'],list(range(len(p['items']))),s.library());grant=g.create(agent='codex',purpose='Context test',views=[],mode='automatic',approved=True)
 wire=json.dumps(g.call(grant['token'],'get_private_context',{'query':'interview PRIVATE_RECORD_CANARY evidence'}))
 assert 'tomorrow' in wire and all(x not in wire for x in ['K1234567','fictional@example.test','PRIVATE_RECORD_CANARY'])

def test_live_sources_sync_disconnect_and_ignore_symlinks(context):
 s,g,h,home,_=context;memory=home/'.claude/projects/example/memory/MEMORY.md';memory.parent.mkdir(parents=True);memory.write_text('Phoenix interview November 12.')
 skill=home/'.claude/skills/prep/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('Use the Phoenix example.')
 assert len(s.library())==2
 h.toggle('claude-memory',True);h.toggle('claude-skills',True);assert len(s.library())==4
 memory.write_text('Phoenix interview November 14.');assert any('November 14' in x['text'] for x in s.library()) and not any('November 12' in x['text'] for x in s.library())
 h.toggle('claude-memory',False);assert len(s.library())==3 and memory.read_text()=='Phoenix interview November 14.'
 folder=home/'.codex/memories';folder.mkdir(parents=True);secret=home/'secret.txt';secret.write_text('SECRET_CANARY');(folder/'memory_summary.md').symlink_to(secret);(folder/'raw_memories.md').write_text('RAW_CHAT_CANARY')
 h.toggle('codex-memory',True);assert h.files('codex-memory')==[] and 'CANARY' not in str(s.library())

def test_agent_transfer_requires_one_time_owner_code_and_save(context):
 s,g,h,_,_=context;grant=g.create(agent='codex',purpose='Transfer',views=[],mode='automatic',approved=True)
 args={'transfer_code':'invented','memories':['Phoenix interview November 12.'],'skills':['For Phoenix, use an evidence checklist.'],'scope':'Current chat only.'}
 with pytest.raises(Denied):g.call(grant['token'],'stage_context_import',args)
 args['transfer_code']=code(h);result=g.call(grant['token'],'stage_context_import',args)
 assert result['staged'] and 'Phoenix' not in str(result) and len(s.library())==2
 with pytest.raises(Denied):g.call(grant['token'],'stage_context_import',args)
 p=h.transfer_status()['preview'];h.commit(p['id'],[0,1],s.library())
 wire=json.dumps(g.call(grant['token'],'get_private_context',{'query':'Phoenix interview checklist'}))
 assert 'November 12' in wire and 'evidence checklist' in wire and h.transfer_status()['saved']

def test_transfer_expiry_replacement_revocation_size(context):
 s,g,h,_,now=context;grant=g.create(agent='codex',purpose='Transfer',views=[],mode='automatic',approved=True)
 args={'transfer_code':code(h),'memories':['Context'],'skills':[],'scope':'Chat only'};now[0]+=1801
 with pytest.raises(Denied):g.call(grant['token'],'stage_context_import',args)
 args['transfer_code']=code(h);code(h)
 with pytest.raises(Denied):g.call(grant['token'],'stage_context_import',args)
 args['transfer_code']=code(h);args['memories']=['x'*200001]
 with pytest.raises(Denied):g.call(grant['token'],'stage_context_import',args)
 args['memories']=['Context'];g.revoke(grant['id'])
 with pytest.raises(Denied):g.call(grant['token'],'stage_context_import',args)
 assert len(s.library())==2

def test_owner_endpoints_are_separate_from_agent_access(context):
 s,g,h,_,_=context;grant=g.create(agent='codex',purpose='Test',views=[],mode='automatic',approved=True)
 with TestClient(owner_app(g,'owner-test'),base_url='http://127.0.0.1:8791') as c:
  for action in ['context-status','context-preview','context-commit','context-transfer-start','context-remove','context-source']:
   assert c.post('/api/'+action,json={},headers={'Authorization':'Bearer '+grant['token']}).status_code==401
  headers={'Authorization':'Bearer owner-test'};p=c.post('/api/context-preview',json={'name':'context.md','content':base64.b64encode(b'# Memories\nNew project\n# Skills\nUse evidence').decode()},headers=headers).json()
  assert len(p['items'])==2
  result=c.post('/api/context-commit',json={'id':p['id'],'indices':[0,1]},headers=headers)
  assert result.status_code==200 and result.json()['added']==2
  assert c.post('/api/context-source',json={'source':'../../secrets','enabled':True},headers=headers).status_code==400
  assert c.get('/context.js').status_code==200

@pytest.mark.parametrize('flags',[{'meta':{'sensitive':True}},{'meta':{'privacy':'local_only'}},{'meta':{'status':'archived'}}])
def test_source_privacy_metadata_is_preserved(flags):
 p=parse_context('context.json',json.dumps({'memories':[{'text':'PRIVATE_RECORD',**flags}]}).encode())
 assert p['items'][0]['device_only']

def test_dedup_does_not_discard_a_stricter_privacy_flag(context):
 s,g,h,_,_=context;p=h.preview('context.json',json.dumps({'memories':[{'text':'I lead a solar startup.','device_only':True}]}).encode())
 result=h.commit(p['id'],[0],s.library())
 assert result['privacy_updated']==1 and result['added']==0
 assert next(x for x in s.library() if x['source_id']=='existing')['device_only']
 h.remove(result['batch_id'])
 assert not next(x for x in s.library() if x['source_id']=='existing')['device_only']
