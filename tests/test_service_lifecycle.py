"""Exercise the actual two loopback listeners and the desktop launch receipt."""
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

import pytest

from privacy_layer.launcher import probe_session

ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


@contextlib.contextmanager
def service(state, owner=0, mcp=0):
    process = subprocess.Popen([
        sys.executable, '-m', 'privacy_layer.server', '--safe-start', '--state', str(state),
        '--owner-port', str(owner), '--mcp-port', str(mcp),
    ], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            record = probe_session(state/'launch.json', timeout=.5)
            if record and record['pid'] == process.pid:
                break
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode())
            time.sleep(.05)
        else:
            raise AssertionError('The authenticated local service did not become ready.')
        yield record
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stderr.close()


def test_launch_stop_and_reopen_on_same_ports(tmp_path):
    state = tmp_path/'state'
    with service(state) as first:
        owner = urlsplit(first['url']).port
        mcp = urlsplit(first['mcp_url']).port
        assert owner != mcp
        assert json.loads((state/'mcp-endpoint.json').read_text()) == {'mcp_url':first['mcp_url']}
        assert (state/'mcp-endpoint.json').stat().st_mode & 0o777 == 0o600
        assert (state/'launch.json').stat().st_mode & 0o777 == 0o600
        with HTTP.open(f'http://127.0.0.1:{owner}/workspace/personal') as page:
            assert page.status == 200
        with pytest.raises(HTTPError) as denied:
            HTTP.open(Request(first['mcp_url'], data=b'{}'))
        assert denied.value.code == 401
        duplicate = subprocess.run([sys.executable, '-m', 'privacy_layer.server', '--safe-start',
                                    '--state', str(state), '--owner-port', '0', '--mcp-port', '0'],
                                   cwd=ROOT, capture_output=True, timeout=5)
        assert duplicate.returncode != 0
        assert probe_session(state/'launch.json') == first
    assert probe_session(state/'launch.json') is None
    for port in (owner, mcp):
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1', port)) != 0
    with service(state, owner, mcp) as second:
        assert second['owner_token'] != first['owner_token']
        request = Request(f'http://127.0.0.1:{owner}/api/test-state', data=b'{}',
                          headers={'Authorization':'Bearer '+first['owner_token']})
        with pytest.raises(HTTPError) as expired:
            HTTP.open(request)
        assert expired.value.code == 401
        request.add_header('Authorization', 'Bearer '+second['owner_token'])
        with HTTP.open(request) as reply:
            assert json.load(reply)['personal_open'] is False


def test_another_listener_cannot_receive_recovery_credential(tmp_path):
    requests = []
    class UnrelatedApp(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'an unrelated loopback service')
        def log_message(self, *args): pass

    with HTTPServer(('127.0.0.1',0), UnrelatedApp) as server:
        port = server.server_port
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        receipt = tmp_path/'launch.json'
        receipt.write_text(json.dumps({'url':f'http://127.0.0.1:{port}/workspace#fixture',
                                       'owner_token':'fixture', 'session_check':1}))
        receipt.chmod(0o600)
        assert probe_session(receipt) is None
        thread.join(timeout=2)
    [(path, headers)] = requests
    assert path == '/_airlock/session'
    assert headers.get('Authorization') is None
    assert 'fixture' not in str(headers)
