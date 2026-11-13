"""App-owned, distributable Google Desktop OAuth identity (never account tokens).

Desktop client identities are public application credentials. A registered client
can be bundled once by the app owner so users only see Google's sign-in flow.
No credential is invented and a web/service-account client is never accepted.
"""
import json
from pathlib import Path
import re

from .google_connection import ConnectorError

BUNDLED_CLIENT = Path(__file__).with_name('google_client.json')
_ALLOWED = {'client_id', 'project_id', 'auth_uri', 'token_uri', 'auth_provider_x509_cert_url', 'client_secret', 'redirect_uris'}


def desktop_client(value):
    if not isinstance(value, dict) or set(value) != {'installed'} or not isinstance(value['installed'], dict):
        raise ConnectorError('Choose the Google setup file for a Desktop app. Web-app and service-account files do not work here.')
    config = value['installed']
    if set(config) - _ALLOWED:
        raise ConnectorError('This file contains unexpected fields. Use the original Desktop app download, without account tokens.')
    identifier, secret = config.get('client_id'), config.get('client_secret')
    if not isinstance(identifier, str) or len(identifier) > 300 or not re.fullmatch(r'[A-Za-z0-9_-]+\.apps\.googleusercontent\.com', identifier):
        raise ConnectorError('This file does not contain a valid Google Desktop app ID.')
    if not isinstance(secret, str) or not 1 <= len(secret) <= 300 or any(c in secret for c in '\r\n\x00'):
        raise ConnectorError('The Google setup file is missing its Desktop app credential.')
    # Always discard downloaded endpoints; the connector uses fixed Google URLs.
    return {'client_id': identifier, 'client_secret': secret}


def read_client(path):
    path = Path(path)
    try:
        if path.stat().st_size > 65536:
            raise ValueError()
        return desktop_client(json.loads(path.read_text()))
    except (OSError, ValueError, UnicodeError):
        raise ConnectorError('Could not read the Google setup file. Download the Desktop app JSON again.') from None


def bundled_client():
    if not BUNDLED_CLIENT.exists():
        return None, ''
    try:
        return read_client(BUNDLED_CLIENT), ''
    except ConnectorError as error:
        return None, str(error)
