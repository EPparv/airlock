"""Check what macOS receives from the actual, shared browser/native launch adapter."""
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlparse

import pytest

from privacy_layer import agent_launch as launcher, clients
from privacy_layer.core import Denied


@pytest.fixture
def mac(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, 'platform', 'darwin')
    monkeypatch.setenv('HOME', str(tmp_path/'home'))
    monkeypatch.setattr(clients, 'ROOT', tmp_path/'Airlock'/'app')
    calls = []
    def capture(bundle, *items):
        calls.append((bundle, *items))
        return True
    monkeypatch.setattr(launcher, '_open', capture)
    return calls


@pytest.mark.parametrize(('agent','bundle','route','key'), [
    ('codex','com.openai.codex','codex://threads/new','prompt'),
    ('cursor','com.todesktop.230313mzl4w4u92','cursor://anysphere.cursor-deeplink/prompt','text'),
    ('claude-code','com.anthropic.claudefordesktop','claude://code/new','q'),
    ('claude-desktop','com.anthropic.claudefordesktop','claude://claude.ai/new','q'),
])
def test_vendor_draft_is_targeted_and_contains_only_fixed_request(mac, agent, bundle, route, key):
    result = launcher.open_agent(agent)
    assert result['opened'] and result['drafted'] and result['method'] == 'draft'
    (chosen, raw), = mac
    parsed = urlparse(raw)
    assert chosen == bundle and raw.split('?')[0] == route
    assert parse_qs(parsed.query) == {key:[launcher.STATUS_PROMPT]}
    assert not parsed.fragment and 'privacy_status' in launcher.STATUS_PROMPT


@pytest.mark.parametrize(('agent','expected','mcp_args'), [
    ('gemini-cli','gemini',['mcp', 'list']),
    ('openclaw','openclaw',['mcp', 'doctor','airlock','--probe']),
    ('muse-code','muse',['exec',launcher.STATUS_PROMPT]),
    ('claude-code','claude',['mcp','get','airlock']),
    ('codex','codex',['mcp','get','airlock']),
])
def test_terminal_handoff_is_prepared_and_uses_workspace_outside_user_projects(mac, tmp_path, monkeypatch, agent, expected, mcp_args):
    # Simulate a real terminal executing the generated file with an executable whose path needs quoting.
    folder = tmp_path/"that user's tool bin"
    folder.mkdir()
    output = tmp_path/'result.json'
    binary = folder/expected
    binary.write_text('#!'+launcher.sys.executable+'\nimport json,os,sys\n'
                      'open(os.environ["AIRLOCK_TEST_LOG"],"w").write(json.dumps([os.getcwd(),sys.argv[1:]]))\n')
    binary.chmod(0o700)
    monkeypatch.setenv('AIRLOCK_TEST_LOG', str(output))
    monkeypatch.setenv('PATH', str(folder)+':'+os.environ['PATH'])
    def capture(bundle, item):
        if bundle != 'com.apple.Terminal':
            return False
        assert item.stat().st_mode & 0o777 == 0o700
        assert not output.exists()
        finished = subprocess.run([str(item)], input='\n', text=True, check=True, capture_output=True)
        if agent == 'muse-code':
            assert launcher.STATUS_PROMPT in finished.stdout and 'Press Return' in finished.stdout
        assert not item.exists()  # launch script removed itself
        return True
    monkeypatch.setattr(launcher,'_open', capture)
    result = launcher.open_agent(agent)
    assert result['method'] == ('draft' if agent=='muse-code' else 'check')
    cwd, args = json.loads(output.read_text())
    assert args == mcp_args
    assert Path(cwd) == launcher._work_folder(agent)


def test_vscode_selects_prompt_and_only_installs_scoped_entry_in_dedicated_workspace(mac, monkeypatch):
    monkeypatch.delenv('COPILOT_HOME', raising=False)
    saved = clients.config_path('vscode')
    saved.parent.mkdir(parents=True)
    token = clients.ROOT/'.private/clients/vscode-test.token'
    entry = {'type':'stdio', **clients.server_entry(token)}
    saved.write_text(json.dumps({'mcpServers':{'airlock':entry,'private-other':{'token':'sensitive'}}}))
    assert launcher.open_agent('vscode')['drafted']
    bundle, root, prompt = mac[0]
    assert bundle == 'com.microsoft.VSCode'
    assert prompt.is_relative_to(root)
    assert launcher.STATUS_PROMPT in prompt.read_text() and "tools: ['airlock/privacy_status']" in prompt.read_text()
    target = root/'.vscode/mcp.json'
    assert json.loads(target.read_text()) == {'servers':{'airlock':entry}}
    assert 'sensitive' not in target.read_text() and root.stat().st_mode & 0o777 == 0o700
    assert launcher.open_agent('vscode')['opened'] and mac[1] == mac[0]
    tampered = dict(entry,command='/bin/echo')
    saved.write_text(json.dumps({'mcpServers':{'airlock':tampered}}))
    assert not launcher.open_agent('vscode')['opened'] and len(mac)==2
    assert 'private-other' not in target.read_text()


def test_unknown_agent_and_missing_apps_never_claim_a_connection(mac, monkeypatch):
    assert set(launcher.LOCAL_AGENTS) == set(launcher.SETUP_URLS)
    for value in ('https://foreign.test','file:///tmp/demo','mcp',{},None):
        with pytest.raises(Denied):
            launcher.open_agent(value)
        with pytest.raises(Denied):
            launcher.open_setup_help(value)
    assert not mac
    monkeypatch.setattr(launcher, '_open', lambda *args: False)
    monkeypatch.setattr(launcher, '_cli', lambda command: None)
    for agent in launcher.LOCAL_AGENTS:
        assert launcher.open_agent(agent)['method'] == 'unavailable'
    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    assert not launcher.open_agent('cursor')['opened']


def test_official_help_only_opens_fixed_https_url(mac,monkeypatch):
    calls = []
    def capture(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(subprocess,'run',capture)
    for key, url in launcher.SETUP_URLS.items():
        assert launcher.open_setup_help(key)['opened']
        assert calls[-1] == ['/usr/bin/open',url] and url.startswith('https://')
