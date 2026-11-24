from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

from privacy_layer.core import Denied, Gateway, digest
from privacy_layer.phone_companion import PhoneCompanion
from privacy_layer.device_apps import ExampleApps
from privacy_layer.remote_clients import BridgeApp
from privacy_layer.workspace import Workspace


ORIGIN = 'https://bridge.example.net'


@pytest.fixture
def phone(bundle):
    g, source, now, _, _ = bundle
    source.data['memories','safe'] = {'text':'Cypress rehearsal is Thursday. Email: robin@example.test.','device_only':False}
    g.device_apps = ExampleApps()
    with g.store.transaction() as d:
        d['remote_bridge'] = {'origin':ORIGIN,'port':9874,'enabled':True}
    owner = PhoneCompanion(g)
    live = [g]
    client = TestClient(BridgeApp(lambda:live[0],9874),base_url=ORIGIN)
    return g, source, now, owner, live, client


def create(phone):
    _,source,_,owner,_,_ = phone
    return owner.owner('phone-create',{'selection':{'memories:safe':digest(source.data['memories','safe']['text'])},
                                      'approved':True})


def post(client,path,body,token=None):
    headers = {'Origin':ORIGIN}
    if token: headers['Authorization']='Bearer '+token
    return client.post('/phone/'+path,json=body,headers=headers)


def pair(phone):
    created = create(phone)
    code = urlsplit(created['url']).fragment.removeprefix('pair=')
    result = post(phone[-1],'pair',{'code':code})
    assert result.status_code == 200,result.text
    return created['id'], code, result.json()['session']


def test_phone_enforces_record_scope_and_mac_approval(phone):
    g,source,_,owner,live,client = phone
    identifier, code, session = pair(phone)
    assert post(client,'pair',{'code':code}).status_code == 403
    assert post(client,'status',{},session).json()['count'] == 1
    reply = post(client,'context',{'query':'Cypress'},session)
    assert reply.status_code == 200,reply.text
    value = reply.json()
    assert len(value['items']) == 1 and 'Thursday' in value['items'][0]['text']
    assert all(k not in reply.text for k in ('robin@example.test','HIDDEN_FINANCE','PRIVATE_MEDICAL'))
    assert set(value['items'][0]) == {'text','kind'}
    Workspace(g).create('email','Review follow-up',[identifier],{'recipients':'owner@example.test',
                        'subject':'Fictional subject','body':'Owner-only private body.'})
    actions = post(client,'actions',{},session)
    assert 'owner@example.test' not in actions.text and 'Owner-only' not in actions.text
    ref = actions.json()['actions'][0]['reference']
    assert post(client,'request',{'reference':ref},session).json()['status']=='pending'
    assert post(client,'request',{'reference':ref},session).json()['status']=='pending'
    listed = post(client,'actions',{},session).json()['actions']
    assert len(listed)==1 and listed[0]['status']=='pending'
    assert owner.owner('phone-state',{})['devices'][0]['state'] == 'paired'
    assert post(client,'disconnect',{},session).json() == {'closed':True}
    assert post(client,'context',{'query':'Cypress'},session).status_code == 401


def test_phone_pairing_one_use_even_concurrently_and_secrets_stay_volatile(phone):
    g,_,_,owner,_,client = phone
    created = create(phone)
    code = urlsplit(created['url']).fragment[5:]
    def redeem():
        return post(client,'pair',{'code':code})
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(lambda _:redeem(), range(2)))
    assert sorted(r.status_code for r in replies)==[200,403]
    session = next(r.json()['session'] for r in replies if r.status_code == 200)
    with g.store.transaction() as d:
        assert code not in str(d) and session not in str(d)
    assert created['id'] in str(owner.owner('phone-state',{}))
    assert client.post('/mcp',json={},headers={'Authorization':'Bearer '+session}).status_code == 401
    assert post(client,'status',{},code).status_code == 401


