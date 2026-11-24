import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from starlette.testclient import TestClient

from privacy_layer import quick_tunnel
from privacy_layer.core import Denied
from privacy_layer.remote_clients import BridgeApp, RemoteClients
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


def configured(gateway, verifier=lambda origin, cancel: None):
    return RemoteClients(gateway, FakeListener(), tunnel_factory=Tunnel, verify=verifier)


def test_only_owner_can_open_then_verified_url_is_bound_and_retired_on_lock(bundle):
    g = bundle[0]
    active = [g]
    server = BridgeApp(lambda: active[0], 8794)
    calls = []
    def verify(origin, cancel):
        with TestClient(server, base_url=origin) as c:
            assert c.get('/openapi.json').json()['servers'] == [{'url':origin}]
            assert c.get('/api/workspace-state').status_code == 404
            with pytest.raises(Denied):
                remote.create('muse', 60, 3)
        calls.append(origin)
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
    def verify(origin, cancel):
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
            f'print("info | {ORIGIN} |", file=sys.stderr, flush=True)\nwhile True: time.sleep(.1)\n')
        binary.chmod(0o700)
        return binary
    tunnel = quick_tunnel.QuickTunnel(tmp_path/'cache', prepare=prepare)
    done = threading.Event()
    assert tunnel.start(9874, lambda _: done.set()) == ORIGIN
    args, env = json.loads(marker.read_text())
    assert args[-2:] == ['--url','http://127.0.0.1:9874'] and '127.0.0.1:0' in args
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
