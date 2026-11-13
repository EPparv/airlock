"""Real permission/storage/provider code; Ollama HTTP is explicitly mocked."""
import asyncio
import json
import httpx
import pytest

from privacy_layer.core import Denied
from privacy_layer.founder_demo import FounderDemo, MEETING, FINANCE, RESTRICTED_VALUE
from privacy_layer.local_provider import LocalProvider, LOCAL_DESTINATION, DEFAULT_LOCAL_MODEL, local_model_name

INFO={'details':{'format':'gguf'},'capabilities':['completion'],
      'model_info':{'general.architecture':'qwen3','qwen3.context_length':32768}}

@pytest.fixture
def local(bundle,monkeypatch):
    monkeypatch.delenv('AIRLOCK_DEMO_LOCAL_MODEL',raising=False)
    monkeypatch.setattr('privacy_layer.founder_demo.NearProvider',lambda:pytest.fail('Local inference must never fall back to NEAR'))
    sent=[];behavior={}
    def handle(request):
        sent.append(request)
        if request.url.path=='/api/show':
            if behavior.get('hook'):behavior['hook']()
            return httpx.Response(200,json=behavior.get('info',INFO))
        assert str(request.url)==LOCAL_DESTINATION
        if behavior.get('after_dispatch'):behavior['after_dispatch']()
        if behavior.get('timeout'):raise httpx.ReadTimeout('fictional private response',request=request)
        if behavior.get('status'):return httpx.Response(behavior['status'],headers={'Location':'https://cloud.invalid'},text=RESTRICTED_VALUE)
        return httpx.Response(200,json=behavior.get('answer',{'model':DEFAULT_LOCAL_MODEL,'done':True,'done_reason':'stop','message':{'content':'Mocked local draft: Hi Maya, can we meet Thursday?'}}))
    provider=LocalProvider(httpx.MockTransport(handle))
    d=FounderDemo(bundle[0],local_provider=provider);d.reset();d.grant()
    return d,sent,behavior,bundle[2]


def send(d,p):return asyncio.run(d.send(p['approval_id'],True,p['sha256']))


def test_local_prompt_bytes_match_review_and_restricted_value_never_leaves(local):
    d,sent,_,_=local;p=d.review([MEETING],'local')
    assert p['destination']==LOCAL_DESTINATION and p['model']==DEFAULT_LOCAL_MODEL
    assert not sent
    result=send(d,p)
    assert result['mode']=='local' and result['inference_calls']==1 and result['cloud_inference_calls']==0
    assert [r.url.path for r in sent]==['/api/show','/api/chat']
    assert sent[-1].content==p['payload'].encode()
    assert 'think' not in json.loads(p['payload'])  # plain instruction models may not support this option
    assert all(RESTRICTED_VALUE.encode() not in r.content for r in sent)
    assert all(r.url.host=='127.0.0.1' and r.url.port==11434 for r in sent)
    assert 'not TEE-attested' in result['checks']['model']


def test_restricted_local_request_calls_no_provider(local):
    d,sent,_,_=local
    assert d.review([MEETING,FINANCE],'local')['blocked']
    assert sent==[]


@pytest.mark.parametrize('change',['revoke','expiry','model','source','during_preflight'])
def test_local_permissions_rechecked_before_generation(local,monkeypatch,change):
    d,sent,behavior,now=local;p=d.review([MEETING],'local')
    if change=='revoke':d.revoke()
    elif change=='expiry':now[0]+=601
    elif change=='model':monkeypatch.setenv('AIRLOCK_DEMO_LOCAL_MODEL','gemma3:4b')
    elif change=='source':
        with d.store.transaction() as data:data['founder_demo']['records'][MEETING]['never_share']=True
    else:behavior['hook']=d.revoke
    with pytest.raises(Denied):send(d,p)
    assert not [r for r in sent if r.url.path=='/api/chat']


@pytest.mark.parametrize('info',[
    {**INFO,'remote_host':'https://remote.invalid'},
    {**INFO,'remote_model':'remote-alias'},
    {**INFO,'details':{'format':'remote'}},
    {**INFO,'capabilities':['embedding']},
    {**INFO,'model_info':{'general.architecture':'qwen3','qwen3.context_length':512}},
    {**INFO,'thinking':{'values':[True]}},
])
def test_remote_or_incompatible_weights_block_before_content(local,info):
    d,sent,behavior,_=local;behavior['info']=info
    with pytest.raises(Denied):send(d,d.review([MEETING],'local'))
    assert len(sent)==1 and sent[0].url.path=='/api/show'
    assert b'Maya' not in sent[0].content


@pytest.mark.parametrize('failure',[302,401,500,'timeout','truncated','model','empty'])
def test_local_errors_do_not_fall_back_or_expose_response(local,failure,caplog):
    d,sent,behavior,_=local
    if isinstance(failure,int):behavior['status']=failure
    elif failure=='timeout':behavior['timeout']=True
    else:
        behavior['answer']={'model':DEFAULT_LOCAL_MODEL,'done':True,'message':{'content':'Sample'}}
        if failure=='truncated':behavior['answer']['done_reason']='length'
        elif failure=='model':behavior['answer']['model']='remote'
        else:behavior['answer']['message']['content']=''
    p=d.review([MEETING],'local')
    with pytest.raises(Denied) as error:send(d,p)
    assert RESTRICTED_VALUE not in str(error.value)+caplog.text
    assert len(sent)==2 and d.state()['result'] is None
    with pytest.raises(Denied):send(d,p)
    assert len(sent)==2


def test_connection_check_sends_only_model_metadata(local):
    d,sent,_,_=local
    assert asyncio.run(d.check('local'))['ready']
    assert len(sent)==1 and json.loads(sent[0].content)=={'model':DEFAULT_LOCAL_MODEL}
    assert d.state()['grant'] is not None


def test_revoke_during_generation_withholds_response(local):
    d,sent,behavior,_=local
    # Change expiry without replacing pending state, testing the final recheck.
    def expire():
        with d.store.transaction() as data:data['founder_demo']['grant']['revoked']=True
    behavior['after_dispatch']=expire
    with pytest.raises(Denied,match='already reached'):
        send(d,d.review([MEETING],'local'))
    assert len(sent)==2 and d.state()['result'] is None


def test_large_context_is_rejected_without_model_request(local):
    d,sent,_,_=local
    with d.store.transaction() as data:data['founder_demo']['records'][MEETING]['text']='Example meeting. '*500
    with pytest.raises(Denied,match='context exceeds'):
        send(d,d.review([MEETING],'local'))
    assert sent==[]


def test_local_client_ignores_proxy_and_disallows_redirects(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY','http://proxy.invalid:8080')
    client=LocalProvider().client()
    assert client.trust_env is False and client.follow_redirects is False
    asyncio.run(client.aclose())


@pytest.mark.parametrize('model',['gpt-cloud:latest','https://cloud.invalid/x','bad model'])
def test_cloud_model_names_blocked(monkeypatch,model):
    monkeypatch.setenv('AIRLOCK_DEMO_LOCAL_MODEL',model)
    with pytest.raises(Denied):local_model_name()
