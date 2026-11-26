"""Launch a known local agent with Airlock's status check from the Mac owner service."""
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote

from . import clients
from .core import Denied


STATUS_PROMPT = 'Call only the Airlock privacy_status tool and report whether it responds.'
DESKTOP = {
    'codex': ('Codex', 'com.openai.codex', 'codex://threads/new?prompt='),
    'cursor': ('Cursor', 'com.todesktop.230313mzl4w4u92', 'cursor://anysphere.cursor-deeplink/prompt?text='),
    'claude-desktop': ('Claude Desktop', 'com.anthropic.claudefordesktop', 'claude://claude.ai/new?q='),
    'claude-code': ('Claude Code', 'com.anthropic.claudefordesktop', 'claude://code/new?q='),
}
# These inspection commands run inside the vendor client without starting a model turn.
TERMINAL_CHECKS = {
    'codex': ('codex', ('mcp', 'get', 'airlock')),
    'claude-code': ('claude', ('mcp', 'get', 'airlock')),
    'gemini-cli': ('gemini', ('mcp', 'list')),
    'openclaw': ('openclaw', ('mcp', 'doctor', 'airlock', '--probe')),
    # Muse starts its real MCP runtime with its built-in offline echo provider.
    'muse-code': ('muse', ('exec', '--provider', 'echo', '--trust-workspace', '--no-session-log',
                           '--no-foreign-personal-context', 'Check Airlock tools.')),
}
LOCAL_AGENTS = tuple(clients.RELATIVE_CONFIGS)
SETUP_URLS = {
    'codex': 'https://learn.chatgpt.com/docs/app',
    'cursor': 'https://cursor.com/downloads',
    'claude-desktop': 'https://claude.com/download',
    'claude-code': 'https://code.claude.com/docs/en/quickstart',
    'vscode': 'https://code.visualstudio.com/download',
    'muse-code': 'https://dev.meta.ai/docs/muse-code',
    'gemini-cli': 'https://geminicli.com/docs/get-started/installation/',
    'openclaw': 'https://docs.openclaw.ai/install',
}


def _result(method, message):
    return {'opened': method != 'unavailable', 'drafted': method == 'draft',
            'method': method, 'message': message}


