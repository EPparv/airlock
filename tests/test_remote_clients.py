import json
import os
import socket
import subprocess
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from privacy_layer import remote_clients, remote_tunnel
from privacy_layer.agent_memory import AgentMemory
from privacy_layer.core import Denied
from privacy_layer.remote_clients import BridgeApp, LoopbackListener, RemoteClients, public_origin


class FakeListener:
    thread = None
    port = None

    def ensure(self, port):
        self.port = port
        self.thread = self

    def is_alive(self):
        return True

    def verify_local(self, origin, cancel, check):
        pass

    def stop(self):
        self.thread = None


@pytest.fixture
def cloud(bundle):
    g = bundle[0]
    active = [g]
    remote = RemoteClients(g, FakeListener())
    remote.configure('https://bridge.example.net', 9874, True)
    server = BridgeApp(lambda: active[0], 9874)
    with TestClient(server, base_url='https://bridge.example.net') as client:
        yield g, active, remote, client


@pytest.mark.parametrize('value', ['http://unsafe.site', 'https://127.0.0.1', 'https://localhost',
                                   'https://bridge.local', 'https://name@my.site', 'https://my.site/?token=x',
                                   'https://my.site/path', 'https://a.net:xyz', 'https://abc.net#x',
                                   'https://abc.net:0', 'https://abc.net\\path', None])
def test_bridge_origin(value):
    with pytest.raises(Denied):
        public_origin(value)


def test_muse_rest_discovery_scopes_and_lifecycle(cloud):
    g, active, remote, client = cloud
    created = remote.create('muse', 3600, 10)
    headers = {'Authorization': 'Bearer ' + created['credential']}
    spec = client.get('/openapi.json').json()
    assert created['url'].endswith('/openapi.json') and spec['security'] == [{'agent': []}]
    assert '/v1/update_shared_context' in spec['paths'] and '/api/revoke' not in spec['paths']
    path = '/v1/get_private_context'
    assert client.post(path, json={'query': 'answer'}, headers=headers).status_code == 403
    AgentMemory(g).configure(created['id'], ['skills:s1'], disclose=True)
    result = client.post(path, json={'query': 'answer'}, headers=headers)
    assert 'Lead with the answer' in result.text and 'HIDDEN_FINANCE' not in result.text
    assert remote.state()['connections'][0]['last_call']
    assert created['credential'] not in json.dumps(remote.state())
    assert client.post(path + '?token=x', json={}, headers=headers).status_code == 403
    assert client.post(path, json={}, headers={**headers, 'origin': 'https://bridge.example.net'}).status_code == 403
    assert client.post(path, json={}, headers={**headers, 'Host': 'untrusted.test'}).status_code == 403
    assert client.post('/api/workspace-state', json={}, headers=headers).status_code == 404
    assert client.get('/workspace/personal', headers=headers).status_code == 404
    assert client.post(path, content=b'x' * 70000, headers={**headers, 'Content-Type': 'application/json'}).status_code == 413
    active[0] = None
    assert client.post(path, json={'query': 'x'}, headers=headers).status_code == 503
    active[0] = g
    with pytest.raises(Denied):
        remote.configure('https://new.example.net', 9874, True)
    remote.configure('', 9874, False)
    assert client.post(path, json={}, headers=headers).status_code == 503
    remote.configure('https://bridge.example.net', 9874, True)
    g.revoke(created['id'])
    assert client.post(path, json={'query': 'x'}, headers=headers).status_code == 401


def mcp_call(client, token, method='initialize', params=None):
    if params is None:
        params = {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'verification', 'version': '1'}}
    return client.post('/mcp', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'},
                       json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})


def test_manus_streamable_http_with_separate_scoped_credentials(cloud, bundle):
    g, active, remote, client = cloud
    manus = remote.create('manus', 60, 1)
    token = manus['credential']
    assert manus['url'] == 'https://bridge.example.net/mcp'
    assert mcp_call(client, token).json()['result']['serverInfo']['name'] == 'Airlock'
    result = mcp_call(client, token, 'tools/list', {}).json()['result']
    assert 'get_private_context' in [tool['name'] for tool in result['tools']]
    muse = remote.create('muse', 3600, 10)
    assert mcp_call(client, muse['credential']).status_code == 401
    assert mcp_call(client, bundle[-1]()['token']).status_code == 401
    assert client.post('/v1/privacy_status', json={}, headers={'authorization':'Bearer ' + token}).status_code == 401
    response = mcp_call(client, token, 'tools/call', {'name': 'privacy_status', 'arguments': {}})
    assert not response.json()['result']['isError']
    assert mcp_call(client, token).status_code == 401
    short = remote.create('muse', 60, 3)
    bundle[2][0] += 61
    assert client.post('/v1/privacy_status', json={}, headers={'authorization':'Bearer ' + short['credential']}).status_code == 401


