import json
from pathlib import Path
import re

import httpx
import pytest
from starlette.testclient import TestClient

from privacy_layer import prompt_gateway as pg
from privacy_layer.server import owner_app
from privacy_layer.safe_test import SafeTest

URL = 'http://127.0.0.1:8791'
TOKEN = 'owner-secret'
OWNER = {'Authorization':'Bearer '+TOKEN}
CLOUD_KEY = 'sk-ownerOnlyPrivateKey_0987654321'


def auth(token):
    return {'Authorization':'Bearer '+token}


def chat(text='Write a poem.', **kwargs):
    return dict(model='airlock',messages=[{'role':'user','content':text}],**kwargs)


def reply(content='A short poem.',finish='stop'):
    return {'choices':[{'message':{'role':'assistant','content':content,'reasoning':'provider only'},
                       'finish_reason':finish}],'system_fingerprint':'private provider info'}


def weights(remote=False):
    return dict(remote_host='cloud.example' if remote else '',details={'format':'gguf'},
                model_info={'general.architecture':'llama','llama.context_length':8192},
                capabilities=['completion'])


@pytest.fixture
def proxy(bundle):
    gateway = bundle[0]
    app = owner_app(gateway,TOKEN)
    captured = []

    def handler(req):
        captured.append((str(req.url),dict(req.headers),json.loads(req.content)))
        if req.url.path=='/api/show':
            return httpx.Response(200,json=weights())
        return httpx.Response(200,json=reply())

    model = app.state.prompt_gateway
    model.transport = httpx.MockTransport(handler)
    with TestClient(app,base_url=URL) as c:
        yield c, model, captured


def create(c, **overrides):
    data = dict(name='Local notes', provider='ollama', model='qwen3:4b-instruct', approved=True)
    data.update(overrides)
    result = c.post('/api/prompt-create',headers=OWNER,json=data)
    result.raise_for_status()
    return result.json()


def test_real_routes_screen_all_roles_before_inference(proxy,bundle):
    c, model, captured = proxy
    config = create(c)
    headers = auth(config['token'])
    assert config['base_url']==URL+'/v1' and config['model']=='airlock'
    assert c.get('/v1/models',headers=headers).json()['data'][0]['id']=='airlock'
    messages=[
        {'role':'system','content':'Meet Astrid Malik. Call (415)555-1234.'},
        {'role':'developer','content':'Name: Astrid Malik. Contact dev@corp.example.'},
        {'role':'assistant','content':'Use PRIVATE_CREDENTIAL_CANARY on Friday.'},
        {'role':'user','content':[{'type':'text','text':'Write to dev@'},{'type':'text','text':'corp.example.'}]},
    ]
    result=c.post('/v1/chat/completions',headers=headers,json=dict(model='airlock',messages=messages))
    assert result.status_code==200, result.text
    assert result.json()['choices'][0]['message']=={'role':'assistant','content':'A short poem.'}
    assert 'provider only' not in result.text and 'system_fingerprint' not in result.text
    assert [r[0] for r in captured]==[pg.LOCAL_BASE+'/api/show',pg.DESTINATIONS['ollama']]
    assert set(captured[0][2])=={'model'}
    assert 'authorization' not in captured[1][1]
    outbound=json.dumps(captured[1][2])
    for private in ('dev@','Astrid','Malik','555-1234','PRIVATE_CREDENTIAL_CANARY'):
        assert private not in outbound
    for kind in ('person','email','phone'):
        assert f'[{kind}-' in outbound
    email = re.search(r'\[email-[a-p]+\]',outbound).group()
    assert outbound.count(email)==2
    other=create(c)
    c.post('/v1/chat/completions',headers=auth(other['token']),json=chat('Reply to dev@corp.example.'))
    assert email not in str(captured[-1][2])
    with bundle[0].store.transaction() as d:
        assert 'Astrid' not in str(d) and 'dev@corp' not in str(d)
    assert config['token'] not in c.post('/api/prompt-status',headers=OWNER,json={}).text


