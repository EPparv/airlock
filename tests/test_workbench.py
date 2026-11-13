import base64,hashlib,io,json,os,sys,zipfile
from pathlib import Path
import pytest
from privacy_layer.core import Denied
from privacy_layer.skills import SkillPackages,parse_package
from privacy_layer.shared import SharedContext
from privacy_layer.context import ContextHub
from privacy_layer.actions import Actions,Artifacts
from privacy_layer.runner import execute


def archive(files):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for n,v in files.items():z.writestr(n,v)
    return b.getvalue()

def package(script='print("hello")',extras=None):
    return archive({'SKILL.md':'---\nname: interview-brief\ndescription: Prepare interview evidence locally\n---\nUse evidence dates and avoid assumptions.\n','scripts/main.py':script,'references/style.md':'Keep answers concise.',**(extras or {})})

def setup(bundle):
    g,s,now,views,make=bundle;a=make(mode='automatic',max_calls=100)
    s.search_gmail_page=lambda q,cursor=None:{'items':[{'kind':'gmail','source_id':'e1',**s.read('gmail','e1')}],'next_cursor':None}
    base=s.library;hub=ContextHub(g.store,clock=g.clock);s.library=lambda:base()+hub.rows()
    with g.store.transaction() as d:grant=dict(d['grants'][a['id']])
    return g,s,a,grant

@pytest.mark.parametrize('extra',[{'../outside':'x'},{'/root':'x'},{'bad\\path':'x'},{'A.txt':'a','a.txt':'b'},{'airlock.json':'{"network":true}'},{'vendor/wrong.whl':'bad'}])
def test_malicious_packages_rejected(extra):
    with pytest.raises(Denied):parse_package(package(extras=extra))

def test_full_resources_and_replacement_reapproval(bundle):
    g,s,a,grant=setup(bundle);manager=SkillPackages(g,grant)
    preview=manager.preview(package(extras={'assets/template.bin':b'\x00\xff'}));key=manager.install(preview['preview'],True)['skill_id']
    read=manager.read(key);assert len(read['resources'])==4 and 'avoid assumptions' in read['text']
    assert 'local binary asset' in str(read)
    preview=manager.preview(package('print("changed")'));assert manager.install(preview['preview'])['skill_id']==key
    assert not manager.package(key)['enabled']
    assert 'files' not in str(manager.available('interview'))

def test_private_brief_uses_three_source_types(bundle):
    g,s,a,grant=setup(bundle)
    r=g.call(a['token'],'prepare_private_brief',{'topic':'interview answer style','gmail_query':'pickup','max_messages':2})
    assert {x['kind'] for x in r['items']}=={'memories','skills','gmail'}
    assert r['gmail_messages_read']==1 and 'HIDDEN_' not in json.dumps(r)
    assert 'not an exhaustive inbox review' in r['coverage']
    with g.store.transaction() as d:assert d['disclosures'][-1]['response']==r

def test_cross_agent_updates_conflicts_undo_and_live_revision(bundle):
    g,s,a,grant=setup(bundle);b=g.create(agent='cursor',purpose='Shared context check',views=[],approved=True,mode='automatic')
    args={'operation':'add','kind':'memories','text':'Fictional Zephyr demo deadline is Friday.','reference':'','expected_revision':0}
    with pytest.raises(Denied):g.call(a['token'],'update_shared_context',args)
    g.set_capabilities(a['id'],context_updates=True);g.set_capabilities(b['id'],context_updates=True)
    revision=g.call(a['token'],'context_status',{})['revision']
    proposed=g.call(a['token'],'update_shared_context',args)
    from privacy_layer.agent_memory import AgentMemory
    assert g.call(b['token'],'context_status',{})['revision']==revision
    added=AgentMemory(g).decide(proposed['proposal_id'],True)
    assert g.call(b['token'],'context_status',{})['revision']>revision
    item=g.call(b['token'],'get_private_context',{'query':'Zephyr demo deadline'})['items'][0]
    assert item['shared_reference']==added['reference'] and 'unverified' in item['evidence_type'] or 'not independently verified' in item['evidence_type']
    args.update(operation='update',reference=added['reference'],expected_revision=1,text='Fictional Zephyr demo deadline is Monday.')
    proposed=g.call(b['token'],'update_shared_context',args)
    changed=AgentMemory(g).decide(proposed['proposal_id'],True);assert changed['revision']==2
    with pytest.raises(Denied,match='another agent'):g.call(a['token'],'update_shared_context',args)
    SharedContext(g).undo(added['reference'],2)
    assert 'Friday' in g.call(a['token'],'get_private_context',{'query':'Zephyr'})['items'][0]['text']
    assert s.data['memories','m1']==bundle[1].data['memories','m1']

