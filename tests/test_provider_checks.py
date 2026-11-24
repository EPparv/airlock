import json

from starlette.testclient import TestClient
import pytest

from privacy_layer.core import Denied
from privacy_layer.provider_checks import ProviderChecks, TTL
from privacy_layer.remote_clients import BridgeApp, RemoteClients
from privacy_layer.server import owner_app
from test_remote_clients import FakeListener, mcp_call


@pytest.mark.parametrize('vendor', ['muse', 'manus', 'ironclaw', 'custom'])
def test_owner_matches_live_code_only_for_the_intended_https_connection(bundle, vendor, monkeypatch):
    gateway, sources, clock, *_ = bundle
    remote = RemoteClients(gateway, FakeListener())
    remote.configure('https://demo.example.org', 9874, True)
    check = ProviderChecks(gateway, remote)
    created = remote.create(vendor, 3600, 2)
    other = remote.create(vendor, 3600, 2)
    cid = {'id': created['id']}
    assert check.owner('provider-check-start', cid)['local'] == 'Agent bridge listening'
    assert check.owner('provider-check-state', cid)['received'] is None
    with pytest.raises(Denied):
        check.owner('provider-check-confirm', {**cid, 'code':'BADCODE'})
    with pytest.raises(Denied):
        gateway.call(created['credential'], 'privacy_status', {})  # bypassing the configured route is insufficient
    for attr in ('read', 'library', 'protected'):
        monkeypatch.setattr(sources, attr, lambda *_: pytest.fail('Status check touched private data'))
    with TestClient(BridgeApp(lambda: gateway, 9874), base_url='https://demo.example.org') as web:
        if vendor == 'muse':
            response = web.post('/v1/privacy_status', json={}, headers={'Authorization':'Bearer '+created['credential']})
            result = response.json()
        else:
            assert mcp_call(web, created['credential']).status_code == 200
            assert check.owner('provider-check-state', cid)['received'] is None
            response = mcp_call(web, created['credential'], 'tools/call', {'name':'privacy_status', 'arguments':{}})
            result = json.loads(response.json()['result']['content'][0]['text'])
        assert response.status_code == 200
    assert set(result) == {'execution', 'connection_check'}
    code = result['connection_check']
    local = check.owner('provider-check-state', cid)
    assert local['received'] and not local['confirmed'] and code not in json.dumps(local)
    assert not check.owner('provider-check-state', {'id':other['id']})['received']
    with pytest.raises(Denied):
        check.owner('provider-check-confirm', {'id':other['id'], 'code':code})
    confirmed = check.owner('provider-check-confirm', {**cid, 'code':code.lower()})
    assert confirmed['confirmed'] == clock[0] and not confirmed['expires']
    with pytest.raises(Denied):
        check.owner('provider-check-confirm', {**cid, 'code':code})


def test_chatgpt_status_recovery_expiry_exhaustion_and_revocation(bundle):
    gateway, _, clock, _, create_local = bundle
    remote = RemoteClients(gateway, FakeListener())
    check = ProviderChecks(gateway, remote)
    with pytest.raises(Denied):
        check.owner('provider-check-start', {'id':create_local()['id']})
    created = remote.create('chatgpt', 3600, 2)
    cid = {'id':created['id']}
    token_file = gateway.store.path.parent / 'clients' / ('chatgpt-' + created['id'] + '.token')
    token = token_file.read_text()
    status = check.owner('provider-check-start', cid)
    assert status['local'] == 'Dedicated credential available'
    assert status['tunnel_command'] == created['command'] and token not in status['tunnel_command']
    code = gateway.call(token, 'privacy_status', {})['connection_check']
    assert check.owner('provider-check-start', cid)['received'] == clock[0]  # idempotent while pending
    clock[0] += TTL + 1
    with pytest.raises(Denied):
        check.owner('provider-check-confirm', {**cid, 'code':code})
    assert not check.owner('provider-check-state', cid)['received']
    check.owner('provider-check-start', cid)
    fresh = gateway.call(token, 'privacy_status', {})['connection_check']
    assert fresh != code
    assert not check.owner('provider-check-state', cid)['can_start']
    assert check.owner('provider-check-confirm', {**cid, 'code':fresh})['confirmed'] == clock[0]
    with pytest.raises(Denied):
        check.owner('provider-check-start', cid)
    created = remote.create('chatgpt', 60, 2)
    cid = {'id':created['id']}
    token_file = token_file.with_name('chatgpt-' + created['id'] + '.token')
    check.owner('provider-check-start', cid)
    code = gateway.call(token_file.read_text(), 'privacy_status', {})['connection_check']
    gateway.revoke(created['id'])
    with pytest.raises(Denied):
        check.owner('provider-check-confirm', {**cid,'code':code})


def test_owner_api_requires_owner_auth_and_preserves_budget(bundle):
    gateway = bundle[0]
    with TestClient(owner_app(gateway, 'example-owner'), base_url='http://127.0.0.1:8791') as web:
        headers = {'Authorization':'Bearer example-owner'}
        r = web.post('/api/remote-create',json={'vendor':'chatgpt','lifetime':3600,'max_calls':6},headers=headers)
        assert r.status_code == 200
        body = {'id':r.json()['id']}
        assert web.post('/api/provider-check-start',json=body).status_code == 401
        for name in ('start', 'state', 'cancel', 'state'):
            r = web.post('/api/provider-check-'+name,json=body,headers=headers)
            assert r.status_code == 200 and r.json()['remaining'] == 6
            assert not r.json()['received']
