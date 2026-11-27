from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

from privacy_layer import clients, quick_connect
from privacy_layer.agent_memory import AgentMemory
from privacy_layer.core import Denied
from privacy_layer.device_apps import ExampleApps, NativeApps
from privacy_layer.quick_connect import QuickConnections
from privacy_layer.server import owner_app

CONNECT = 'workspace-quick-connect'
OPEN = 'workspace-open-client'
OPTIONS = 'workspace-launch-options'
CURSOR = {'agent':'cursor','approved':True}
LAUNCHED = {'opened':True,'drafted':True,'method':'draft','message':'Test request prepared.'}


@pytest.fixture
def owner(bundle, tmp_path, monkeypatch):
    from privacy_layer import agent_launch
    gateway, sources, now, *_ = bundle
    home = tmp_path/'profile'
    home.mkdir()
    sources.context_home = home
    gateway.device_apps = NativeApps()
    monkeypatch.setattr(quick_connect, 'launch_options', lambda: ['cursor','codex','dot','mcp'])
    monkeypatch.setattr(clients, 'ROOT', tmp_path/'app')
    launches = []
    def open_agent(agent):
        launches.append(agent)
        return dict(LAUNCHED)
    monkeypatch.setattr(agent_launch, 'open_agent', open_agent)
    return QuickConnections(gateway), gateway, now, launches


def test_owner_browser_connect_and_reconnect_preserve_scope_and_call_evidence(owner, monkeypatch):
    service, g, now, launches = owner
    original_library = g.sources.library
    monkeypatch.setattr(g.sources, 'library', lambda: pytest.fail('Empty grant read personal records'))
    with TestClient(owner_app(g,'owner',8791), base_url='http://127.0.0.1:8791') as client:
        def post(action, body, **extra):
            return client.post('/api/'+action,json=body,headers={'Authorization':'Bearer owner',**extra})
        assert post(OPTIONS,{}).json()['agents'] == ['cursor','codex','dot','mcp']
        assert post(CONNECT,CURSOR,Origin='https://other.example').status_code == 403
        assert post(CONNECT,CURSOR,Host='other.example').status_code == 403
        assert post(CONNECT,CURSOR,Authorization='Bearer agent-token').status_code == 401
        for invalid in ({**CURSOR,'approved':1}, {**CURSOR,'agent':'custom'},
                        {**CURSOR,'target':'https://other.example'}, {'agent':'cursor'}):
            assert post(CONNECT,invalid).status_code == 400
        assert not g.list_grants() and not launches
        result = post(CONNECT,CURSOR).json()
        assert result['opened'] and result['drafted'] and result['installed'] and not result['needsReview']
        assert all(value is None for value in result['previousStatus'].values())
        assert 'config' not in result and 'token' not in result
        grant = g.list_grants()[0]
        assert grant['scope'] == {'records':[],'disclose':False,'disclose_records':[],'compute':False}
        assert grant['remaining'] == 100 and grant['last_discovery'] is None and grant['last_call'] is None
        with g.store.transaction() as data:
            record = data['grants'][grant['id']]
            assert record['device_permissions'] == {'mail':False,'calendar':False}
            assert not any(record['capabilities'].values())
        monkeypatch.setattr(g.sources, 'library', original_library)
        AgentMemory(g).configure(grant['id'], ['skills:s1'], disclose=True)
        token = next((clients.ROOT/'.private/clients').glob('*.token')).read_text().strip()
        g.authenticate(token, discovered=True)
        g.call(token, 'privacy_status', {})
        previous = g.list_grants()[0]
        result = post(CONNECT,CURSOR).json()
        assert result['id'] == previous['id'] and result['previousStatus']['last_discovery'] == now[0]
        assert result['previousStatus']['last_call'] == now[0] and launches == ['cursor','cursor']
        assert g.list_grants() == [previous]
        assert post(OPEN,{**CURSOR,'id':result['id']}).json()['opened']
        assert post(OPEN,{**CURSOR,'agent':'codex','id':result['id']}).status_code == 400
        g.revoke(result['id'])
        assert post(OPEN,{**CURSOR,'id':result['id']}).status_code == 400
        assert len(launches) == 3


def test_missing_app_retry_uses_same_grant_and_manual_setup_is_preserved(owner, monkeypatch):
    from privacy_layer import agent_launch
    service, g, _, calls = owner
    with monkeypatch.context() as patch:
        patch.setattr(agent_launch, 'open_agent', lambda _: (_ for _ in ()).throw(OSError('not installed')))
        saved = service.owner(CONNECT, CURSOR)
    assert saved['installed'] and not saved['opened'] and saved['id']
    assert service.owner(CONNECT, CURSOR)['id'] == saved['id'] and calls == ['cursor']
    with g.store.transaction() as data:
        data['grants'][saved['id']]['client_setup']['installed'] = False
    assert service.owner(CONNECT, CURSOR)['needsReview'] and len(calls) == 1
    g.create(agent='cursor',purpose='Explicit second grant',views=[],approved=True,mode='automatic')
    review = service.owner(CONNECT,CURSOR)
    assert review['needsReview'] and review['id'] == '' and not review['opened'] and len(calls) == 1
    assert len(g.list_grants()) == 2


def test_quick_connect_declines_to_revive_expired_grant(owner):
    service, g, now, calls = owner
    old = service.owner(CONNECT, CURSOR)['id']
    now[0] += 86401
    with pytest.raises(Denied):
        service.owner(OPEN, {**CURSOR,'id':old})
    assert service.owner(CONNECT, CURSOR)['id'] != old
    assert len(calls) == 2


