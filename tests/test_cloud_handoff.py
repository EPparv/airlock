from pathlib import Path
from unittest.mock import Mock

import pytest

from privacy_layer import remote_clients
from privacy_layer.core import Denied
from privacy_layer.remote_clients import MUSE_SETUP_REQUEST, STATUS_REQUEST, RemoteClients, open_provider
from test_remote_clients import FakeListener


def test_reconnect_requires_owner_and_keeps_existing_access(bundle, monkeypatch):
    gateway = bundle[0]
    remote = RemoteClients(gateway, FakeListener())
    opener = Mock(return_value={'opened':True})
    monkeypatch.setattr(remote_clients, 'open_provider', opener)
    assert remote.connect('manus', True) == {'state':'bridge'}
    opener.assert_not_called()
    with pytest.raises(Denied):
        remote.connect('manus', False)
    remote.configure('https://bridge.example.net', 9874, True)
    first = remote.connect('manus', True)
    assert first['setup'] and first['credential']
    assert first['previous'] == dict(last_initialized=None,last_discovery=None,last_call=None,last_context_read=None)
    opener.assert_called_once_with('manus', True)
    with gateway.store.transaction() as data:
        grant = data['grants'][first['id']]
        original = grant.copy()
    again = remote.connect('manus', True)
    assert again['id'] == first['id'] and again['setup'] and 'credential' not in again
    with gateway.store.transaction() as data:
        assert data['grants'][first['id']] == original
    with gateway.store.transaction() as data:
        data['grants'][first['id']]['last_initialized'] = gateway.clock()
    initialized = remote.connect('manus', True)
    assert initialized['previous']['last_initialized'] == gateway.clock() and not initialized['setup']
    gateway.authenticate(first['credential'], discovered=True)
    used = remote.connect('manus', True)
    assert not used['setup'] and used['previous']['last_discovery'] and not used['previous']['last_call']
    opener.assert_called_with('manus', False)
    second = remote.create('manus', 3600, 10)
    opener.reset_mock()
    assert remote.connect('manus', True) == {'state':'choose'}
    opener.assert_not_called()
    assert remote.connect('manus', True, second['id'])['id'] == second['id']
    with pytest.raises(Denied):
        remote.connect('muse', True, second['id'])


@pytest.mark.parametrize('vendor,setup,url,prompt', [
    ('muse', True, 'https://muse.ai/', MUSE_SETUP_REQUEST),
    ('chatgpt', True, 'https://chatgpt.com/plugins', None),
    ('chatgpt', False, 'https://chatgpt.com/', STATUS_REQUEST),
    ('manus', True, 'https://www.manus.im/app?openConnectors=true', None),
    ('manus', False, 'https://manus.im/app', STATUS_REQUEST),
    ('dot', False, 'https://chatgpt.com/dots', STATUS_REQUEST),
])
def test_macos_opens_fixed_provider_and_prepares_only_public_request(monkeypatch, vendor, setup, url, prompt):
    monkeypatch.setattr(remote_clients.sys, 'platform', 'darwin')
    run = Mock()
    monkeypatch.setattr(remote_clients.subprocess, 'run', run)
    result = open_provider(vendor, setup)
    assert result['opened'] and not result['drafted'] and result['prepared'] == bool(prompt)
    assert run.call_args_list[0].args == (['/usr/bin/open',url],)
    assert run.call_count == (2 if prompt else 1)
    if prompt:
        assert run.call_args_list[1].args == (['/usr/bin/pbcopy'],)
        assert run.call_args_list[1].kwargs['input'].decode() == prompt == result['request']


def test_opener_never_treats_user_input_as_a_destination(monkeypatch):
    monkeypatch.setattr(remote_clients.sys, 'platform', 'darwin')
    run = Mock(side_effect=OSError('unavailable'))
    monkeypatch.setattr(remote_clients.subprocess, 'run', run)
    for vendor in ['https://other.example.net/', None, ['muse']]:
        with pytest.raises(Denied):
            open_provider(vendor)
    assert not open_provider('custom')['opened']
    run.assert_not_called()
    result = open_provider('muse')
    assert not result['opened'] and not result['prepared'] and result['retry_native']


