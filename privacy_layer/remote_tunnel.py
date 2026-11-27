"""Run and observe the owner's dedicated ChatGPT tunnel without recording keys or service logs."""
import argparse
import fcntl
import getpass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


TUNNEL_PHASE = {
    'unknown':'The tunnel has not been started by this version of Airlock.',
    'input':'Terminal is waiting for the dedicated tunnel credentials.',
    'checking':'The local tunnel client is checking the profile.',
    'running':'The local tunnel process is running. A tool call confirms the provider can reach Airlock.',
    'stopped':'The local tunnel process stopped. Reopen the tunnel to reconnect.',
    'missing':'Install the official OpenAI tunnel-client, then reopen the tunnel.',
    'timeout':'OpenAI tunnel setup timed out. Check the Mac’s network, then reopen the tunnel.',
    'rate':'OpenAI returned HTTP 429. Wait for Retry-After if supplied and check the organization’s quota before retrying.',
    'auth':'OpenAI rejected the tunnel credentials. Check the restricted runtime key, the workspace association and Tunnels Read and Use.',
    'failed':'The tunnel did not start. Check the tunnel ID, network and workspace permissions.',
}


def tunnel_binary(root=None):
    """Finder, Terminal and earlier Airlock installs can have different search paths."""
    if root:
        legacy = Path(root) / '.tools/tunnel-client'
        if legacy.is_file() and os.access(legacy, os.X_OK):
            return str(legacy)
    home = Path.home()
    path = os.pathsep.join([os.environ.get('PATH', os.defpath), '/opt/homebrew/bin', '/usr/local/bin', str(home/'.local/bin')])
    return shutil.which('tunnel-client', path=path)


def failure_phase(text):
    if re.search(r'(?<!\d)429(?!\d)|too many requests|rate[ _-]?limit', text, re.I):
        return 'rate'
    if re.search(r'(?<!\d)(401|403)(?!\d)|unauthorized|forbidden', text, re.I):
        return 'auth'
    return 'failed'


def launch_command(token_file, session_file):
    return shlex.join([sys.executable, str(Path(__file__).resolve()), '--token-file', str(token_file),
                       '--session-file', str(session_file)])


def local_status(token_file):
    try:
        with token_file.with_suffix('.tunnel-state').open() as state:
            try:
                fcntl.flock(state, fcntl.LOCK_SH | fcntl.LOCK_NB)
                active = False
            except BlockingIOError:
                active = True
            phase = state.read(20).strip()
        if phase not in TUNNEL_PHASE:
            phase = 'unknown'
        if not active and phase in ('input','checking','running'):
            phase = 'stopped'
    except OSError:
        phase, active = 'unknown', False
    return {'phase':phase,'active':active,'message':TUNNEL_PHASE[phase]}


def write_phase(state, phase):
    state.seek(0)
    state.truncate()
    state.write(phase)
    state.flush()


def run(token_file, session_file, tunnel_id, runtime_key, binary, on_phase=lambda _: None):
    if not re.fullmatch(r'tunnel_[A-Za-z0-9]{4,128}', tunnel_id):
        raise ValueError('Enter a valid OpenAI tunnel ID.')
    if not runtime_key.startswith('sk-') or not 8 <= len(runtime_key) <= 500:
        raise ValueError('Enter the restricted tunnel runtime key.')
    if not re.fullmatch(r'chatgpt-[a-f0-9]{32}\.token', token_file.name):
        raise ValueError('Use the command for this ChatGPT connection.')
    if not token_file.is_file() or not session_file.is_file():
        raise ValueError('Open the personal workspace in Airlock and create a ChatGPT connection.')
    bridge = Path(__file__).with_name('stdio.py')
    command = shlex.join([sys.executable, str(bridge), '--token-file', str(token_file), '--session-file', str(session_file)])
    profile = 'airlock-' + token_file.stem.split('-', 1)[1]
    on_phase('checking')
    # init refuses existing profiles. Keep the generated configuration private
    # to this run and reuse the persistent Airlock grant on every reconnect.
    with tempfile.TemporaryDirectory(prefix='airlock-chatgpt-') as profile_dir:
        env = {**os.environ, 'CONTROL_PLANE_API_KEY':runtime_key}
        selection = ['--profile', profile, '--profile-dir', profile_dir]
        for args in (['init', '--sample', 'sample_mcp_stdio_local', *selection,
                      '--tunnel-id', tunnel_id, '--mcp-command', command], ['doctor', *selection, '--explain']):
            result = subprocess.run([binary, *args], env=env, capture_output=True, timeout=45)
            if result.returncode:
                detail = (result.stderr + result.stdout).decode('utf-8', errors='replace')
                phase = failure_phase(detail)
                on_phase(phase)
                raise ValueError(TUNNEL_PHASE[phase])
        on_phase('running')
        return subprocess.run([binary, 'run', *selection], env=env).returncode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--token-file', required=True, type=Path)
    p.add_argument('--session-file', required=True, type=Path)
    a = p.parse_args()
    if not re.fullmatch(r'chatgpt-[a-f0-9]{32}\.token', a.token_file.name) or not a.token_file.is_file():
        print('Use the tunnel setup supplied by your active ChatGPT connection.', file=sys.stderr)
        return 1
    fd = os.open(a.token_file.with_suffix('.tunnel-state'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as state:
        try:
            fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('The tunnel setup for this connection is already open.')
            return 0
        phase = 'input'
        def update(value):
            nonlocal phase
            phase = value
            write_phase(state, value)
        binary = tunnel_binary(Path(__file__).resolve().parents[1])
        if not binary:
            update('missing')
            print(TUNNEL_PHASE[phase], file=sys.stderr)
            return 1
        update('input')
        print('Enter your dedicated OpenAI tunnel credentials. Keep Terminal open while using ChatGPT.')
        try:
            code = run(a.token_file, a.session_file, input('OpenAI tunnel ID: ').strip(),
                       getpass.getpass('Restricted tunnel runtime key: ').strip(), binary, update)
            update('stopped' if code == 0 else 'failed')
            return code
        except subprocess.TimeoutExpired:
            update('timeout')
            print(TUNNEL_PHASE[phase], file=sys.stderr)
            return 1
        except (ValueError, OSError, EOFError) as error:
            if phase not in ('rate','auth','failed'):
                update('failed')
            print(str(error) if isinstance(error, ValueError) else TUNNEL_PHASE[phase], file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            update('stopped')
            return 130


if __name__ == '__main__':
    sys.exit(main())