def test_shared_notes_filter_secrets_and_cannot_edit_original(bundle):
    g,s,a,grant=setup(bundle);g.set_capabilities(a['id'],context_updates=True)
    args={'operation':'add','kind':'skills','text':'Write concise answers.\napi_key=PRIVATE_CREDENTIAL_CANARY','reference':'','expected_revision':0}
    r=g.call(a['token'],'update_shared_context',args);assert 'PRIVATE_CREDENTIAL_CANARY' not in json.dumps(r)
    args.update(operation='update',reference='m1',expected_revision=1)
    with pytest.raises(Denied):g.call(a['token'],'update_shared_context',args)

@pytest.mark.skipif(sys.platform!='darwin',reason='Mac execution boundary')
def test_os_boundary_and_local_output_confinement(bundle,tmp_path):
    g,s,a,grant=setup(bundle);outside=tmp_path/'private.txt';outside.write_text('OUTSIDE_CANARY')
    script='''import json,os,socket,subprocess,base64
from pathlib import Path
checks={}
try:Path(OUTSIDE).read_text();checks['outside_read']=False
except PermissionError:checks['outside_read']=True
try:Path(OUTSIDE+'-write').write_text('x');checks['outside_write']=False
except PermissionError:checks['outside_write']=True
try:socket.create_connection(('127.0.0.1',8791),timeout=1);checks['network']=False
except OSError:checks['network']=True
try:subprocess.run(['/usr/bin/security','find-generic-password'],capture_output=True);checks['child_process']=False
except OSError:checks['child_process']=True
checks['no_inherited_secret']='FAKE_PARENT_SECRET' not in os.environ
checks['assets']=Path('assets/data.txt').read_text()=='asset works'
inputs=json.loads(Path(os.environ['AIRLOCK_INPUT']).read_text())
checks['selected_input']=bool(inputs['context']) and bool(inputs['emails'])
Path(os.environ['AIRLOCK_OUTPUT'],'checks.json').write_text(json.dumps(checks))
print(base64.b64encode(b'HIDDEN_PASSPORT_CANARY').decode())
'''.replace('OUTSIDE',repr(str(outside)))
    manager=SkillPackages(g,grant);key=manager.install(manager.preview(package(script,{'assets/data.txt':'asset works'}))['preview'],True)['skill_id']
    script_id=manager.resource_id(key,'scripts/main.py');args={'skill_id':key,'script':script_id,'topic':'interview concise','gmail_query':'pickup'}
    with pytest.raises(Denied):g.call(a['token'],'run_local_skill',args)
    g.set_capabilities(a['id'],skill_execution=True)
    os.environ['FAKE_PARENT_SECRET']='CREDENTIAL_CANARY'
    try:r=g.call(a['token'],'run_local_skill',args)
    finally:os.environ.pop('FAKE_PARENT_SECRET',None)
    assert r['status']=='completed',r
    owner=Artifacts(g);files=owner.list()['items'][0]['files'];idx=next(f['index'] for f in files if f['name']=='checks.json')
    checks=json.loads(base64.b64decode(owner.read(r['artifact'],idx)['content']));assert all(checks.values()),checks
    assert 'SElEREVOX1BBU1NQT1JUX0NBTkFSWQ==' not in json.dumps(r)
    assert 'checks.json' not in json.dumps(r) and 'CREDENTIAL_CANARY' not in json.dumps(r)
    assert not Path(str(outside)+'-write').exists()

@pytest.mark.skipif(sys.platform!='darwin',reason='Mac execution boundary')
def test_execution_timeout():
    pkg=parse_package(package('while True: pass'))
    assert execute(pkg,'scripts/main.py',{},timeout=.2)['status']=='timed_out'

def test_reviewed_connection_cannot_use_expanded_tools(bundle):
    g,s,now,views,make=bundle;a=make()
    for tool,args in [('context_status',{}),('list_local_skills',{'query':''}),('prepare_private_brief',{'topic':'x','gmail_query':'','max_messages':0})]:
        with pytest.raises(Denied):g.call(a['token'],tool,args)

def test_offline_dependency_hash_and_hooks():
    wheel=archive({'demo_dependency/__init__.py':'VALUE="works"','demo_dependency-1.0.dist-info/METADATA':'Name: demo-dependency\nVersion: 1.0'})
    name='vendor/demo_dependency-1.0-py3-none-any.whl'
    config={'dependencies':[{'file':name,'sha256':hashlib.sha256(wheel).hexdigest()}]}
    pkg=parse_package(package(extras={name:wheel,'airlock.json':json.dumps(config)}));assert pkg['dependencies']==[name]
    config['dependencies'][0]['sha256']='0'*64
    with pytest.raises(Denied,match='hash-verified'):parse_package(package(extras={name:wheel,'airlock.json':json.dumps(config)}))
    wheel=archive({'startup.pth':'import os'})
    config['dependencies'][0]['sha256']=hashlib.sha256(wheel).hexdigest()
    with pytest.raises(Denied,match='install hooks'):parse_package(package(extras={name:wheel,'airlock.json':json.dumps(config)}))

