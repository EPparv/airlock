import json
from pathlib import Path
import re
import subprocess
import sys
import threading

import pytest
from starlette.testclient import TestClient

from privacy_layer import quick_tunnel
from privacy_layer.core import Denied
from privacy_layer.remote_clients import BridgeApp, LinkCheck, RemoteClients
from test_remote_clients import FakeListener

ORIGIN = 'https://quiet-window-park.trycloudflare.com'


class Tunnel:
    def __init__(self, _):
        self.cancel = threading.Event()

    def start(self, port, on_exit):
        self.on_exit = on_exit
        return ORIGIN

    def stop(self):
        self.cancel.set()


def configured(gateway, verifier=lambda origin, cancel, check: True):
    return RemoteClients(gateway, FakeListener(), tunnel_factory=Tunnel, verify=verifier)


def test_only_owner_can_open_then_verified_url_is_bound_and_retired_on_lock(bundle):
    g = bundle[0]
    active = [g]
    server = BridgeApp(lambda: active[0], 8794)
    calls = []
    def verify(origin, cancel, check):
        with TestClient(server, base_url=origin) as c:
            assert c.get('/openapi.json').status_code == 404
            page = c.get(check.path, headers={'cf-ray':'deadbeef12345678-IAD'})
            assert check.output() in page.text
            assert c.get('/api/workspace-state').status_code == 404
            with pytest.raises(Denied):
                remote.create('muse', 60, 3)
        calls.append(origin)
        return True
    remote = configured(g, verify)
    with pytest.raises(Denied):
        remote.owner('remote-quick-start', {'approved':False})
    state = remote.owner('remote-quick-start', {'approved':True})
    assert state['mode'] == 'temporary' and state['enabled'] and state['verified']
    assert remote.start_temporary(True) == state and calls == [ORIGIN]
    grant = remote.create('muse', 60, 3)
    with TestClient(BridgeApp(lambda: active[0], 8794), base_url=ORIGIN) as c:
        assert c.post('/v1/privacy_status', headers={'Authorization':'Bearer '+grant['credential']}, json={}).status_code == 200
        remote.close()
        assert c.get('/openapi.json').status_code == 503
    with pytest.raises(Denied):
        g.authenticate(grant['credential'])
    with pytest.raises(Denied):
        remote.start_temporary(True)
    reopened = configured(g)
    assert not reopened.state()['enabled'] and not reopened.state()['listening']


def test_crashes_and_failed_reachability_close_the_link(bundle):
    g = bundle[0]
    def failed(*args): raise Denied('Unable to reach test link')
    remote = configured(g, failed)
    with pytest.raises(Denied, match='test link'):
        remote.start_temporary(True)
    assert not remote.state()['enabled'] and remote.tunnel is None
    remote = configured(g)
    remote.start_temporary(True)
    a = remote.create('manus', 60, 5)
    process = remote.tunnel
    process.on_exit(process)
    assert not remote.state()['enabled']
    with pytest.raises(Denied):
        g.authenticate(a['credential'])
    remote.start_temporary(True)
    b = remote.create('muse', 60, 5)
    # A fresh service after an unclean exit must invalidate even reusable local credentials.
    reopened = configured(g)
    assert not reopened.state()['enabled']
    with pytest.raises(Denied):
        g.authenticate(b['credential'])
    remote.stop_temporary()


def test_close_during_open_does_not_restore_link(bundle):
    g = bundle[0]
    verifying, stopped = threading.Event(), threading.Event()
    def verify(origin, cancel, check):
        verifying.set()
        assert cancel.wait(2)
    remote = configured(g, verify)
    def start():
        try: remote.start_temporary(True)
        except Denied: stopped.set()
    t = threading.Thread(target=start)
    t.start()
    assert verifying.wait(2)
    remote.close()
    t.join(2)
    assert stopped.is_set() and not remote.state()['enabled']


def test_respects_existing_manual_domain_and_grants(bundle):
    remote = configured(bundle[0])
    remote.configure('https://fixed.example.org', 9088, True)
    with pytest.raises(Denied):
        remote.start_temporary(True)
    grant = remote.create('manus', 60, 10)
    remote.configure('', 9088, False)
    with pytest.raises(Denied):
        remote.start_temporary(True)
    remote.g.revoke(grant['id'])
    assert remote.start_temporary(True)['verified']
    with pytest.raises(Denied):
        remote.configure('https://different.example.org', 8080, True)
    assert not remote.owner('remote-quick-stop', {})['enabled']


