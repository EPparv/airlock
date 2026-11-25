"""Optional observations from real, signed-in-free apps on a disposable macOS VM."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from privacy_layer import clients
from test_mcp import serving


@pytest.mark.skipif(not os.environ.get('AIRLOCK_VENDOR_PROBE'), reason='Requires opt-in vendor app runner')
def test_vendor_mac_launch_and_mcp_discovery(bundle, serving, tmp_path, monkeypatch):
    assert sys.platform == 'darwin' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
    agent = os.environ['AIRLOCK_VENDOR_AGENT']
    assert agent in ('codex', 'cursor')
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
    connection = clients.connect(gateway, agent=agent, approved=True,
                                 scope={'records': [], 'disclose': False, 'compute': False, 'proposals': False})
    try:
        assert connection['installed'] and Path(connection['path']) == config
        assert not clients.connection_status(gateway, connection['id'])['last_discovery']
        subprocess.run([os.environ['AIRLOCK_VENDOR_PROBE'], agent, os.environ['AIRLOCK_VENDOR_BUNDLE']], check=True, timeout=185)
        until = time.monotonic() + 35
        while time.monotonic() < until:
            if clients.connection_status(gateway, connection['id'])['last_discovery']:
                print('Vendor GUI performed authenticated MCP tools/list on the fresh Airlock grant.')
                break
            time.sleep(1)
        else:
            print('Vendor GUI launch verified. No MCP tool discovery observed before account sign-in or interactive approval.')
    finally:
        gateway.revoke(connection['id'])