def test_phone_rejects_expired_link_lock_changed_scope_and_reopen(phone):
    g,_,now,owner,live,client = phone
    original = create(phone)
    now[0] += 301
    assert post(client,'pair',{'code':urlsplit(original['url']).fragment[5:]}).status_code==403
    identifier,_,session = pair(phone)
    assert owner.owner('phone-state',{})['devices'][0]['id'] == identifier
    with g.store.transaction() as state:
        state['remote_bridge']['enabled']=False
    assert post(client,'status',{},session).status_code==503
    with g.store.transaction() as state:
        state['remote_bridge']['enabled']=True
    live[0]=None
    assert post(client,'context',{'query':''},session).status_code==503
    live[0]=Gateway(g.store,g.sources,g.clock)
    assert post(client,'context',{'query':''},session).status_code==401
    assert PhoneCompanion(live[0]).owner('phone-state',{}) == {'devices':[]}


def test_phone_owner_can_revoke_and_private_selection_is_rejected(phone):
    g,s,_,owner,_,client = phone
    with pytest.raises(Denied):
        owner.owner('phone-create',{'selection':{'memories:m2':digest(s.data['memories','m2']['text'])}, 'approved':True})
    with pytest.raises(Denied):
        owner.owner('phone-create',{'selection':{'memories:safe':'changed'}, 'approved':True})
    identifier,_,session=pair(phone)
    owner.owner('phone-revoke',{'id':identifier})
    assert post(client,'status',{},session).status_code == 401


def test_phone_dedicated_host_and_browser_boundaries(phone):
    _,_,_,_,_,client = phone
    _,_,session=pair(phone)
    for asset in ('/phone','/phone/phone.js','/phone/phone.css'):
        r=client.get(asset);assert r.status_code==200
        assert r.headers['Referrer-Policy']=='no-referrer' and "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
        assert r.headers['Cache-Control']=='no-store'
        assert client.get(asset,headers={'Host':'wrong.example.net'}).status_code==403
    headers={'Authorization':'Bearer '+session}
    for path in ('/phone/workspace','/api/workspace-state','/phone/decide'):
        assert client.post(path,json={},headers=headers).status_code==404
    assert client.post('/phone/status',json={},headers=headers).status_code==403
    assert client.post('/phone/status',json={},headers={**headers,'Origin':'https://different.example.net'}).status_code==403
    assert client.post('/phone/status',json={},headers={**headers,'Origin':ORIGIN,'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.post('/phone/status?test=1',json={},headers={**headers,'Origin':ORIGIN}).status_code==400
    assert client.post('/phone/context',json={'query':'x'*16500},headers={**headers,'Origin':ORIGIN}).status_code==413


def test_phone_revocation_during_a_read_withholds_the_finished_result(phone,monkeypatch):
    g,_,_,owner,_,client = phone
    identifier,_,session = pair(phone)
    call = g.call
    def revoke_before_delivery(*args):
        result = call(*args)
        owner.owner('phone-revoke',{'id':identifier})
        return result
    monkeypatch.setattr(g,'call',revoke_before_delivery)
    response = post(client,'context',{'query':'Cypress'},session)
    assert response.status_code == 403
    assert 'Thursday' not in response.text and 'robin' not in response.text


def test_phone_access_is_tied_to_the_configured_tunnel_origin(phone):
    g,_,_,owner,live,client=phone
    _,code,session=pair(phone)
    with g.store.transaction() as state:
        state['remote_bridge']['origin']='https://second.example.net'
    newer=TestClient(BridgeApp(lambda:live[0],9874),base_url='https://second.example.net')
    for browser,origin in ((newer,'https://second.example.net'),(client,ORIGIN)):
        r=browser.post('/phone/context',json={'query':'Cypress'},headers={
            'Origin':origin,'Authorization':'Bearer '+session})
        assert r.status_code in (401,403) and 'Thursday' not in r.text
