"""Safe startup, real gateway checks and a hard boundary to personal sources."""
import json
from pathlib import Path
import tomllib

import pytest
from starlette.testclient import TestClient

from privacy_layer import clients, sources
from privacy_layer.core import Denied
from privacy_layer.safe_test import SafeTest, GatewayRouter, PRIVATE, REHEARSAL

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def safe(tmp_path,monkeypatch):
    home=tmp_path/'profile';home.mkdir()
    (home/'.private-ai').mkdir();(home/'.private-ai/vault.enc').write_bytes(b'PERSONAL_VAULT_CANARY')
    (home/'CLAUDE.md').write_text('PERSONAL_FILE_CANARY')
    app=tmp_path/'app';app.mkdir();monkeypatch.setattr(clients,'ROOT',app)
    def forbidden(*a,**kw):raise AssertionError('Personal sources were initialized')
    monkeypatch.setattr(sources,'LocalSources',forbidden)
    return SafeTest(ROOT,app/'.private',profile_home=home)

def test_all_guided_checks_use_real_gateway_without_personal_sources(safe):
    for step in ('recall','privacy','correction','propose','approve','persistence','revoke'):
        assert safe.check(step)['passed'],step
    state=safe.status()
    assert len(state['checks'])==7 and state['isolated'] and not state['personal_open']
    assert 'PERSONAL_' not in json.dumps(state)
    assert PRIVATE not in json.dumps(state['receipts'])
    assert REHEARSAL in json.dumps(state['checks']['approve']['response'])
    assert (Path(safe.profile_home)/'.private-ai/vault.enc').read_bytes()==b'PERSONAL_VAULT_CANARY'
    assert (Path(safe.profile_home)/'CLAUDE.md').read_text()=='PERSONAL_FILE_CANARY'
    assert not (safe.state/'connections.enc').exists()
    assert not (safe.state/'key.lock').exists()
    raw=safe.g.store.path.read_bytes()
    assert b'Cypress' not in raw and b'ORCHID' not in raw
    assert safe.g.store.path.stat().st_mode&0o777==0o600
    assert (safe.folder/'fictional.key').stat().st_mode&0o777==0o600

def test_restart_and_reset_never_open_personal_access(safe):
    old=safe.metadata()['local']['token'];safe.check('correction')
    restarted=SafeTest(ROOT,safe.state,profile_home=safe.profile_home)
    assert restarted.personal is None
    assert restarted.status()['checks']['correction']['passed']
    assert 'November 27' in str(restarted.read())
    restarted.reset()
    with pytest.raises(Denied):GatewayRouter(restarted).call(old,'get_private_context',{'query':'Cypress'})
    assert 'November 20' in str(restarted.read())
    assert not restarted.status()['checks']

@pytest.mark.parametrize('action,body',[
    ('context-preview',{'name':'private.txt','content':'PERSONAL_CANARY'}),
    ('context-source',{'source':'claude','enabled':True}),('gmail-connect',{}),
    ('create',{}),('client-connect',{'agent':'codex','approved':True}),
    ('open-personal',{'approved':False}),('open-personal',{'approved':'true'}),
    ('test-reset',{'approved':False}),('test-connect',{'agent':'codex','approved':False}),
    ('test-connect',{'agent':'dot','approved':True}),
])
def test_safe_owner_api_rejects_personal_actions_and_implicit_consent(safe,action,body):
    with TestClient(safe.app('test-owner',8791),base_url='http://127.0.0.1:8791') as c:
        r=c.post('/api/'+action,json=body,headers={'Authorization':'Bearer test-owner'})
        assert r.status_code==400
    assert safe.personal is None and not (safe.state/'connections.enc').exists()

def test_owner_auth_origin_and_asset_boundary(safe):
    with TestClient(safe.app('test-owner',8791),base_url='http://127.0.0.1:8791') as c:
        for asset in ('/','/safe-test.js','/safe-test.css','/icon.svg'):
            r=c.get(asset);assert r.status_code==200
            assert 'no-store' in r.headers['cache-control']
            assert "frame-ancestors 'none'" in r.headers['content-security-policy']
        assert c.get('/personal').status_code==404
        assert c.get('/ui.js').status_code==404
        assert c.post('/api/test-state',json={}).status_code==401
        h={'Authorization':'Bearer test-owner'}
        assert c.post('/api/test-state',json={},headers={**h,'Origin':'https://evil.example'}).status_code==403
        assert c.post('/api/test-state',json={},headers={**h,'Host':'evil.example'}).status_code==403
        assert c.post('/api/test-state',content=b'x'*4097,headers=h).status_code==413
        r=c.post('/api/test-state',json={},headers=h)
        assert r.status_code==200 and 'token' not in r.text