def test_native_tunnel_setup_is_only_for_an_active_dedicated_grant(bundle, monkeypatch):
    gateway = bundle[0]
    remote = RemoteClients(gateway, FakeListener())
    created = remote.create('chatgpt', 3600, 10)
    monkeypatch.setattr(remote_clients.sys, 'platform', 'darwin')
    run = Mock()
    monkeypatch.setattr(remote_clients.subprocess, 'run', run)
    result = remote.open_tunnel_setup(created['id'])
    assert result == {'opened':True}
    command = run.call_args.args[0]
    assert command[:3] == ['/usr/bin/open','-a','Terminal']
    path = Path(command[3])
    script = path.read_text()
    assert path.suffix == '.command' and path.stat().st_mode & 0o777 == 0o700
    assert created['command'] in script
    token = (path.parent / ('chatgpt-' + created['id'] + '.token')).read_text()
    assert token not in script
    run.reset_mock()
    gateway.revoke(created['id'])
    for id in (created['id'], '../../other', None):
        with pytest.raises(Denied):
            remote.open_tunnel_setup(id)
    run.assert_not_called()


def test_first_dot_connection_issues_own_zero_scope_and_uses_current_port(bundle, monkeypatch):
    import json
    from types import SimpleNamespace
    from privacy_layer import setup
    gateway = bundle[0]
    root = gateway.store.path.parent
    monkeypatch.setattr(setup, 'ROOT', root)
    monkeypatch.setattr(setup, 'tunnel_binary', lambda _: '/usr/local/bin/tunnel-client')
    monkeypatch.setattr(remote_clients, 'open_provider', lambda vendor: {'opened':True})
    (root / 'launch.json').write_text(json.dumps({'mcp_url':'http://127.0.0.1:34909/mcp'}))
    calls = []
    def process(args, **options):
        calls.append((args, options))
        state = {'nested':{'process_running':True, 'healthy':True, 'ready':True}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(state), stderr='')
    monkeypatch.setattr(setup.subprocess, 'run', process)
    remote = RemoteClients(gateway, FakeListener())
    request = dict(approved=True, tunnel_id='tunnel_ab12_' + 'c' * 32, runtime_key='sk-only-for-this-test')
    first = remote.owner('remote-connect-dot', request)
    assert first['opened'] and not any(k in first for k in ('credential','token','runtime_key'))
    args, options = calls[0]
    assert args[args.index('--tunnel-id')+1] == request['tunnel_id']
    assert args[args.index('--mcp-server-url')+1] == 'http://127.0.0.1:34909/mcp'
    token = (root/'dot.token').read_text()
    assert token not in str(args) and request['runtime_key'] not in str(args)
    assert options['env']['PRIVATE_AI_AGENT_AUTH'] == 'Bearer ' + token
    with gateway.store.transaction() as data:
        original = data['grants'][first['id']].copy()
        assert original['scope']['records'] == [] and not original['scope']['disclose']
    again = remote.owner('remote-connect-dot', request)
    assert again['id'] == first['id'] and (root/'dot.token').read_text() == token
    with gateway.store.transaction() as data:
        assert data['grants'][first['id']]['remaining'] == original['remaining']
        assert data['grants'][first['id']]['expires'] == original['expires']
    # A failed credential update preserves the working key and active grant.
    def rate_limited(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='', stderr='HTTP 429 from tunnel-service [private detail]')
    monkeypatch.setattr(setup.subprocess, 'run', rate_limited)
    with pytest.raises(Denied, match='429') as error:
        remote.owner('remote-connect-dot', {**request,'runtime_key':'sk-invalid-key-update'})
    assert 'private detail' not in str(error.value)
    with gateway.store.transaction() as data:
        assert data['dot_tunnel']['runtime_key'] == request['runtime_key']
        assert len(data['grants']) == 1 and not data['grants'][first['id']]['revoked']


