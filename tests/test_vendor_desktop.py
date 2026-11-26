"""Optional observations from real, signed-in-free apps on a disposable macOS VM."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

import pytest
import uvicorn

from privacy_layer import clients
from privacy_layer.server import owner_app
from privacy_layer.device_apps import NativeApps
from test_mcp import serving


def observe_picker_request(application, port):
    async def observed(scope, receive, send):
        if scope.get('path') != '/api/workspace-launch-options':
            return await application(scope, receive, send)
        headers = dict(scope.get('headers', []))
        expected_origin = f'http://127.0.0.1:{port}'.encode('ascii')
        origin = headers.get(b'origin')
        origin_kind = {None:'absent', b'null':'null', expected_origin:'same-origin'}.get(origin, 'other')

        async def record(message):
            if message['type'] == 'http.response.start':
                print('WebKit picker POST:', message['status'], 'origin classification:', origin_kind,
                      'bearer present:', headers.get(b'authorization', b'').startswith(b'Bearer '), flush=True)
            await send(message)

        return await application(scope, receive, record)
    return observed


@contextmanager
def workspace_url(gateway):
    owner = secrets.token_urlsafe(32)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        application = observe_picker_request(owner_app(gateway, owner, port), port)
        server = uvicorn.Server(uvicorn.Config(application, log_level='critical', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started
            yield f'http://127.0.0.1:{port}/workspace/personal#{owner}'
        finally:
            server.should_exit = True
            thread.join(10)


@pytest.mark.skipif(not os.environ.get('AIRLOCK_VENDOR_PROBE'), reason='Requires opt-in vendor app runner')
def test_vendor_mac_launch_and_mcp_discovery(bundle, serving, tmp_path, monkeypatch):
    assert sys.platform == 'darwin' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
    agent = os.environ['AIRLOCK_VENDOR_AGENT']
    assert agent in ('codex', 'cursor', 'claude-desktop')
    config = Path.home() / clients.RELATIVE_CONFIGS[agent]
    assert not config.exists(), 'A preexisting user config is outside this disposable test.'
    root = tmp_path/'Airlock'
    (root/'.venv/bin').mkdir(parents=True)
    (root/'.venv/bin/python').symlink_to(sys.executable)
    (root/'privacy_layer').symlink_to(Path(clients.__file__).parent)
    (root/'.private').mkdir()
    (root/'release.json').write_text('{}')
    (root/'.private/launch.json').write_text(json.dumps({'mcp_url': serving[0]}))
    monkeypatch.setattr(clients, 'ROOT', root)

    gateway = bundle[0]
    gateway.device_apps = NativeApps()
    assert not gateway.list_grants()
    try:
        with workspace_url(gateway) as url:
            subprocess.run([os.environ['AIRLOCK_VENDOR_PROBE'], agent, os.environ['AIRLOCK_VENDOR_BUNDLE']],
                           check=True, timeout=240, env={**os.environ, 'AIRLOCK_VENDOR_WORKSPACE':url})
        grants = gateway.list_grants()
        assert len(grants) == 1, 'Reopening an active app should use its existing grant.'
        grant = grants[0]
        assert grant['agent'] == agent and grant['configured'] and grant['scope']['records'] == []
        assert config.is_file()
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            status = clients.connection_status(gateway, grant['id'])
            if status['last_discovery'] or status['last_call']:
                print('Vendor GUI authenticated to Airlock. Tool discovery:', bool(status['last_discovery']),
                      'tool call:', bool(status['last_call']))
                break
            time.sleep(1)
        else:
            print('Vendor GUI launch verified. No authenticated discovery before sign-in or vendor approval.')
    finally:
        for grant in gateway.list_grants():
            gateway.revoke(grant['id'])
