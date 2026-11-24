"""Trusted release runner. Keeps private keys in a temporary macOS keychain."""
import argparse
import base64
import contextlib
import os
from pathlib import Path
import re
import secrets
import shlex
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macos import package
from macos.distribution import check, requirement

KEYS = ('AIRLOCK_APPLE_TEAM_ID', 'AIRLOCK_SIGNING_P12_BASE64', 'AIRLOCK_SIGNING_P12_PASSWORD',
        'AIRLOCK_NOTARY_KEY_P8_BASE64', 'AIRLOCK_NOTARY_KEY_ID', 'AIRLOCK_NOTARY_ISSUER_ID')


def configuration(values, required=False):
    if all(values.get(k) for k in KEYS):
        requirement(values[KEYS[0]])
        return values
    if required or any(values.get(k) for k in KEYS):
        missing = ', '.join(k for k in KEYS if not values.get(k))
        raise ValueError('Apple release configuration is incomplete. Set ' + missing)
    return None


def private_key_file(path, encoded):
    with path.open('xb') as stream:
        path.chmod(0o600)
        stream.write(base64.b64decode(''.join(encoded.split()), validate=True))


@contextlib.contextmanager
def signing_context(config):
    with tempfile.TemporaryDirectory(prefix='airlock-publisher-') as temp:
        directory = Path(temp)
        p12 = directory / 'developer-id.p12'
        p8 = directory / 'notary.p8'
        keychain = str(directory / 'publisher.keychain-db')
        private_key_file(p12, config['AIRLOCK_SIGNING_P12_BASE64'])
        private_key_file(p8, config['AIRLOCK_NOTARY_KEY_P8_BASE64'])
        password = secrets.token_urlsafe(32)
        security = '/usr/bin/security'
        previous = shlex.split(check(security, 'list-keychains', '-d', 'user'))
        check(security, 'create-keychain', '-p', password, keychain)
        try:
            check(security, 'unlock-keychain', '-p', password, keychain)
            check(security, 'set-keychain-settings', '-lut', '3600', keychain)
            check(security, 'list-keychains', '-d', 'user', '-s', keychain, *previous)
            check(security, 'import', p12, '-k', keychain, '-P', config['AIRLOCK_SIGNING_P12_PASSWORD'],
                  '-T', '/usr/bin/codesign')
            check(security, 'set-key-partition-list', '-S', 'apple-tool:,apple:', '-s', '-k', password, keychain)
            team = config['AIRLOCK_APPLE_TEAM_ID']
            matches = re.findall(r'\b([0-9A-Fa-f]{40}) "Developer ID Application: [^"\n]+ \('+team+r'\)"',
                                 check(security, 'find-identity', '-v', '-p', 'codesigning', keychain))
            if len(matches) != 1:
                raise ValueError('Import a single valid Developer ID Application identity for the configured Apple team.')
            yield {'identity': matches[0], 'team': team, 'keychain': keychain,
                   'auth': ['--key', p8, '--key-id', config['AIRLOCK_NOTARY_KEY_ID'],
                            '--issuer', config['AIRLOCK_NOTARY_ISSUER_ID']]}
        finally:
            try:
                check(security, 'list-keychains', '-d', 'user', '-s', *previous)
            finally:
                check(security, 'delete-keychain', keychain)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--google-client', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    values = {k: os.environ.pop(k, '') for k in KEYS}
    config = configuration(values, os.environ.get('AIRLOCK_REQUIRE_NOTARIZATION') == 'true')
    ctx = signing_context(config) if config else contextlib.nullcontext(None)
    with ctx as signing:
        package.build(args.destination, args.google_client, signing=signing, report_path=args.report)


if __name__ == '__main__':
    # CalledProcessError includes argv, which can contain a transient keychain
    # password during import. Keep those arguments out of workflow logs.
    import subprocess
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(f'{Path(error.cmd[0]).name} failed with status {error.returncode}.', file=sys.stderr)
        raise SystemExit(1)