def test_actual_loopback_and_resumption(bundle, monkeypatch):
    g = bundle[0]
    monkeypatch.setattr(remote_clients, '_get_active', lambda: g)
    with socket.socket() as temp:
        temp.bind(('127.0.0.1', 0))
        port = temp.getsockname()[1]
    listener = LoopbackListener()
    remote = RemoteClients(g, listener)
    try:
        remote.configure('https://proxy.example.net', port, True)
        grant = remote.create('muse', 60, 5)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
            response = client.post('/v1/privacy_status', headers={'Authorization':'Bearer ' + grant['credential']}, json={})
            assert response.status_code == 200
        with g.store.transaction() as state:
            assert state['remote_bridge']['enabled']
        listener.stop()
        restored = RemoteClients(g, listener)
        assert restored.state()['listening']
        restored.configure('', port, False)
        assert not restored.state()['enabled']
    finally:
        listener.stop()


def test_tunnel_export_contains_only_paths_and_uses_dedicated_profile(bundle, monkeypatch):
    g = bundle[0]
    remote = RemoteClients(g, FakeListener())
    created = remote.create('chatgpt', 60, 3)
    folder = g.store.path.parent
    token_file = folder / 'clients' / ('chatgpt-' + created['id'] + '.token')
    assert token_file.is_file() and token_file.stat().st_mode & 0o777 == 0o600
    assert token_file.read_text() not in created['command']
    assert remote.state()['connections'][0]['vendor'] == 'chatgpt'
    assert g.call(token_file.read_text(), 'privacy_status', {})['remaining_calls'] >= 0
    session = folder / 'launch.json'
    session.write_text('{}')
    calls = []
    def record(args, **kwargs):
        assert kwargs['env']['CONTROL_PLANE_API_KEY'] == 'sk-fictional-runtime-key'
        assert 'sk-fictional-runtime-key' not in str(args) and token_file.read_text() not in str(args)
        calls.append(args)
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(remote_tunnel.subprocess, 'run', record)
    assert remote_tunnel.run(token_file, session, 'tunnel_' + 'a' * 32, 'sk-fictional-runtime-key', 'tunnel-client') == 0
    assert [args[1] for args in calls] == ['init', 'doctor', 'run']
    assert all('airlock-' + created['id'] in args for args in calls)


@pytest.mark.parametrize('value', [
    None, 'tunnel_abc', 'tunnel_' + 'a' * 31, 'tunnel_' + 'a' * 33, 'tunnel_' + 'A' * 32,
    'tunnel_abc_' + 'a' * 32, 'tunnel_abcde_' + 'a' * 32, 'tunnel_AB12_' + 'a' * 32,
    'tunnel_ab12_' + 'a' * 31, 'tunnel_ab12_' + 'a' * 32 + '/', 'tunnel_ab12_' + 'a' * 32 + '\n',
])
def test_invalid_tunnel_id(value):
    assert not remote_tunnel.valid_tunnel_id(value)


@pytest.mark.parametrize('tunnel_id', ['tunnel_' + 'b' * 32, 'tunnel_ab12_' + 'b' * 32])
@pytest.mark.skipif(not os.environ.get('AIRLOCK_TEST_TUNNEL_CLIENT'), reason='official tunnel-client executable required')
def test_reopen_chatgpt_with_official_tunnel_client(tmp_path, monkeypatch, tunnel_id):
    binary = os.environ['AIRLOCK_TEST_TUNNEL_CLIENT']
    profile_id = 'a' * 32
    token = tmp_path/f'chatgpt-{profile_id}.token'
    token.write_text('synthetic-scoped-grant')
    session = tmp_path/'launch.json'
    session.write_text('{}')
    legacy = tmp_path/f'airlock-{profile_id}.yaml'
    legacy.write_text('owner configuration')
    monkeypatch.setenv('TUNNEL_CLIENT_PROFILE_DIR', str(tmp_path))
    monkeypatch.setenv('CONTROL_PLANE_BASE_URL', 'http://127.0.0.1:1')

    # Exercise the official init and doctor twice. Stop before any tunnel polling.
    official_run = subprocess.run
    prepared = []
    def offline_run(args, **kwargs):
        if args[1] != 'run':
            return official_run(args, **kwargs)
        directory = Path(args[args.index('--profile-dir')+1])
        contents = (directory/f'airlock-{profile_id}.yaml').read_text()
        assert directory.stat().st_mode & 0o777 == 0o700
        assert tunnel_id in contents and token.name in contents and 'env:CONTROL_PLANE_API_KEY' in contents
        assert 'sk-offline-test' not in contents
        prepared.append(directory)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(remote_tunnel.subprocess, 'run', offline_run)
    for _ in range(2):
        assert remote_tunnel.run(token, session, tunnel_id, 'sk-offline-test', binary) == 0
    assert len(set(prepared)) == 2 and not any(directory.exists() for directory in prepared)
    assert legacy.read_text() == 'owner configuration'