def test_guard_uses_fixed_target_and_kills_child_when_owning_process_closes(tmp_path):
    marker = tmp_path / 'child.json'
    stopped = tmp_path / 'stopped'
    def prepare(cache, work, cancel):
        binary = work / 'fake-helper'
        binary.write_text('#!' + sys.executable + '\n' +
            'import json, os, signal, sys, time\nfrom pathlib import Path\n' +
            f'Path({str(marker)!r}).write_text(json.dumps([sys.argv[1:], sorted(os.environ)]))\n' +
            f'signal.signal(signal.SIGTERM, lambda *_: (Path({str(stopped)!r}).touch(), sys.exit(0)))\n' +
            f'print("info | {ORIGIN} |", file=sys.stderr, flush=True)\nprint("Registered tunnel connection", file=sys.stderr, flush=True)\nwhile True: time.sleep(.1)\n')
        binary.chmod(0o700)
        return binary
    tunnel = quick_tunnel.QuickTunnel(tmp_path/'cache', prepare=prepare)
    done = threading.Event()
    assert tunnel.start(9874, lambda _: done.set()) == ORIGIN
    args, env = json.loads(marker.read_text())
    assert args[-2:] == ['--url','http://127.0.0.1:9874'] and '127.0.0.1:0' in args and args[args.index('--protocol')+1] == 'http2'
    assert not any(key.startswith(('TUNNEL_', 'NEAR_', 'OPENAI_')) for key in env)
    tunnel.stop()
    assert done.wait(5) and stopped.exists()


def test_fake_package_checksum_fails_before_execution(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(quick_tunnel.sys, 'platform', 'darwin')
    monkeypatch.setattr(quick_tunnel.platform, 'machine', lambda: 'arm64')
    client = httpx.Client
    body = b'wrong package'
    monkeypatch.setattr(httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(lambda _:
                            httpx.Response(200, content=body)), **kw))
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_kw: pytest.fail('Unsigned bytes reached pkgutil'))
    with pytest.raises(Denied, match='integrity'):
        quick_tunnel.prepare_helper(tmp_path/'cache', tmp_path, threading.Event())


@pytest.mark.skipif(sys.platform != 'darwin', reason='Actual macOS helper verification runs on Intel and Apple silicon')
def test_official_helper_checksum_install_and_offline_version(tmp_path):
    work = tmp_path/'work'
    work.mkdir()
    binary = quick_tunnel.prepare_helper(tmp_path/'cache', work, threading.Event())
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True, timeout=8,
                            env={'HOME':str(work), 'PATH':'/usr/bin:/bin'})
    assert 'cloudflared version ' + quick_tunnel.VERSION in result.stdout


def test_registered_edge_and_public_discovery_through_real_loopback(bundle):
    import httpx
    import socket
    from privacy_layer.remote_clients import LoopbackListener, set_active_gateway

    g = bundle[0]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with g.store.transaction() as data:
        data['remote_bridge'] = {'enabled':False, 'port':port}
    requests = []
    class Edge(httpx.BaseTransport):
        def __init__(self):
            self.http = httpx.HTTPTransport()
        def handle_request(self, request):
            assert request.url.host == ORIGIN.split('://')[1] and re.fullmatch(r'/link-check/[a-f0-9]{32}', request.url.path)
            requests.append(request.url.path)
            # Simulate TLS termination. Forward the original public Host.
            url = request.url.copy_with(scheme='http', host='127.0.0.1', port=port)
            return self.http.handle_request(httpx.Request('GET', url, headers={**dict(request.headers),'cf-ray':'deadbeef12345678-IAD'}))
        def close(self):
            self.http.close()
    listener = LoopbackListener()
    remote = RemoteClients(g, listener, tunnel_factory=Tunnel,
        verify=lambda host, event, check:quick_tunnel.verify_route(host, event, check, transport=Edge(), seconds=2))
    set_active_gateway(lambda:g)
    try:
        assert remote.start_temporary(True)['verified']
        assert len(requests) == 1 and requests[0].startswith('/link-check/')
    finally:
        remote.close()
        set_active_gateway(lambda:None)


