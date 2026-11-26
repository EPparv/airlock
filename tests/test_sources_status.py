import copy
import time
import pytest
from privacy_layer.sources import LocalSources, SCOPES


def source():
    class Transport:
        fail=False
        def request(self,*args,**kwargs):
            if self.fail:raise ValueError('PRIVATE_PROVIDER_ERROR')
            return {'messagesTotal':1}
    s=LocalSources(key=b'k'*32,transport=Transport())
    config={'client_id':'example','revision':1,'email':'test@example.com','features':['mail_read'],'tokens':{'access_token':'fictional','refresh_token':'fictional-refresh','scopes':[SCOPES['mail_read']],'expires_at':time.time()+3600}}
    s.google_config=lambda:copy.deepcopy(config)
    return s,config


def test_gmail_status_tracks_actual_success_and_failure_without_provider_details():
    s,_=source()
    assert s.gmail_state()['sign_in']=='not_checked'
    s.google('/profile')
    assert s.gmail_state()['sign_in']=='connected'
    s.transport.fail=True
    with pytest.raises(ValueError):s.google('/profile')
    assert s.gmail_state()['sign_in']=='unavailable'
    assert 'PRIVATE_PROVIDER_ERROR' not in str(s.gmail_state())


def test_gmail_status_does_not_reuse_old_or_different_account_verification():
    s,c=source();s.google('/profile');s.gmail_health['at']-=601
    assert s.gmail_state()['sign_in']=='not_checked'
    s.google('/profile');c['revision']=2
    assert s.gmail_state()['sign_in']=='not_checked'


def test_owner_configures_desktop_identity_locally_then_signs_in_separately(tmp_path, monkeypatch):
    from privacy_layer.core import Denied, EncryptedStore
    from privacy_layer import sources
    monkeypatch.setattr(sources, 'bundled_client', lambda: (None, ''))
    adapter = LocalSources(key=b'k' * 32, context_home=tmp_path)
    store_file = tmp_path / 'connections.enc'
    adapter.connection_store = EncryptedStore(store_file, adapter.key)
    identity = {'installed': {'client_id': 'fixture.apps.googleusercontent.com', 'client_secret': 'private-fixture',
                              'token_uri': 'https://example.invalid'}}
    with pytest.raises(Denied):
        adapter.configure_gmail({'web': identity['installed']})
    with pytest.raises(Denied):
        adapter.configure_gmail({'installed': {**identity['installed'], 'refresh_token': 'fixture-only'}})
    assert adapter.configure_gmail(identity) == {'configured': True}
    status = adapter.gmail_state()
    assert status['configured'] and status['account'] == '' and status['sign_in'] == 'not_checked'
    assert 'private-fixture' not in str(status) and b'private-fixture' not in store_file.read_bytes()
    assert set(adapter.google_config()) == {'client_id', 'client_secret', 'identity_source'}
    replacement = {'installed': {'client_id': 'other.apps.googleusercontent.com', 'client_secret': 'other-fixture'}}
    assert status['can_replace'] and adapter.configure_gmail(replacement)['configured']
    assert adapter.google_config()['client_id'] == replacement['installed']['client_id']
    with adapter.connection_store.transaction() as data:
        data['google']['tokens'] = {'refresh_token': 'fixture'}
    assert not adapter.gmail_state()['can_replace']
    with pytest.raises(Denied):
        adapter.configure_gmail(identity)


def test_previous_account_health_cannot_complete_a_new_sign_in():
    from types import SimpleNamespace
    adapter, _ = source()
    adapter.google('/profile')
    adapter.oauth = SimpleNamespace(status='waiting', error='')
    assert adapter.gmail_state()['sign_in'] == 'waiting'
    adapter.oauth.status = 'error'
    adapter.oauth.error = 'Consent cancelled'
    assert adapter.gmail_state()['error'] == 'Consent cancelled'
    assert adapter.gmail_state()['sign_in'] == 'error'
