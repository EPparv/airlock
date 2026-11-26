"""Prepare a distributable Google Desktop app identity for one trusted Mac build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from private_ai.google_app import desktop_client
from private_ai.google_connection import ConnectorError

SECRET_NAME = 'AIRLOCK_GOOGLE_DESKTOP_CLIENT_JSON'


def prepare(destination, *, required=False):
    if os.path.lexists(destination):
        raise ValueError('Choose a new temporary output file for this build.')
    raw = os.environ.pop(SECRET_NAME, '')
    if not raw:
        if required:
            raise ValueError('This build requires the publisher Google Desktop OAuth client.')
        return False
    if len(raw.encode()) > 65536:
        raise ValueError('The publisher Google OAuth setup is too large.')
    try:
        identity = desktop_client(json.loads(raw))
    except (ValueError, ConnectorError, RecursionError):
        raise ValueError('Supply the downloaded Google Desktop OAuth client JSON. Account tokens and web or service-account credentials are rejected.') from None
    payload = json.dumps({'installed': identity}, indent=2).encode()
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return True


def verify_distributable(payload, expected_sha256):
    if len(payload) > 65536 or not expected_sha256 or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError('The bundled Google Desktop identity differs from the trusted build input.')
    try:
        identity = desktop_client(json.loads(payload))
    except (ValueError, UnicodeError, ConnectorError, RecursionError):
        raise ValueError('Invalid bundled Google Desktop identity.') from None
    if payload != json.dumps({'installed': identity}, indent=2).encode():
        raise ValueError('The bundled Google Desktop identity has unexpected fields or encoding.')
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--require', action='store_true', help='Stop distribution when the publisher identity is missing.')
    args = parser.parse_args()
    try:
        configured = prepare(args.destination, required=args.require)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print('Publisher Gmail sign-in included.' if configured else 'Personal Google Desktop setup available.')