def _open(bundle_id, *items):
    # Explicit bundle selection prevents a different default scheme handler receiving the prompt.
    result = subprocess.run(['/usr/bin/open', '-b', bundle_id, *map(str, items)], check=False, timeout=10,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def open_setup_help(agent):
    if not isinstance(agent, str) or agent not in SETUP_URLS:
        raise Denied('Choose a supported Mac agent.')
    if sys.platform == 'darwin':
        try:
            result = subprocess.run(['/usr/bin/open', SETUP_URLS[agent]], check=False, timeout=10,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                return {'opened': True, 'message': 'Opened the official setup page.'}
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {'opened': False, 'message': 'Couldn’t open the setup page. Visit ' + SETUP_URLS[agent]}


def _cli(command):
    return shutil.which(command, path=clients.executable_path(Path.home()))


def _work_folder(*parts):
    # Keep the vendor's own trust decision for repeat connects. Do not open Airlock's
    # source, vault or another project as the client workspace.
    folder = Path.home()/'Library/Caches'
    folder.mkdir(parents=True, exist_ok=True)
    for part in ('Airlock Agent Checks', *parts):
        folder = folder / part
        folder.mkdir(mode=0o700, exist_ok=True)
        st = folder.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise ValueError('Unusable connection-check folder')
    return folder


def _write_private(path, content):
    # Atomic replacements never follow an existing output symlink.
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(content)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _terminal(agent):
    name = clients.CLIENTS[agent]['name']
    command, arguments = TERMINAL_CHECKS[agent]
    binary = _cli(command)
    if not binary:
        return _result('unavailable', f'Install {name} on this Mac, then choose Connect again.')
    folder = _work_folder(agent)
    fd, temporary = tempfile.mkstemp(prefix='Airlock-connection-', suffix='.command')
    script = Path(temporary)
    lines = [
        '#!/bin/sh', 'set -eu', 'umask 077',
        'cd -- ' + shlex.quote(str(folder)),
        '/bin/rm -f -- "$0"',
        'export PATH=' + shlex.quote(str(Path(binary).parent) + os.pathsep + clients.executable_path(Path.home())) + ':"$PATH"',
    ]
    # Terminal is another existing macOS process. Match the profile Airlock
    # configured even when that process inherited a different shell environment.
    profile_vars = {'codex': ('CODEX_HOME',), 'claude-code': ('CLAUDE_CONFIG_DIR',),
                    'gemini-cli': ('GEMINI_CLI_HOME',), 'muse-code': ('XDG_CONFIG_HOME',),
                    'openclaw': ('OPENCLAW_CONFIG_PATH','OPENCLAW_STATE_DIR','OPENCLAW_PROFILE')}
    for key in profile_vars.get(agent, ()):
        value = os.environ.get(key)
        lines.append('export ' + key + '=' + shlex.quote(value) if value else 'unset ' + key)
    if agent == 'muse-code':
        # Muse refuses even user-configured MCP servers in an untrusted folder.
        # Ask for this run only, then create a fresh folder with no project settings.
        lines.extend([
            "printf '%s\\n' 'Check Airlock tools with Muse Code’s offline provider.'",
            "printf '%s' 'Press Return to trust an empty Airlock folder for this run, or close this window to cancel. '",
            'IFS= read -r confirm', '[ -z "$confirm" ] || exit 0',
            'check_dir=$(/usr/bin/mktemp -d "$PWD/check.XXXXXXXX")', 'cd -- "$check_dir"',
            """trap 'cd / && /bin/rmdir -- "$check_dir" 2>/dev/null || :' EXIT""",
            shlex.join((binary, *arguments)) + ' >/dev/null',
            "printf '%s\\n' 'See Airlock for the connection result.'",
        ])
    elif agent == 'gemini-cli':
        # With folder trust enabled, Gemini's noninteractive list command only
        # prints a warning. Open its own interactive trust dialog in that folder.
        lines += [
            'report=$(' + shlex.join((binary, *arguments)) + ' 2>&1) || { printf "%s\\n" "$report"; exit 1; }',
            'printf "%s\\n" "$report"',
            'case "$report" in *"because this folder is untrusted"*) exec ' + shlex.quote(binary) + ' ;; esac',
        ]
    else:
        lines.append('exec ' + shlex.join((binary, *arguments)))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            os.fchmod(out.fileno(), 0o700)
            out.write('\n'.join(lines) + '\n')
        if _open('com.apple.Terminal', script):
            if agent == 'muse-code':
                return _result('check', 'Press Return in Terminal to let Muse Code check Airlock from an empty folder.')
            return _result('check', f'Opened {name}’s connection check in Terminal.')
    except (OSError, subprocess.TimeoutExpired):
        pass
    script.unlink(missing_ok=True)
    return _result('unavailable', f'Couldn’t open Terminal for {name}. Open Terminal and try again.')


def _vscode():
    # VS Code's current Copilot harness uses the Copilot profile. Its prompt-file Run button also
    # supports the Local harness, which reads a different workspace-level registration.
    config = clients.config_path('vscode')
    if config.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Unexpected Copilot configuration size')
    registered = json.loads(config.read_text(encoding='utf-8'), object_pairs_hook=clients.unique_keys)
    servers = registered.get('mcpServers') if isinstance(registered, dict) else None
    entry = servers.get(clients.SERVER) if isinstance(servers, dict) else None
    if not isinstance(entry, dict) or not isinstance(entry.get('args'), list) or len(entry['args']) not in (3, 5):
        raise ValueError('Missing Airlock connection')
    token = Path(entry['args'][2])
    if (token.parent != clients.ROOT/'.private/clients' or not token.name.startswith('vscode-')
            or token.suffix != '.token' or entry != {'type':'stdio', 'tools':['*'], **clients.server_entry(token)}):
        raise ValueError('Unexpected server registration')
    root = _work_folder('vscode', token.stem)
    server_dir = _work_folder('vscode', token.stem, '.vscode')
    prompts = _work_folder('vscode', token.stem, '.github', 'prompts')
    _write_private(server_dir/'mcp.json', json.dumps({'servers': {'airlock': {'type':'stdio', **clients.server_entry(token)}}}))
    prompt = prompts/'airlock-status.prompt.md'
    _write_private(prompt, "---\ndescription: Check the Airlock connection\ntools: ['airlock/privacy_status']\n---\n\n"
                   + STATUS_PROMPT + '\n')
    if _open('com.microsoft.VSCode', root, prompt):
        return _result('draft', 'Opened the Airlock request in VS Code. Select Run in Chat to send it.')
    return _result('unavailable', 'Install Visual Studio Code on this Mac, then choose Connect again.')


def open_agent(agent):
    """Open the fixed route for a personal, configured connection; verify use via gateway receipts."""
    if not isinstance(agent, str) or agent not in LOCAL_AGENTS:
        raise Denied('Choose a supported Mac agent.')
    if sys.platform != 'darwin':
        return _result('unavailable', 'Open Airlock on your Mac to launch this agent.')
    try:
        if agent in DESKTOP:
            name, bundle_id, base = DESKTOP[agent]
            url = base + quote(STATUS_PROMPT, safe='')
            if agent == 'codex':
                # The combined ChatGPT desktop app can have a remote or non-Codex
                # chat active. Select an explicit local workspace for the stdio server.
                url += '&path=' + quote(str(_work_folder(agent)), safe='')
            if _open(bundle_id, url):
                return _result('draft', f'Opened {name} with the Airlock status request ready to send.')
            if agent not in TERMINAL_CHECKS:
                return _result('unavailable', f'Install the Mac app for {name}, then choose Connect again.')
        if agent == 'vscode':
            return _vscode()
        return _terminal(agent)
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return _result('unavailable', 'Airlock couldn’t open this agent. Check its installation and try again.')
