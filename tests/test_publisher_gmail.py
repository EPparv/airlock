"""Published Mac OAuth configuration and real loopback callbacks, with a synthetic Google transport."""
import base64
import hashlib
import json
import stat
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import build_opener, ProxyHandler

import pytest

from macos.package import entries
from privacy_layer import sources
from privacy_layer.core import EncryptedStore
from scripts.prepare_google_oauth import prepare, SECRET_NAME, verify_distributable


CLIENT = {'client_id': 'airlock-test.apps.googleusercontent.com', 'client_secret': 'synthetic-desktop-client'}
LOCAL_HTTP = build_opener(ProxyHandler({}))


def test_prepared_identity_matches_packaged_bytes_and_drops_extra_fields(tmp_path, monkeypatch):
    data = {'installed': {**CLIENT, 'project_id': 'demo', 'token_uri': 'https://example.invalid/token'}}
    target = tmp_path / 'prepared.json'
    monkeypatch.setenv(SECRET_NAME, json.dumps(data))
    assert prepare(target, required=True)
    payload = target.read_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(payload) == {'installed': CLIENT}
    assert entries(target)['vendor/private_ai/google_client.json'] == payload
    digest = hashlib.sha256(payload).hexdigest()
    assert verify_distributable(payload, digest) == payload
    with pytest.raises(ValueError):
        verify_distributable(payload, '')
    with pytest.raises(ValueError):
        verify_distributable(payload, '0' * 64)
    with pytest.raises(ValueError):
        prepare(target)
    assert target.read_bytes() == payload
    other = json.dumps(data, indent=2).encode()
    with pytest.raises(ValueError):
        verify_distributable(other, hashlib.sha256(other).hexdigest())


@pytest.mark.parametrize('data', ['bad-json', json.dumps({'web': CLIENT}),
                                  json.dumps({'installed': {**CLIENT, 'refresh_token': 'highly-private-fixture'}})])
def test_publisher_input_failure_never_echoes_or_writes_secret(data, tmp_path, monkeypatch):
    target = tmp_path / 'prepared.json'
    monkeypatch.setenv(SECRET_NAME, data)
    with pytest.raises(ValueError) as error:
        prepare(target)
    assert CLIENT['client_secret'] not in str(error.value) and 'highly-private-fixture' not in str(error.value)
    assert not target.exists()


def test_empty_identity_is_optional_for_testing_and_required_when_requested(tmp_path, monkeypatch):
    target = tmp_path / 'prepared.json'
    monkeypatch.delenv(SECRET_NAME, raising=False)
    assert not prepare(target)
    with pytest.raises(ValueError):
        prepare(target, required=True)
    assert not target.exists()


class GoogleConsent:
    def __init__(self, option):
        self.option = option
        self.params = {}
        self.calls = []

    def request(self, destination, **kwargs):
        self.calls.append(destination)
        if destination == sources.TOKEN:
            data = kwargs['data']
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).decode().rstrip('=')
            assert encoded == self.params['code_challenge'][0]
            assert data['code'] == 'fixture-code' and data['redirect_uri'] == self.params['redirect_uri'][0]
            assert data['client_id'] == CLIENT['client_id'] and data['client_secret'] == CLIENT['client_secret']
            scopes = self.params['scope'][0]
            if self.option == 'extra':
                scopes += ' ' + sources.SCOPES['mail_send']
            if self.option == 'partial':
                scopes = sources.EMAIL_SCOPE
            return {'token_type': 'bearer', 'expires_in': 3600, 'scope': scopes, 'access_token': 'fixture-access',
                    'refresh_token': 'fixture-refresh'}
        assert destination == sources.USERINFO and kwargs['token'] == 'fixture-access'
        return {'email': 'member@example.invalid', 'verified_email': self.option != 'unverified'}


@pytest.mark.parametrize('option', ['ok', 'declined', 'extra', 'partial', 'unverified', 'locked'])
def test_real_pkce_callback_from_packaged_client(tmp_path, monkeypatch, option):
    transport = GoogleConsent(option)
    # Use the file adapter exactly as a Mac bundle would.
    from private_ai import google_app
    monkeypatch.setenv(SECRET_NAME, json.dumps({'installed': CLIENT}))
    identity = tmp_path / 'google_client.json'
    prepare(identity)
    monkeypatch.setattr(google_app, 'BUNDLED_CLIENT', identity)
    adapter = sources.LocalSources(key=b'k' * 32, context_home=tmp_path, transport=transport)
    path = tmp_path / 'vault.enc'
    adapter.connection_store = EncryptedStore(path, adapter.key)
    assert adapter.gmail_state()['identity_source'] == 'publisher' and adapter.gmail_state()['account'] == ''
    parsed = urlsplit(adapter.connect_gmail()['url'])
    assert parsed.scheme == 'https' and parsed.hostname == 'accounts.google.com'
    transport.params = params = parse_qs(parsed.query)
    assert params['scope'][0].split() == [sources.EMAIL_SCOPE, sources.SCOPES['mail_read']]
    assert params['code_challenge_method'] == ['S256']
    callback = params['redirect_uri'][0]
    assert urlsplit(callback).hostname == '127.0.0.1'
    bad_return = callback + '?' + urlencode({'code': 'ignore', 'state': 'wrong-state'})
    try:
        with pytest.raises(HTTPError):
            LOCAL_HTTP.open(bad_return, timeout=3)
        assert not transport.calls
        if option == 'locked':
            # The same cancellation hook runs when the personal workspace is locked.
            adapter.cancel_gmail_sign_in()
            adapter.oauth.thread.join(timeout=3)
            assert not adapter.oauth.thread.is_alive() and not transport.calls
        else:
            query = {'state': params['state'][0], 'error': 'access_denied'} if option == 'declined' else {
                'state': params['state'][0], 'code': 'fixture-code'}
            url = callback + '?' + urlencode(query)
            if option == 'ok':
                with LOCAL_HTTP.open(url, timeout=3) as request:
                    assert request.status == 200 and 'Google is connected' in request.read().decode()
            else:
                with pytest.raises(HTTPError) as response:
                    LOCAL_HTTP.open(url, timeout=3)
                assert response.value.code == 400
            adapter.oauth.thread.join(timeout=3)
        status = adapter.gmail_state()
        assert status['identity_source'] == 'publisher'
        assert status['account'] == ('member@example.invalid' if option == 'ok' else '')
        assert 'fixture-refresh' not in str(status) and CLIENT['client_secret'] not in str(status)
        assert not path.exists() or b'fixture-access' not in path.read_bytes()
        if option == 'declined':
            assert not transport.calls and 'test user' in status['error']
        if option in ('extra', 'partial'):
            assert transport.calls == [sources.TOKEN]
    finally:
        adapter.cancel_gmail_sign_in()
        adapter.oauth.thread.join(timeout=3)