@pytest.mark.parametrize('change',[
    {'tools':[]},{'response_format':{}},{'user':'dev@corp.example'}, {'model':'different'},
    {'logprobs':True},{'stream':1},{'temperature':True},{'max_tokens':0},
    {'messages':[{'role':'tool','content':'private'}]},
    {'messages':[{'role':'user','content':'hi','name':'dev@corp.example'}]},
    {'messages':[{'role':'assistant','content':'ok','tool_calls':[]}]},
    {'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'private'}}]}]},
    {'messages':[{'role':'user','content':'-----BEGIN PRIVATE KEY-----\nprivate payload'}]},
])
def test_unsupported_payloads_stop_before_any_request(proxy,change):
    c,_,captured=proxy
    result=c.post('/v1/chat/completions',headers=auth(create(c)['token']),json={**chat(),**change})
    assert result.status_code==400 and captured==[]


def test_only_local_native_model_token_is_accepted(proxy,bundle):
    c,_,captured=proxy
    config=create(c)
    for headers in (OWNER,auth(bundle[-1]()['token']),{}, {**auth(config['token']),'Origin':URL},
                    {**auth(config['token']),'Host':'external.example'}):
        assert c.post('/v1/chat/completions',headers=headers,json=chat()).status_code in (401,403)
    assert c.post('/api/prompt-status',headers=auth(config['token']),json={}).status_code==401
    assert c.post('/api/prompt-revoke',headers=OWNER,json={'id':config['id']}).json()=={'revoked':True}
    assert c.get('/v1/models',headers=auth(config['token'])).status_code==401
    assert captured==[]


def test_allowlisted_cloud_and_buffered_stream(proxy):
    c,_,captured=proxy
    setup={'name':'writer','provider':'openai','model':'gpt-4.1','api_key':CLOUD_KEY,'approved':True}
    for change in ({'approved':False},{'base_url':'https://example.com'},{'provider':'custom'},
                   {'api_key':'bad'},{'model':'https://example.com'}):
        assert c.post('/api/prompt-create',headers=OWNER,json={**setup,**change}).status_code==400
    config=create(c,**setup)
    assert CLOUD_KEY not in str(config)
    result=c.post('/v1/chat/completions',headers={**auth(config['token']),'X-Private-Header':'extra secret'},
                  json=chat('Write to Jane at info@office.example.',stream=True,max_tokens=91))
    assert result.status_code==200 and result.headers['content-type'].startswith('text/event-stream')
    assert result.text.endswith('data: [DONE]\n\n') and 'A short poem.' in result.text
    assert len(captured)==1
    url,headers,data=captured[0]
    assert url==pg.DESTINATIONS['openai'] and headers['authorization']=='Bearer '+CLOUD_KEY
    assert 'x-private-header' not in headers and data['store'] is False and data['max_completion_tokens']==91
    assert 'info@office' not in str(data) and data['stream'] is False
    assert CLOUD_KEY not in c.post('/api/prompt-status',headers=OWNER,json={}).text


def test_no_redirect_or_fallback_no_provider_error_echo(proxy):
    c,model,captured=proxy
    config=create(c,provider='openai',model='gpt-4.1',api_key=CLOUD_KEY)
    seen=[]
    def redirect(req):
        seen.append(str(req.url))
        return httpx.Response(307,headers={'location':'https://example.org/elsewhere'},text=CLOUD_KEY)
    model.transport=httpx.MockTransport(redirect)
    r=c.post('/v1/chat/completions',headers=auth(config['token']),json=chat())
    assert r.status_code==502 and CLOUD_KEY not in r.text and seen==[pg.DESTINATIONS['openai']]
    config=create(c)
    seen.clear()
    def remote(req):
        seen.append(str(req.url))
        return httpx.Response(200,json=weights(remote=True))
    model.transport=httpx.MockTransport(remote)
    assert c.post('/v1/chat/completions',headers=auth(config['token']),json=chat()).status_code==502
    assert seen==[pg.LOCAL_BASE+'/api/show']


def test_revocation_during_preflight_and_inflight(proxy):
    c,model,_=proxy
    for stage in ('before','after'):
        config=create(c)
        seen=[]
        def upstream(req):
            seen.append(req.url.path)
            preflight=req.url.path=='/api/show'
            if preflight==(stage=='before'):
                model.owner('prompt-revoke',{'id':config['id']})
            return httpx.Response(200,json=weights() if preflight else reply('Withhold on revocation'))
        model.transport=httpx.MockTransport(upstream)
        r=c.post('/v1/chat/completions',headers=auth(config['token']),json=chat())
        assert r.status_code==401 and 'Withhold on revocation' not in r.text
        assert ('/v1/chat/completions' in seen)==(stage=='after')


def test_budget_expiry_lock_and_restart(proxy,bundle,monkeypatch):
    c,model,_=proxy
    monkeypatch.setattr(pg,'MAX_CALLS',1)
    entry=create(c)
    assert c.post('/v1/chat/completions',headers=auth(entry['token']),json=chat()).status_code==200
    assert c.post('/v1/chat/completions',headers=auth(entry['token']),json=chat()).status_code==429
    entry=create(c);bundle[2][0]+=pg.TTL
    assert c.get('/v1/models',headers=auth(entry['token'])).status_code==401
    assert c.post('/api/prompt-status',headers=OWNER,json={}).json()['clients']==[]
    entry=create(c)
    with TestClient(owner_app(bundle[0],TOKEN),base_url=URL) as fresh:
        assert fresh.get('/v1/models',headers=auth(entry['token'])).status_code==401
    model.close()
    assert c.get('/v1/models',headers=auth(entry['token'])).status_code==401
    assert c.post('/api/prompt-create',headers=OWNER,json={}).status_code==400


def test_text_only_errors_and_duplicate_fields(proxy):
    c,_,captured=proxy
    config=create(c)
    headers={**auth(config['token']),'Content-Type':'application/json'}
    for data in (b'{"model":"airlock","model":"airlock"}',b'\xff',b'{'):
        assert c.post('/v1/chat/completions',headers=headers,content=data).status_code==400
    assert c.post('/v1/chat/completions',headers=headers,content=b'a'*(pg.BODY_LIMIT+1)).status_code==413
    assert c.post('/v1/chat/completions',headers=auth(config['token']),content=b'plain').status_code==415
    assert not captured


def test_safe_fixture_cannot_issue_model_credentials(tmp_path):
    safe=SafeTest(Path(__file__).resolve().parents[1],tmp_path,profile_home=tmp_path/'example-home')
    with TestClient(safe.app(TOKEN,8791),base_url=URL) as c:
        assert c.post('/api/prompt-create',headers=OWNER,json={'approved':True}).status_code==400
        assert c.get('/v1/models',headers=OWNER).status_code==404


def test_lowercase_and_quoted_secrets_across_turns(proxy):
    c, model, captured = proxy
    entry=create(c)
    body=chat()
    body['messages']=[
        {'role':'assistant','content':'Previously work with lee west and iris-secret.'},
        {'role':'user','content':'My name is lee west. Details: {"password": "iris-secret"}.'},
    ]
    r=c.post('/v1/chat/completions',headers=auth(entry['token']),json=body)
    assert r.status_code==200
    outbound=json.dumps(captured[-1][2])
    assert 'lee west' not in outbound and 'iris-secret' not in outbound
    assert re.search(r'\[person-[a-p]+\]',outbound)


def test_official_sdk_reads_models_text_and_stream(proxy):
    # The desktop package does not need an SDK to serve HTTP. Exercise the
    # official client where available, in addition to raw wire-format assertions.
    sdk=pytest.importorskip('openai')
    c, _, _ = proxy
    config=create(c)
    client=sdk.OpenAI(base_url=config['base_url'],api_key=config['token'],http_client=c,max_retries=0)
    assert client.models.list().data[0].id=='airlock'
    messages=[{'role':'user','content':'Write a short poem.'}]
    completion=client.chat.completions.create(model='airlock',messages=messages)
    assert completion.choices[0].message.content=='A short poem.'
    stream=client.chat.completions.create(model='airlock',messages=messages,stream=True)
    assert ''.join((r.choices[0].delta.content or '') for r in stream)=='A short poem.'


def test_closing_personal_workspace_clears_live_model_keys(tmp_path,monkeypatch):
    from privacy_layer import sources
    safe=SafeTest(Path(__file__).resolve().parents[1],tmp_path,profile_home=tmp_path/'example-home')
    class LocalSources:
        key=b'p'*32
        context_home=tmp_path
        def __init__(self,**kw): pass
        def library(self): return []
        def protected(self): return []
    monkeypatch.setattr(sources,'LocalSources',LocalSources)
    with TestClient(safe.app(TOKEN,8791),base_url=URL) as c:
        start=c.post('/api/open-personal',headers=OWNER,json={'approved':True}).json()
        personal=auth(start['url'].split('#')[1])
        config=c.post('/api/prompt-create',headers=personal,json={
            'approved':True,'provider':'ollama','model':'qwen3:4b-instruct','name':'From SDK'
        }).json()
        prompt_auth=auth(config['token'])
        assert c.get('/v1/models',headers=prompt_auth).status_code==200
        old_gateway=safe.personal_app.state.prompt_gateway
        c.post('/api/close-personal',headers=OWNER,json={}).raise_for_status()
        assert old_gateway.closed and old_gateway.clients=={}
        assert c.get('/v1/models',headers=prompt_auth).status_code==404
        c.post('/api/open-personal',headers=OWNER,json={'approved':True}).raise_for_status()
        assert c.get('/v1/models',headers=prompt_auth).status_code==401


def test_official_responses_sdk_text_list_instructions_and_stream(proxy):
    sdk=pytest.importorskip('openai')
    c, _, captured = proxy
    config=create(c)
    client=sdk.OpenAI(base_url=config['base_url'],api_key=config['token'],http_client=c,max_retries=0)
    response=client.responses.create(model='airlock',input='Contact me at poem@corp.example.',
                                     instructions='Name: Rosa West.',max_output_tokens=45,store=False)
    assert response.output_text=='A short poem.' and response.store is False
    assert response.status=='completed' and response.output[0].role=='assistant'
    assert 'poem@corp.example' not in str(captured[-1][2]) and 'Rosa' not in str(captured[-1][2])
    assert 'Rosa' not in response.model_dump_json() and captured[-1][2]['max_tokens']==45
    messages=[
        {'role':'user','content':[{'type':'input_text','text':'Invite Rosa West for lunch.'}]},
        {'role':'assistant','content':[{'type':'output_text','text':'Email poem@corp.example'}]},
        {'type':'message','role':'user','content':'Please continue.'},
    ]
    with client.responses.stream(model='airlock',input=messages) as stream:
        events=list(stream)
        assert [e.delta for e in events if e.type=='response.output_text.delta']==['A short poem.']
        assert stream.get_final_response().output_text=='A short poem.'
    assert [m['role'] for m in captured[-1][2]['messages']]==['user','assistant','user']
    assert 'Rosa' not in str(captured[-1][2]) and 'poem@corp.example' not in str(captured[-1][2])


@pytest.mark.parametrize('extra',[
    {'tools':[]},{'store':True},{'previous_response_id':'resp_123'}, {'conversation':'conv_123'},
    {'background':True},{'reasoning':{'effort':'low'}}, {'metadata':{'raw':'private'}},
    {'input':[]},{'instructions':{'text':'unsafe'}},
    {'input':[{'type':'function_call_output','call_id':'anything','output':'hidden'}]},
    {'input':[{'role':'user','content':[{'type':'input_file','file_url':'https://raw.example'}]}]},
    {'input':[{'role':'user','content':'hi','name':'jane@corp.example'}]},
    {'input':[{'role':'user','content':[{'type':'input_text','text':'hi','metadata':{}}]}]},
])
def test_responses_reject_unsupported_shapes_without_contacting_upstream(proxy,extra):
    c, _, captured = proxy
    config=create(c)
    response=c.post('/v1/responses',headers=auth(config['token']),json={'model':'airlock','input':'hi',**extra})
    assert response.status_code==400 and captured==[]
    assert c.get('/v1/responses/resp_123',headers=auth(config['token'])).status_code==404