@pytest.mark.parametrize('status,expected', [(429,'rate limit'),(502,'HTTP 502'),(403,'HTTP 403')])
def test_safe_quick_link_diagnostics(status, expected):
    import httpx
    edge = httpx.MockTransport(lambda _: httpx.Response(status, text='PRIVATE_ERROR_OUTPUT'))
    with pytest.raises(Denied, match=expected) as trouble:
        quick_tunnel.verify_route(ORIGIN, threading.Event(), LinkCheck(lambda:0), transport=edge, seconds=0)
    assert ORIGIN not in str(trouble.value) and 'PRIVATE_ERROR_OUTPUT' not in str(trouble.value)
    assert quick_tunnel.helper_error('quick tunnel provisioning failed with status 429: private data',None) == 'Cloudflare link provisioning returned HTTP 429.'


def test_dns_pending_exposes_one_page_and_unlocks_after_owner_redeems(bundle):
    g = bundle[0]
    remote = configured(g, lambda *args:False)  # Simulated failed Mac DNS lookup.
    pending = remote.start_temporary(True)
    item = pending['verification']
    assert not pending['verified'] and set(item) == {'url','expires','attempts_left'}
    path = item['url'].removeprefix(ORIGIN)
    assert re.fullmatch(r'/link-check/[0-9a-f]{32}', path) and item['attempts_left'] == 5
    check = remote.check
    for vendor in ('chatgpt','muse','manus','custom'):
        with pytest.raises(Denied):
            remote.create(vendor,60,2)
    with TestClient(BridgeApp(lambda:g,8794),base_url=ORIGIN) as c:
        for endpoint in ['/phone','/openapi.json','/api/state','/mcp','/v1/privacy_status']:
            assert c.get(endpoint).status_code == 404
        assert c.get(path).status_code == 403
        local = c.get(path, headers={'Host':'127.0.0.1:8794'})
        assert local.status_code == 204 and check.code not in local.text
        with pytest.raises(Denied):
            remote.confirm_temporary(check.code)  # No arriving external request yet.
        assert not remote.retry_temporary()['verified']
        response = c.get(path,headers={'cf-ray':'aabbccddeeff0011-IAD'})
        assert response.status_code == 200
        assert 'no-store' in response.headers['cache-control'] and 'no-referrer' == response.headers['referrer-policy']
        digits = re.search('<output id="airlock-code">([0-9]{8})</output>', response.text)[1]
        assert digits not in json.dumps(remote.state())
        assert remote.state()['verified'] is False
        assert c.post(path, json={'code':digits}).status_code==405
        assert remote.owner('remote-quick-confirm',{'code':digits})['verified']
        assert remote.state()['verification'] is None
        assert c.get(path,headers={'cf-ray':'aabbccddeeff0011-IAD'}).status_code == 404
        assert c.get('/openapi.json').json()['servers'] == [{'url':ORIGIN}]
        grant=remote.create('muse',60,2)
        assert c.post('/v1/privacy_status',json={},headers={'Authorization':'Bearer '+grant['credential']}).status_code == 200
    with pytest.raises(Denied):
        remote.confirm_temporary(digits)
    remote.close()


def test_external_check_attempts_expiry_and_retry(bundle):
    g, _, clock, *_ = bundle
    result = [False]
    def probe(*args):
        return result[0]
    remote = configured(g,probe)
    first = remote.owner('remote-quick-start',{'approved':True,'verification_method':'device'})
    assert first['verification'] and not first['verified']
    session = remote.tunnel
    wrong = '10000000' if remote.check.code != '10000000' else '10000001'
    for _ in range(5):
        with pytest.raises(Denied):
            remote.confirm_temporary(wrong)
    assert session.cancel.is_set() and not remote.state()['enabled']
    other = remote.start_temporary(True, 'device')
    assert other['verification']['url'] != first['verification']['url']
    clock[0] = other['verification']['expires']
    assert not remote.state()['enabled'] and remote.tunnel is None
    remote.start_temporary(True, 'device')
    result[0] = True
    assert remote.owner('remote-quick-retry',{})['verified']
    remote.close()


def test_system_resolver_failure_leaves_device_option():
    import httpx
    def no_dns(request):
        raise httpx.ConnectError('nodename nor servname provided',request=request)
    pending = quick_tunnel.verify_route(ORIGIN, threading.Event(), LinkCheck(lambda:0),
                                        transport=httpx.MockTransport(no_dns),seconds=0)
    assert pending is False
