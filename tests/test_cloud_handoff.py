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
    opener.assert_called_once_with('manus', True)
    with gateway.store.transaction() as data:
        grant = data['grants'][first['id']]
        original = grant.copy()
    again = remote.connect('manus', True)
    assert again['id'] == first['id'] and again['setup'] and 'credential' not in again
    with gateway.store.transaction() as data:
        assert data['grants'][first['id']] == original
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
    ('manus', True, 'https://manus.im/app', None),
    ('ironclaw', False, 'https://agent.near.ai/', STATUS_REQUEST),
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