def test_opening_specific_grant_restores_its_own_current_registration(owner):
    import json
    from pathlib import Path
    service, g, _, calls = owner
    a = service.owner(CONNECT, CURSOR)['id']
    b = clients.connect(g, agent='cursor', approved=True, home=g.sources.context_home,
                        scope={'records':['skills:s1'], 'disclose':True})['id']
    path = clients.config_path('cursor', g.sources.context_home)
    def installed_id():
        entry = json.loads(path.read_text())['mcpServers']['airlock']
        return g.authenticate(Path(entry['args'][2]).read_text().strip())['id']
    assert installed_id() == b
    assert service.owner(OPEN, {**CURSOR, 'id':a})['opened']
    assert installed_id() == a
    path.unlink()
    assert service.owner(OPEN, {**CURSOR, 'id':b})['opened']
    assert installed_id() == b
    assert len(calls) == 3 and all(grant['last_discovery'] is None for grant in g.list_grants())


def test_two_workspace_instances_coordinate_new_grant(owner):
    first, g, _, _ = owner
    second = QuickConnections(g)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.owner,CONNECT,CURSOR) for client in (first,second)]
        results = [f.result(timeout=5) for f in futures]
    assert results[0]['id'] == results[1]['id'] and len(g.list_grants()) == 1


def test_owner_boundary_without_native_personal_workspace(owner):
    service, g, _, calls = owner
    g.device_apps = ExampleApps()
    assert service.owner(OPTIONS, {}) == {'agents':[]}
    with pytest.raises(Denied):
        service.owner(CONNECT,CURSOR)
    assert not calls and not g.list_grants()


def test_dot_missing_tunnel_does_not_issue_a_grant(owner):
    service, g, _, _ = owner
    r = service.owner(CONNECT,{'agent':'dot','approved':True})
    assert r['needsReview'] and r['method']=='setup' and not r['id'] and not g.list_grants()

def test_unnamed_mcp_reuses_manual_grant_without_opening_an_app(owner):
    service, g, _, calls = owner
    req = {'agent':'mcp','approved':True}
    first = service.owner(CONNECT,req)
    assert first['method']=='manual' and not first['opened'] and not first['needsReview']
    assert service.owner(CONNECT,req) == first
    assert service.owner(OPEN,{**req,'id':first['id']}) == first
    assert len(g.list_grants()) == 1 and not calls


def test_local_mcp_never_selects_cloud_connector_grants(owner):
    from privacy_layer.remote_clients import RemoteClients
    service, g, _, _ = owner
    cloud = RemoteClients(g).create('chatgpt', 3600, 8)['id']
    req = {'agent':'mcp','approved':True}
    local = service.owner(CONNECT,req)
    assert local['id'] != cloud and local['method'] == 'manual'
    assert service.owner(CONNECT,req)['id'] == local['id']
    with pytest.raises(Denied):
        service.owner(OPEN,{**req,'id':cloud})
    with pytest.raises(Denied):
        clients.manual_connection_details(g,cloud)


def test_overlapping_clicks_share_one_app_handoff(owner, monkeypatch):
    from concurrent.futures import Future
    from threading import Event
    from privacy_layer import agent_launch
    service, g, _, _ = owner
    opening, joined = Event(), Event()
    launches = []
    class SharedRequest(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout=5)
    def slow_open(agent):
        launches.append(agent)
        opening.set()
        assert joined.wait(timeout=5)
        return LAUNCHED
    monkeypatch.setattr(quick_connect, 'Future', SharedRequest)
    monkeypatch.setattr(agent_launch, 'open_agent', slow_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.owner,CONNECT,CURSOR)
        assert opening.wait(timeout=5)
        second = pool.submit(service.owner,CONNECT,CURSOR)
        assert first.result(timeout=5) == second.result(timeout=5)
    assert launches == ['cursor'] and len(g.list_grants()) == 1


def test_setup_help_requires_explicit_owner_action_and_creates_no_grant(owner, monkeypatch):
    from privacy_layer import agent_launch
    service, g, _, launches = owner
    helps = []
    def help_page(agent):
        helps.append(agent)
        return {'opened':True, 'message':'Opened setup instructions.'}
    monkeypatch.setattr(agent_launch, 'open_setup_help', help_page, raising=False)
    with pytest.raises(Denied):
        service.owner('workspace-agent-help',{**CURSOR,'url':'https://other.example'})
    with pytest.raises(Denied):
        service.owner('workspace-agent-help',{**CURSOR,'agent':'mcp'})
    assert service.owner('workspace-agent-help',CURSOR)['opened']
    assert helps == ['cursor'] and not launches and not g.list_grants()


def test_existing_dot_requires_the_matching_tunnel_credential(owner, tmp_path, monkeypatch):
    from privacy_layer import remote_clients, setup
    service, g, _, _ = owner
    req = {'agent':'dot', 'approved':True}
    grant = g.create(agent='dot', purpose='Saved Dot tunnel', views=[], approved=True, mode='automatic')
    AgentMemory(g).configure(grant['id'], records=[])
    with g.store.transaction() as d:
        d['dot_tunnel'] = {'id':'fixture','runtime_key':'example'}
        d['grants'][grant['id']]['client_setup'] = {'installed':True}
    monkeypatch.setattr(setup, 'ROOT', tmp_path/'app')
    token_file = setup.ROOT/'.private/dot.token'
    token_file.parent.mkdir(parents=True,exist_ok=True)
    token_file.write_text('invalid')
    opened = []
    monkeypatch.setattr(remote_clients, 'open_provider', lambda agent: opened.append(agent) or LAUNCHED)
    monkeypatch.setattr(setup, 'restore_dot', lambda _: None)
    assert service.owner(CONNECT,req)['method'] == 'review' and not opened
    token_file.write_text(grant['token'])
    assert service.owner(CONNECT,req)['id'] == grant['id'] and opened == ['dot']
    assert g.list_grants()[0]['last_call'] is None