def test_muse_handoffs_and_ironclaw_manifest(cloud):
    from privacy_layer.agent_handoffs import Handoffs
    from privacy_layer.workspace import Workspace

    g, active, remote, client = cloud
    muse = remote.create('muse', 60, 20)
    iron = remote.create('ironclaw', 60, 20)
    assert 'https://bridge.example.net/mcp' in iron['manifest'] and '.invalid' not in iron['manifest']
    assert iron['credential'] not in iron['manifest']
    assert mcp_call(client, iron['credential']).status_code == 200
    from privacy_layer.device_apps import NativeApps
    g.device_apps = NativeApps()
    state = Workspace(g).state()
    assert {a['display_name'] for a in state['agents']} == {'Meta Muse', 'IronClaw'}
    spec = client.get('/openapi.json').json()['paths']
    assert {name for name in spec if 'handoff' in name} == {
        '/v1/list_agent_handoffs', '/v1/claim_agent_handoff', '/v1/read_agent_handoff', '/v1/submit_agent_handoff'}
    required = spec['/v1/submit_agent_handoff']['post']['requestBody']['content']['application/json']['schema']['required']
    assert required == ['reference', 'result']
    handoffs = Handoffs(g)
    people = handoffs.owner('handoff-state', {})['agents']
    assert {a['name'] for a in people} == {'Meta Muse', 'IronClaw'}
    args = {'worker': muse['id'], 'recipient': iron['id'], 'instruction': 'Prepare a short checklist'}
    review = handoffs.owner('handoff-check-assignment', args)
    handoffs.owner('handoff-assign', {**args, 'approval':review['approval'], 'approved':True})
    headers = {'Authorization': 'Bearer ' + muse['credential']}
    listed = client.post('/v1/list_agent_handoffs', json={}, headers=headers).json()
    handle = listed['handoffs'][0]['reference']
    assert client.post('/v1/claim_agent_handoff', json={'reference': handle}, headers=headers).status_code == 200
    submitted = client.post('/v1/submit_agent_handoff', json={'reference': handle, 'result':'Checklist ready'}, headers=headers)
    assert submitted.status_code == 200


def test_readonly_public_schema_import_from_a_browser(cloud):
    _, _, remote, client = cloud
    before = remote.state()
    headers = {'Origin':'https://importer.example.org'}
    get = client.get('/openapi.json', headers=headers)
    assert get.status_code == 200 and get.json()['servers'] == [{'url':'https://bridge.example.net'}]
    head = client.head('/openapi.json', headers=headers)
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == get.headers['content-length']
    assert head.headers['content-type'] == get.headers['content-type']
    for method in ('GET','HEAD'):
        preflight = client.options('/openapi.json',headers={**headers,
            'Access-Control-Request-Method':method,'Access-Control-Request-Headers':'Accept, Content-Type'})
        assert preflight.status_code == 204 and not preflight.content
        assert set(preflight.headers['access-control-allow-methods'].split(', ')) == {'GET','HEAD'}
        assert 'authorization' not in preflight.headers.get('access-control-allow-headers','').lower()
        for reply in (get,head,preflight):
            assert reply.headers['access-control-allow-origin'] == '*'
            assert 'access-control-allow-credentials' not in reply.headers
    assert remote.state() == before


def test_schema_import_never_grants_credentialed_or_private_cors(cloud):
    _, _, _, client = cloud
    browser = {'Origin':'https://importer.example.org'}
    def rejected(method, path, headers):
        response = client.request(method,path,headers={**browser,**headers})
        assert response.status_code >= 400
        assert not any(key.startswith('access-control-allow') for key in response.headers)
    for fields in ({'Authorization':'Bearer sample'}, {'Cookie':'session=sample'}, {'Host':'127.0.0.1:9874'},
                   {'Host':'elsewhere.example.net'}):
        rejected('HEAD','/openapi.json',fields)
    for requested in ('Authorization','Cookie','X-API-Key'):
        rejected('OPTIONS','/openapi.json',{'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':requested})
    rejected('OPTIONS','/openapi.json',{'Access-Control-Request-Method':'POST'})
    rejected('OPTIONS','/openapi.json',{'Access-Control-Request-Method':'GET','Access-Control-Request-Private-Network':'true'})
    for path in ('/openapi.json?cache=no','/mcp','/v1/privacy_status','/api/workspace-state','/phone/pair'):
        rejected('GET',path,{})
        rejected('OPTIONS',path,{'Access-Control-Request-Method':'GET'})
    local = client.get('/openapi.json', headers={'Host':'127.0.0.1:9874'})
    assert local.status_code == 200 and 'access-control-allow-origin' not in local.headers