def test_dot_setup_retries_after_missing_client_unopened_session_and_failed_provider(bundle, monkeypatch):
    from types import SimpleNamespace
    from privacy_layer import setup
    gateway = bundle[0]
    remote = RemoteClients(gateway, FakeListener())
    root = gateway.store.path.parent
    monkeypatch.setattr(setup, 'ROOT', root)
    monkeypatch.setattr(setup, 'tunnel_binary', lambda _:None)
    never = Mock()
    tunnel_id = 'tunnel_' + 'a' * 32
    monkeypatch.setattr(remote_clients, 'open_provider', never)
    with pytest.raises(Denied, match='Install'):
        remote.connect_dot(tunnel_id, 'sk-test-key', True)
    assert not gateway.list_grants()
    monkeypatch.setattr(setup, 'tunnel_binary', lambda _:'/usr/local/bin/tunnel-client')
    with pytest.raises(Denied, match='Open your Airlock workspace'):
        remote.connect_dot(tunnel_id, 'sk-test-key', True)
    (root/'launch.json').write_text('{"mcp_url":"http://127.0.0.1:34001/mcp"}')
    monkeypatch.setattr(setup.subprocess, 'run', lambda *a, **kw:SimpleNamespace(returncode=1, stdout='HTTP 403',stderr='secret text'))
    with pytest.raises(Denied, match='restricted runtime key') as err:
        remote.connect_dot(tunnel_id, 'sk-test-key', True)
    assert 'secret text' not in str(err.value) and not (root/'dot.token').exists()
    assert all(g['revoked'] for g in gateway.list_grants())
    assert not setup.saved_dot_available(gateway)
    never.assert_not_called()


def test_chatgpt_observes_tunnel_lifetime_and_does_not_duplicate_a_running_terminal(bundle, monkeypatch):
    import fcntl
    from privacy_layer.remote_tunnel import local_status, write_phase
    gateway = bundle[0]
    remote = RemoteClients(gateway, FakeListener())
    grant = remote.create('chatgpt', 120, 3)
    path = gateway.store.path.parent / 'clients' / ('chatgpt-' + grant['id'] + '.token')
    assert local_status(path)['phase'] == 'unknown'
    with path.with_suffix('.tunnel-state').open('w') as state:
        fcntl.flock(state, fcntl.LOCK_EX)
        write_phase(state, 'running')
        assert local_status(path)['active']
        monkeypatch.setattr(remote_clients.sys, 'platform', 'darwin')
        monkeypatch.setattr(remote_clients.subprocess, 'run', lambda *_a, **_kw:pytest.fail('An active tunnel started twice'))
        assert remote.open_tunnel_setup(grant['id'])['already_open']
    assert local_status(path)['phase'] == 'stopped'
    path.with_suffix('.tunnel-state').write_text('rate')
    assert not local_status(path)['active'] and '429' in local_status(path)['message']


def test_tunnel_doctor_reports_rate_limit_without_secret_or_retry(bundle, monkeypatch):
    from types import SimpleNamespace
    from privacy_layer import remote_tunnel
    remote = RemoteClients(bundle[0], FakeListener())
    grant = remote.create('chatgpt', 120, 3)
    folder = bundle[0].store.path.parent
    token = folder / 'clients' / ('chatgpt-' + grant['id'] + '.token')
    session = folder/'launch.json'
    session.write_text('{}')
    process = Mock(side_effect=[SimpleNamespace(returncode=0),SimpleNamespace(returncode=1,stdout=b'',stderr=b'HTTP 429 [private diagnostic]')])
    monkeypatch.setattr(remote_tunnel.subprocess, 'run', process)
    phases = []
    with pytest.raises(ValueError, match='429') as error:
        remote_tunnel.run(token,session,'tunnel_' + 'a' * 32,'sk-test-key','tunnel-client',phases.append)
    assert phases == ['checking','rate'] and process.call_count == 2
    assert 'private diagnostic' not in str(error.value) and 'sk-test-key' not in str(error.value)


def test_ironclaw_opens_only_an_explicit_owner_host(bundle, monkeypatch):
    remote = RemoteClients(bundle[0], FakeListener())
    monkeypatch.setattr(remote_clients.sys, 'platform', 'darwin')
    runner = Mock()
    monkeypatch.setattr(remote_clients.subprocess, 'run', runner)
    assert remote.open_client('ironclaw', True)['choose_host']
    runner.assert_not_called()
    for bad in ('https://agent.near.ai/', 'https://test.agents.near.ai', 'https://key@host.example',
                'https://host.example/?token=secret', 'http://remote.example', 'https://host.example/path', 'file:///tmp'):
        with pytest.raises(Denied):
            remote.open_ironclaw(bad, True)
    runner.assert_not_called()
    setup = remote.open_ironclaw('https://mine.example.org/', True)
    assert setup['url'] == 'https://mine.example.org/extensions/registry' and setup['opened']
    returning = remote.open_client('ironclaw', False)
    assert returning['url'] == 'https://mine.example.org/' and returning['request'] == STATUS_REQUEST
    assert remote.open_ironclaw('http://127.0.0.1:3000', True)['url'] == 'http://127.0.0.1:3000/extensions/registry'
