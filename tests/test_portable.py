import base64,json,time
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
from urllib.request import urlopen
import pytest
from privacy_layer import sources,clients,setup
from privacy_layer.core import EncryptedStore,Gateway,Denied
from privacy_layer.context import ContextHub
from privacy_layer.server import owner_app
from starlette.testclient import TestClient

def test_empty_install_import_without_legacy_vault(tmp_path):
    s=sources.LocalSources(key=b'k'*32,context_home=tmp_path)
    st=EncryptedStore(tmp_path/'context.enc',s.key);s.connection_store=st
    assert s.path is None and s.library()==[]
    hub=ContextHub(st,tmp_path);p=hub.preview('context.md',b'# Memories\nFictional Aurora launch is November 17.\n# Skills\nUse three short bullets for Aurora updates.','auto')
    hub.commit(p['id'],list(range(len(p['items']))),[])
    assert {r['kind'] for r in s.library()}=={'memories','skills'}
    g=Gateway(st,s);grant=g.create(agent='codex',purpose='Test import',views=[],approved=True,mode='automatic')
    result=g.call(grant['token'],'get_private_context',{'query':'Aurora launch updates'})
    assert result['library_counts']=={'memories':1,'skills':1}
    assert 'November 17' in str(result) and 'three short bullets' in str(result)
    assert not (tmp_path/'.private-ai/vault.enc').exists()

def test_fresh_keychain_setup_never_resets_existing_store(tmp_path,monkeypatch):
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    class Keys:
        value=None
        def __init__(self,path):pass
        def get(self):return type(self).value
        def set(self,v):type(self).value=v
    monkeypatch.setattr(sources,'MacKeychain',Keys)
    first=sources.LocalSources(context_home=tmp_path);second=sources.LocalSources(context_home=tmp_path)
    assert first.key==second.key and len(first.key)==32
    (tmp_path/'.private/connections.enc').write_bytes(b'previous-encrypted-data');Keys.value=None
    with pytest.raises(sources.DeviceAccessError):sources.LocalSources(context_home=tmp_path)
    assert (tmp_path/'.private/connections.enc').read_bytes()==b'previous-encrypted-data'

class GoogleFixture:
    def __init__(self):self.calls=[]
    def request(self,url,**kw):
        self.calls.append((url,kw))
        if url==sources.TOKEN:
            assert kw['data']['code']=='fictional-code' and len(kw['data']['code_verifier'])>=43
            return {'access_token':'FICTIONAL_ACCESS','refresh_token':'FICTIONAL_REFRESH','token_type':'Bearer','expires_in':3600,'scope':' '.join([sources.EMAIL_SCOPE,sources.SCOPES['mail_read']])}
        if url==sources.USERINFO:return {'email':'fictional@example.test','verified_email':True}
        if url==sources.GMAIL+'/profile':return {'messagesTotal':2}
        if '/messages?' in url:return {'messages':[{'id':'abc123'}]}
        if '/messages/abc123?' in url:
            return {'payload':{'headers':[{'name':'Subject','value':'Aurora launch review'},{'name':'Date','value':'Tue, 10 Nov 2026 09:00:00 -0500'}],'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(b'Aurora review is November 17. Bring the onboarding prototype. Booking reference: QX7654.').decode().rstrip('=')}}}
        raise AssertionError('Unexpected Google destination')

def fresh_google(tmp_path,monkeypatch):
    monkeypatch.setattr(sources,'bundled_client',lambda:({'client_id':'fictional.apps.googleusercontent.com','client_secret':'fictional-desktop-identity'},''))
    transport=GoogleFixture();s=sources.LocalSources(key=b'k'*32,context_home=tmp_path,transport=transport)
    s.connection_store=EncryptedStore(tmp_path/'connections.enc',s.key)
    return s,transport

def test_fresh_google_pkce_callback_readonly_and_encrypted(tmp_path,monkeypatch):
    s,t=fresh_google(tmp_path,monkeypatch);r=s.connect_gmail();params=parse_qs(urlsplit(r['url']).query)
    assert params['code_challenge_method']==['S256'] and params['scope']==[' '.join([sources.EMAIL_SCOPE,sources.SCOPES['mail_read']])]
    assert 'mail.google.com' not in params['scope'][0] and 'gmail.send' not in params['scope'][0]
    callback=params['redirect_uri'][0]+'?'+urlencode({'state':params['state'][0],'code':'fictional-code'})
    with urlopen(callback) as result:assert result.status==200
    assert s.gmail_state()['account']=='fictional@example.test'
    s.google('/profile');assert s.gmail_state()['sign_in']=='connected'
    raw=(tmp_path/'connections.enc').read_bytes()
    assert b'FICTIONAL_ACCESS' not in raw and b'FICTIONAL_REFRESH' not in raw
    assert 'fictional-desktop-identity' not in str(s.gmail_state())
    with pytest.raises(Exception):urlopen(callback,timeout=1)

def test_setup_preferences_require_owner_and_config_does_not_contain_tokens(tmp_path,monkeypatch):
    s,_=fresh_google(tmp_path,monkeypatch);g=Gateway(s.connection_store,s);monkeypatch.setattr(clients,'ROOT',tmp_path/'app')
    (tmp_path/'app').mkdir();(tmp_path/'app/release.json').write_text('{}')
    with TestClient(owner_app(g,'owner'),base_url='http://127.0.0.1:8791') as c:
        h={'Authorization':'Bearer owner'}
        assert c.get('/onboarding.js').status_code==200
        assert c.post('/api/onboarding',json={'dismissed':True}).status_code==401
        assert c.post('/api/onboarding',json={'dismissed':'yes'},headers=h).status_code==400
        assert c.post('/api/onboarding',json={'gmail_skipped':True},headers=h).json()=={'gmail_skipped':True}
        r=c.post('/api/client-connect',json={'agent':'codex','approved':True,'lifetime':604800,'max_calls':1000},headers=h)
        assert r.status_code==200 and r.json()['installed']
        assert (tmp_path/'.codex/config.toml').exists() and 'pal_' not in (tmp_path/'.codex/config.toml').read_text()
        assert '--session-file' in r.json()['args']
        dashboard=c.post('/api/dashboard',json={},headers=h).json()
        assert dashboard['counts']=={'memories':0,'skills':0} and dashboard['onboarding']['gmail_skipped']
        assert dashboard['connections'][0]['used'] is False
