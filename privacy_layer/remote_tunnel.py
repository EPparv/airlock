"""Run an owner's dedicated private ChatGPT tunnel from an interactive terminal."""
import argparse
import getpass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


def launch_command(token_file, session_file):
    return shlex.join([sys.executable, str(Path(__file__).resolve()), '--token-file', str(token_file),
                       '--session-file', str(session_file)])


def run(token_file, session_file, tunnel_id, runtime_key, binary):
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
    env = {**os.environ, 'CONTROL_PLANE_API_KEY': runtime_key}
    subprocess.run([binary, 'init', '--sample', 'sample_mcp_stdio_local', '--profile', profile,
                    '--tunnel-id', tunnel_id, '--mcp-command', command], env=env, check=True)
    subprocess.run([binary, 'doctor', '--profile', profile, '--explain'], env=env, check=True)
    return subprocess.run([binary, 'run', '--profile', profile], env=env).returncode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--token-file', required=True, type=Path)
    p.add_argument('--session-file', required=True, type=Path)
    a = p.parse_args()
    binary = shutil.which('tunnel-client')
    if not binary:
        print('Install the official tunnel-client from OpenAI Platform tunnel settings, then run this command again.', file=sys.stderr)
        return 1
    print('Use a dedicated tunnel associated only with the people who may use this Airlock grant. Keep this window open while using ChatGPT.')
    try:
        return run(a.token_file, a.session_file, input('OpenAI tunnel ID: ').strip(),
                   getpass.getpass('Restricted tunnel runtime key: ').strip(), binary)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Tunnel setup stopped.', str(error) if isinstance(error, ValueError) else 'Check the tunnel-client output and workspace permissions.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
