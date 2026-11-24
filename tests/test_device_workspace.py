"""Exercise the actual gateway with a disposable vault and fake Mac destinations."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Event

import pytest
from starlette.testclient import TestClient

from privacy_layer.agent_memory import AgentMemory
from privacy_layer.core import Denied
from privacy_layer.data_view import api_settings, fetch_api
from privacy_layer.workspace import Workspace


class RecordingApps:
    def __init__(self):
        self.reads = []
        self.writes = []

    def sources(self, source):
        self.reads.append(source)
        if source == 'calendar':
            return [{'title':'Private meeting', 'recipients':['secret@example.org']}]
        return [{'title':'Private subject', 'recipient':'secret@example.org'}]

    def perform(self, kind, payload, attachment):
        self.writes.append((kind,payload,attachment))
        return True


@pytest.fixture
def setup(bundle):
    g,sources,now,_,_ = bundle
    g.device_apps = RecordingApps()
    def connect(name):
        gr = g.create(agent=name,purpose='Local workflow',views=[],approved=True,mode='automatic')
        AgentMemory(g).configure(gr['id'],records=[])
        return gr
    return g, Workspace(g), connect('codex'), connect('cursor'), now


def encoded(data):
    return base64.b64encode(data).decode()


def call(g, grant, tool, **kw):
    return g.call(grant['token'],tool,kw)


def test_private_mail_receipts_and_nontransferable_references(setup):
    g,w,first,second,_ = setup
    created=w.create('email','Send invoice',[first['id']],dict(recipients='secret@example.org',subject='A private invoice',
        body='Only the recipient sees these figures.',attachment={'name':'invoice.pdf','data':encoded(b'secret-pdf')}))
    row=w.state()['actions'][0]
    assert 'data' not in row['payload']['attachment']
    view=call(g,first,'list_private_actions')['actions'][0]
    assert call(g,second,'list_private_actions')['actions']==[]
    with pytest.raises(Denied):
        call(g,second,'private_action_status',reference=view['reference'])
    result=call(g,first,'request_private_action',reference=view['reference'])
    assert result['status']=='pending' and g.device_apps.writes==[]
    with pytest.raises(Denied):
        w.decide(created['id'],'different fingerprint',True)
    assert w.decide(created['id'],row['fingerprint'],True)=={'status':'sent'}
    assert g.device_apps.writes==[('email',{'recipients':['secret@example.org'],'subject':'A private invoice','body':'Only the recipient sees these figures.'},{'name':'invoice.pdf','bytes':b'secret-pdf'})]
    assert call(g,first,'private_action_status',reference=view['reference'])['status']=='sent'
    receipts=json.dumps(w.state()['receipts'])
    for secret in ('secret@example.org','invoice.pdf','A private invoice','Only the recipient','secret-pdf'):
        assert secret not in receipts


@pytest.mark.parametrize('source',['mail','calendar'])
def test_agent_can_resolve_local_recipient_once_only_with_permission(setup,source):
    g,w,first,_,_=setup
    kw=dict(source=source,subject='Following up',body='Can we meet next week?',request_key='followup_123')
    with pytest.raises(Denied):
        call(g,first,'prepare_private_followup',**kw)
    assert not g.device_apps.reads
    with g.store.transaction() as d:
        d['grants'][first['id']]['device_permissions']={source:True}
    result=call(g,first,'prepare_private_followup',**kw)
    assert 'secret@example.org' not in json.dumps(result)
    assert call(g,first,'prepare_private_followup',**kw)==result
    assert g.device_apps.reads==[source]
    with pytest.raises(Denied):
        call(g,first,'prepare_private_followup',**{**kw,'body':'A different instruction'})
    row=w.state()['actions'][0]
    assert row['payload']['recipients']==['secret@example.org']
    w.decide(row['id'],row['fingerprint'],True)
    w.remove(row['id'])
    with pytest.raises(Denied):
        call(g,first,'prepare_private_followup',**kw)
    assert len(g.device_apps.writes)==1 and g.device_apps.reads==[source]


def calendar_request(g,w,agent):
    w.create('event','Schedule review',[agent['id']],dict(title='Private review',calendar='Work',start='2026-11-25T12:00:00-05:00',end='2026-11-25T13:00:00-05:00'))
    row=w.state()['actions'][0]
    call(g,agent,'request_private_action',reference=row['handles'][agent['id']])
    return row['id'],row['fingerprint']


@pytest.mark.parametrize('cause',['revoke','edit','time','decline'])
def test_changed_policy_or_decline_blocks_queued_write(setup,cause):
    g,w,agent,_,now=setup
    key,fingerprint=calendar_request(g,w,agent)
    if cause=='revoke': g.revoke(agent['id'])
    if cause=='edit': AgentMemory(g).configure(agent['id'],records=[])
    if cause=='time': now[0]+=3600
    if cause=='decline': assert w.decide(key,fingerprint,False)['status']=='declined'
    with pytest.raises(Denied):
        w.decide(key,fingerprint,True)
    assert g.device_apps.writes==[]


def test_concurrent_approval_or_uncertain_submission_never_repeats(setup):
    g,w,agent,_,_=setup
    key,fingerprint=calendar_request(g,w,agent)
    started,release=Event(),Event()
    def ambiguous(kind,payload,attachment):
        g.device_apps.writes.append((kind,payload['start']))
        started.set()
        assert release.wait(4)
        raise RuntimeError('indeterminate')
    g.device_apps.perform=ambiguous
    with ThreadPoolExecutor() as pool:
        first=pool.submit(w.decide,key,fingerprint,True)
        assert started.wait(4)
        with pytest.raises(Denied):
            w.decide(key,fingerprint,True)
        release.set()
        assert first.result()=={'status':'unconfirmed'}
    with pytest.raises(Denied):
        w.decide(key,fingerprint,True)
    assert g.device_apps.writes==[('event','2026-11-25T17:00:00+00:00')]


@pytest.mark.parametrize('form',['json','csv','sqlite'])
def test_column_projection_and_per_agent_tokens(setup, form):
    g,w,first,second,_=setup
    r={'stage':'Pilot','email':'secret@example.org','fullName':'Rita Smith','note':'Rita Smith is attending','apiKey':'secret_value','private_note':'Hidden terms'}
    if form=='json': raw=json.dumps([r]).encode()
    elif form=='csv': raw=(','.join(r)+'\n'+','.join(r.values())).encode()
    else:
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE plan (stage, email, fullName, note, apiKey, private_note)')
            db.execute('INSERT INTO plan VALUES (?,?,?,?,?,?)',tuple(r.values()))
            raw=db.serialize()
    fields=['stage','email','fullName','note','apiKey']
    w.create('data','Customer status',[first['id'],second['id']],dict(name='snapshot.'+form,data=encoded(raw),table='plan' if form=='sqlite' else '',fields=fields))
    a=w.state()['actions'][0]
    with g.store.transaction() as d:
        assert 'Hidden terms' not in str(d['device_actions'][a['id']]['payload'])
    receipts=[]
    for agent in (first,second):
        ref=a['handles'][agent['id']]
        out=call(g,agent,'read_private_fields',reference=ref)
        v=out['rows'][0]
        assert v[0]=='Pilot' and v[1].startswith('[email-') and v[2] in v[3] and v[4]=='[withheld]'
        assert all(k not in json.dumps(out) for k in ('Rita Smith','secret_value','Hidden terms','secret@example.org'))
        assert call(g,agent,'read_private_fields',reference=ref)==out
        receipts.append(v)
    assert receipts[0][1:3]!=receipts[1][1:3]


def test_protected_phrase_straddling_display_limit_is_filtered_before_clipping(setup):
    g,w,agent,_,_=setup
    phrase='PRIVATE_CREDENTIAL_CANARY'
    data={'text':'a '*195+phrase}
    w.create('data','Snippet',[agent['id']],dict(name='file.json',fields=['text'],table='',data=encoded(json.dumps(data).encode())))
    ref=w.state()['actions'][0]['handles'][agent['id']]
    assert 'PRIVATE_' not in str(call(g,agent,'read_private_fields',reference=ref))


def test_live_api_uses_fixed_endpoint_and_filters_new_columns_each_read(setup,monkeypatch):
    g,w,agent,other,_=setup
    requests=[]
    def read(settings):
        requests.append(settings['url'])
        assert settings['credential']=='local_only_token'
        return [{'stage':'Current '+str(len(requests)),'new_secret':'raw_value','email':'secret@example.org'}],False
    monkeypatch.setattr('privacy_layer.workspace.fetch_api',read)
    values=dict(url='https://example.org/ledger',credential='local_only_token',array_key='',fields=['stage'])
    w.create('api','Current stage',[agent['id']],values)
    row=w.state()['actions'][0]
    assert 'credential' not in row['payload']
    ref=row['handles'][agent['id']]
    with pytest.raises(Denied):
        call(g,other,'read_private_fields',reference=ref)
    with pytest.raises(Denied):
        call(g,agent,'read_private_fields',reference=ref,url='https://elsewhere.example')
    out=call(g,agent,'read_private_fields',reference=ref)
    assert out['rows']==[['Current 2']] and requests==[values['url']]*2
    assert all(s not in json.dumps(w.state()['receipts']) for s in ('local_only_token','raw_value','secret@example.org',values['url']))
    for url in ('file:///etc/hosts','http://example.org','https://person:secret@example.org','https://example.org/#hidden'):
        with pytest.raises(Denied):
            api_settings(url,'','')


def test_real_json_api_adapter_sends_only_to_exact_url(monkeypatch):
    from io import BytesIO
    seen=[]
    class Opener:
        def open(self,req,timeout):
            seen.append((req.get_method(),req.full_url,req.get_header('Authorization')))
            return BytesIO(b'{"items":[{"stage":"Live"}]}')
    def opener(*handlers):
        assert handlers[1].redirect_request(None) is None
        return Opener()
    monkeypatch.setattr('privacy_layer.data_view.build_opener',opener)
    result=fetch_api(api_settings('http://localhost:4040/api','test_fixture','items'))
    assert result==([{'stage':'Live'}],False)
    assert seen==[('GET','http://localhost:4040/api','Bearer test_fixture')]


def test_example_owner_routes_are_isolated(tmp_path):
    from pathlib import Path
    from privacy_layer.safe_test import SafeTest
    safe=SafeTest(Path(__file__).resolve().parents[1],tmp_path/'sample',profile_home=tmp_path/'profile')
    client=TestClient(safe.app('demo-owner',8912),base_url='http://127.0.0.1:8912')
    def post(action,body=None,token='demo-owner'):
        return client.post('/api/'+action,json=body or {},headers={'Authorization':'Bearer '+token})
    assert post('workspace-state',token='wrong').status_code==401
    assert post('workspace-create').status_code==400
    assert post('workspace-api-fields',{'url':'https://example.org','credential':'','array_key':''}).status_code==400
    state=post('workspace-state').json()
    email=next(a for a in state['actions'] if a['kind']=='email')
    assert post('workspace-decide',dict(identifier=email['id'],fingerprint=email['fingerprint'],approve=True)).json()=={'status':'sent'}
    response=post('workspace-try',dict(identifier=email['id'],agent=email['applicant'],tool='private_action_status')).json()
    assert response['simulated'] and 'mara@example.com' not in str(response)
    assert safe.personal is None


def test_live_loopback_projection_changes_and_rejects_redirects(setup):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    g,w,agent,_,_=setup
    hits=[]
    class Endpoint(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.path,self.headers.get('Authorization')))
            if self.path=='/redirect':
                self.send_response(302)
                self.send_header('Location','/different')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'list':[{'stage':len(hits),'secret':'Hidden terms'}]}).encode())
        def log_message(self,*args): pass
    try:
        server=ThreadingHTTPServer(('127.0.0.1',0),Endpoint)
    except PermissionError:
        pytest.skip('Local HTTP sockets are disabled in this test environment')
    worker=Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        origin='http://127.0.0.1:'+str(server.server_port)
        w.create('api','Customer stage',[agent['id']],dict(url=origin+'/records',credential='fictional-token',array_key='list',fields=['stage']))
        ref=w.state()['actions'][0]['handles'][agent['id']]
        out=call(g,agent,'read_private_fields',reference=ref)
        assert out['rows']==[['2']] and 'Hidden terms' not in json.dumps(out)
        with pytest.raises(Denied): fetch_api(api_settings(origin+'/redirect','fictional-token','list'))
        assert hits==[('/records','Bearer fictional-token')]*2+[('/redirect','Bearer fictional-token')]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