@pytest.mark.skipif(sys.platform!='darwin',reason='Mac execution boundary')
def test_bundled_dependency_and_symlink_output():
    wheel=archive({'demo_dependency/__init__.py':'VALUE="works"'});name='vendor/demo_dependency-1.0-py3-none-any.whl'
    script='''import os
from pathlib import Path
from demo_dependency import VALUE
out=Path(os.environ['AIRLOCK_OUTPUT'])
(out/'result.txt').write_text(VALUE)
(out/'input-link').symlink_to(os.environ['AIRLOCK_INPUT'])
(out/'folder-link').symlink_to(Path(os.environ['AIRLOCK_INPUT']).parent,target_is_directory=True)
'''
    pkg=parse_package(package(script,{name:wheel,'airlock.json':json.dumps({'dependencies':[{'file':name,'sha256':hashlib.sha256(wheel).hexdigest()}]})}))
    r=execute(pkg,'scripts/main.py',{'local':'INPUT_CANARY'})
    assert r['status']=='completed'
    assert [f['name'] for f in r['files']]==['result.txt']
    assert base64.b64decode(r['files'][0]['content'])==b'works'

def test_changed_capability_blocks_shared_write_and_run(bundle,monkeypatch):
    g,s,a,grant=setup(bundle);g.set_capabilities(a['id'],skill_execution=True,context_updates=True)
    with g.store.transaction() as d:grant=dict(d['grants'][a['id']])
    g.set_capabilities(a['id'],skill_execution=False,context_updates=False)
    with pytest.raises(Denied):SharedContext(g,grant).change('add','memories','Fictional shared note','',0)
    manager=SkillPackages(g,grant);key=manager.install(manager.preview(package())['preview'],True)['skill_id']
    with pytest.raises(Denied):Actions(g,grant).run(key,manager.resource_id(key,'scripts/main.py'),'interview','')

def test_owner_only_artifact_download_route(bundle):
    from starlette.testclient import TestClient
    from privacy_layer.server import owner_app
    g,s,a,grant=setup(bundle);key=Artifacts(g).save([{'name':'private.txt','content':base64.b64encode(b'LOCAL_ONLY_CANARY').decode()}],'completed',grant)
    with TestClient(owner_app(g,'test-owner'),base_url='http://127.0.0.1:8791') as c:
        assert c.post('/api/artifact-read',json={'reference':key,'index':0},headers={'Authorization':'Bearer '+a['token']}).status_code==401
        r=c.post('/api/artifact-read',json={'reference':key,'index':0},headers={'Authorization':'Bearer test-owner'});assert base64.b64decode(r.json()['content'])==b'LOCAL_ONLY_CANARY'
    with pytest.raises(Denied):g.call(a['token'],'artifact-read',{'reference':key,'index':0})

def test_private_phrase_change_during_action_blocks_outbound_result(bundle,monkeypatch):
    from starlette.testclient import TestClient
    from privacy_layer.server import owner_app
    from privacy_layer import actions,runner
    g,s,a,grant=setup(bundle);g.set_capabilities(a['id'],skill_execution=True)
    manager=SkillPackages(g,grant);key=manager.install(manager.preview(package())['preview'],True)['skill_id']
    def owner_changes_policy(*args,**kwargs):
        with TestClient(owner_app(g,'owner'),base_url='http://127.0.0.1:8791') as c:
            assert c.post('/api/private-phrases',json={'phrases':['Hyderabad']},headers={'Authorization':'Bearer owner'}).status_code==200
        return {'status':'completed','files':[]}
    monkeypatch.setattr(runner,'execute',owner_changes_policy)
    with pytest.raises(Denied,match='Sharing rules changed'):
        g.call(a['token'],'run_local_skill',{'skill_id':key,'script':manager.resource_id(key,'scripts/main.py'),'topic':'interview','gmail_query':'pickup'})
    with g.store.transaction() as d:assert not any(e['tool']=='run_local_skill' and e['status']=='released' for e in d['audit'])

def test_brief_ranks_message_body_not_just_date(bundle):
    g,s,a,grant=setup(bundle)
    s.data['gmail','e2']={'text':'Summer sale and garden furniture offers.','title':'Weekly update','date':'Wed, 11 Nov 2026 09:00:00 -0500'}
    s.search_gmail_page=lambda q,cursor=None:{'items':[{'kind':'gmail','source_id':i,**s.read('gmail',i)} for i in ('e2','e1')],'next_cursor':None}
    r=g.call(a['token'],'prepare_private_brief',{'topic':'interview','gmail_query':'pickup','max_messages':1})
    email=[x for x in r['items'] if x['kind']=='gmail'];assert len(email)==1 and 'ready for pickup' in email[0]['text']

def test_portable_installer_copies_skills_and_checks_yaml():
    root=Path(__file__).resolve().parents[1]
    bootstrap=(root/'macos/bootstrap.sh').read_text()
    assert '/usr/bin/ditto "$payload/builtin" "$app/builtin"' in bootstrap
    assert 'import mcp,cryptography,yaml' in bootstrap