def test_test_gateway_has_no_nonfictional_import_write_or_inference_path(safe):
    router=GatewayRouter(safe);token=safe.metadata()['local']['token']
    for tool in ('search_gmail','stage_context_import','run_local_skill','request_private_task','get_private_task_result'):
        with pytest.raises(Denied):router.call(token,tool,{})
    for value in ('Remember my private life.',REHEARSAL+'\nPERSONAL_CANARY'):
        with pytest.raises(Denied):router.call(token,'update_shared_context',dict(operation='add',kind='memories',text=value,reference='',expected_revision=0))
    router.call(token,'update_shared_context',dict(operation='add',kind='memories',text=REHEARSAL,reference='',expected_revision=0))
    assert REHEARSAL not in str(safe.read())
    assert safe.status()['pending'][0]['text']==REHEARSAL
    assert safe.check('approve')['passed']

@pytest.mark.parametrize('agent',['codex','claude-desktop','claude-code','cursor'])
def test_test_connection_preserves_real_and_unrelated_config(safe,agent):
    real=clients.server_entry(safe.state/'existing-personal.token')
    clients.install_config(agent,real,home=safe.profile_home)
    result=safe.connect(agent,True)
    path=Path(safe.profile_home)/clients.RELATIVE_CONFIGS[agent]
    parsed=tomllib.loads(path.read_text()) if agent=='codex' else json.loads(path.read_text())
    servers=parsed['mcp_servers' if agent=='codex' else 'mcpServers']
    assert servers['airlock']==real and 'airlock-test' in servers
    token=next((safe.folder/'clients').glob('*.token')).read_text()
    assert token not in json.dumps(result) and token not in path.read_text()
    r=GatewayRouter(safe).call(token,'get_private_context',{'query':'Cypress '+PRIVATE})
    assert PRIVATE not in json.dumps(r) and 'Cypress' in str(r)
    assert safe.status()['live'][0]['last_context_read']
    safe.g.revoke(result['id'])
    with pytest.raises(Denied):GatewayRouter(safe).call(token,'get_private_context',{'query':'Cypress'})

def test_invalid_client_config_stays_unchanged_and_new_grant_is_revoked(safe):
    path=Path(safe.profile_home)/'.codex/config.toml';path.parent.mkdir();path.write_text('invalid ! TOML')
    with pytest.raises(Denied):safe.connect('codex',True)
    assert path.read_text()=='invalid ! TOML'
    assert not list((safe.folder/'clients').glob('*.token'))
    assert not safe.status()['live']
    assert [g for g in safe.g.list_grants() if g['agent']=='codex'][0]['revoked']

def test_personal_workspace_requires_separate_owner_token_and_closes(safe,monkeypatch):
    calls=[]
    class PersonalSources:
        key=b'p'*32
        context_home=safe.profile_home
        def __init__(self,**kw):calls.append(kw)
        def library(self):return [{'kind':'memories','source_id':'personal','text':'PERSONAL_ONLY','device_only':False}]
        def protected(self):return []
    monkeypatch.setattr(sources,'LocalSources',PersonalSources)
    app=safe.app('test-owner',8791)
    with TestClient(app,base_url='http://127.0.0.1:8791') as c:
        test={'Authorization':'Bearer test-owner'}
        r=c.post('/api/open-personal',json={'approved':True},headers=test)
        assert r.status_code==200 and len(calls)==1
        owner=r.json()['url'].split('#')[1];assert owner!='test-owner'
        personal={'Authorization':'Bearer '+owner}
        assert c.get('/personal').status_code==200
        assert c.post('/api/library',json={},headers=test).status_code==400
        assert 'PERSONAL_ONLY' in c.post('/api/library',json={},headers=personal).text
        grant=safe.personal.create(agent='test',purpose='test',views=[],mode='automatic',approved=True)
        router=GatewayRouter(safe)
        assert 'PERSONAL_ONLY' in str(router.call(grant['token'],'get_private_context',{'query':''}))
        assert 'PERSONAL_ONLY' not in str(router.call(safe.metadata()['local']['token'],'get_private_context',{'query':''}))
        c.post('/api/close-personal',json={},headers=test).raise_for_status()
        assert not safe.status()['personal_open']
        assert c.post('/api/library',json={},headers=personal).status_code==401
        with pytest.raises(Denied):router.call(grant['token'],'get_private_context',{'query':''})
        assert SafeTest(ROOT,safe.state,profile_home=safe.profile_home).personal is None

def test_new_personal_connection_is_closed_until_owner_selects_records(tmp_path,monkeypatch):
    from privacy_layer.sources import LocalSources
    from privacy_layer.core import Gateway,EncryptedStore
    from privacy_layer.server import owner_app
    from privacy_layer.context import ContextHub
    monkeypatch.setattr(clients,'ROOT',tmp_path)
    s=LocalSources(key=b'p'*32,context_home=tmp_path/'empty-profile')
    g=Gateway(EncryptedStore(tmp_path/'personal.enc',s.key),s);s.connection_store=g.store
    hub=ContextHub(g.store,home=s.context_home);p=hub.preview('fictional.md',b'# Memories\nFictional project begins November 21.')
    hub.commit(p['id'],[0],[])
    with TestClient(owner_app(g,'owner'),base_url='http://127.0.0.1:8791') as c:
        h={'Authorization':'Bearer owner'}
        r=c.post('/api/client-connect',json={'agent':'codex','approved':True,'install':False},headers=h)
        assert r.status_code==200,r.text
        grant=r.json();args=grant['args'];token=Path(args[args.index('--token-file')+1]).read_text()
        with pytest.raises(Denied):g.call(token,'get_private_context',{'query':'project'})
        state=c.post('/api/memory-state',json={},headers=h).json()
        assert state['connections'][0]['scope']=={'records':[],'disclose':False,'compute':False}
        refs=[r['ref'] for r in state['records']]
        r=c.post('/api/memory-scope',json={'identifier':grant['id'],'records':refs,'disclose':True,'compute':False,'proposals':True},headers=h)
        assert r.status_code==200,r.text
        assert 'November 21' in str(g.call(token,'get_private_context',{'query':'project'}))
        with pytest.raises(Denied):g.call(token,'search_gmail',{'query':'anything'})


def test_native_proposal_can_be_approved_after_simulated_revocation(safe):
    old=safe.metadata()['local']['token']
    for step in ('recall','privacy','correction','propose','approve','persistence','revoke'):
        assert safe.check(step)['passed']
    live=safe.grant('codex')
    safe.g.call(live['token'],'update_shared_context',dict(operation='add',kind='memories',text=REHEARSAL,reference='',expected_revision=0))
    assert safe.check('approve')['passed']
    with pytest.raises(Denied):safe.g.call(old,'get_private_context',{'query':'Cypress'})
    assert REHEARSAL in str(safe.g.call(live['token'],'get_private_context',{'query':'Cypress rehearsal'}))


def test_real_mcp_http_authentication_and_revocation(safe):
    from privacy_layer.server import mcp_app
    app,_=mcp_app(GatewayRouter(safe),8792)
    token=safe.metadata()['local']['token']
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
    with TestClient(app,base_url='http://127.0.0.1:8792') as c:
        init={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'safe-test','version':'1'}}}
        r=c.post('/mcp',json=init,headers=headers)
        assert r.status_code==200,r.text
        assert 'serverInfo' in r.json()['result']
        request={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_private_context','arguments':{'query':'Cypress'}}}
        r=c.post('/mcp',json=request,headers=headers)
        assert r.status_code==200 and not r.json()['result'].get('isError'),r.text
        assert 'November 20' in r.text and PRIVATE not in r.text
        request['params']={'name':'search_gmail','arguments':{'query':'anything'}}
        r=c.post('/mcp',json=request,headers=headers)
        assert r.json()['result']['isError']
        safe.g.revoke(safe.metadata()['local']['id'])
        assert c.post('/mcp',json=init,headers=headers).status_code==401
        assert c.post('/mcp',json=init,headers={**headers,'Authorization':'Bearer unknown'}).status_code==401
