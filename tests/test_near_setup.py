import json
import asyncio
import functools
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import httpx
import pytest
from starlette.testclient import TestClient

from privacy_layer.core import Denied
from privacy_layer.near_setup import NearSetup, PROBE_PROMPT
from privacy_layer.server import owner_app
from privacy_layer.safe_test import SafeTest


def async_test(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def evidence():
    return NS(gateway=NS(tls_binding=NS(kind='attested'), tcb_status='UpToDate', advisory_ids=[]),
              models=[NS(tcb_status='UpToDate', advisory_ids=[], gpu_evidence='verified')])


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(NearSetup, 'sdk_status', staticmethod(lambda: {'ready':True,'version':'0.3.0','required':'0.3.0','message':'installed'}))
    s=NearSetup(clock=lambda:100)
    s.configure('sk-fictional-test-only')
    return s


def factory_for(*, unsafe=False, fail=False, hook=None):
    @asynccontextmanager
    async def factory(key, *, settings=None, observer=None):
        class Client:
            async def verify(self, model):
                if observer:
                    observer('gateway', NS(app_compose='{"name":"fixture gateway"}'))
                    observer('model', NS(app_compose='{"name":"fixture model"}'))
                if hook: hook()
                if fail: raise RuntimeError('sk-fictional-test-only must never echo')
                value=evidence()
                if unsafe: value.models=[]
                return value
            async def send(self, request):
                assert settings and settings['model_pins'] and settings['gateway_pins']
                await request.extensions['trace']('http11.send_request_headers.started',{})
                payload=json.loads(request.content)
                assert payload['messages'][0]['content']==PROBE_PROMPT
                return httpx.Response(200,request=request,json={'id':'fictional-proof','model':payload['model'],
                    'choices':[{'message':{'content':'AIRLOCK_NEAR_OK'}}]})
            async def verify_response(self, identifier):
                return NS(signature_kind='provider_tee',attestations=[NS()])
        yield Client()
    return factory


@async_test
async def test_discovery_never_approves_and_probe_needs_explicit_consent(setup):
    setup.client_factory=factory_for()
    state=await setup.discover()
    assert not state['ready'] and not state['deployment_approved']
    assert 'sk-fictional' not in json.dumps(state)
    review=state['deployment_review']
    with pytest.raises(Denied): setup.approve(review['id'], False)
    with pytest.raises(Denied): setup.approve('wrong', True)
    setup.approve(review['id'], True)
    with pytest.raises(Denied): await setup.probe(False)
    result=await setup.probe(True)
    assert result['last_test']['passed']
    assert result['last_test']['checks']['response_signature']=='passed (model TEE)'
    setup.clear()
    assert not setup.status()['ready'] and setup.status()['last_test'] is None


@async_test
@pytest.mark.parametrize('kwargs',[{'unsafe':True},{'fail':True}])
async def test_failed_attestation_never_creates_a_review(setup,kwargs):
    setup.client_factory=factory_for(**kwargs)
    with pytest.raises(Denied) as exc: await setup.discover()
    assert 'sk-fictional' not in str(exc.value)
    assert setup.pending is None and not setup.status()['ready']


@async_test
async def test_clear_during_preflight_stops_dispatch(setup):
    setup.client_factory=factory_for()
    review=(await setup.discover())['deployment_review']
    setup.approve(review['id'],True)
    setup.client_factory=factory_for(hook=setup.clear)
    with pytest.raises(Denied,match='settings changed'): await setup.probe(True)
    assert setup.last_test is None


@async_test
async def test_expired_deployment_review_rejected(setup):
    setup.client_factory=factory_for()
    review=(await setup.discover())['deployment_review']
    setup.clock=lambda:10000
    with pytest.raises(Denied): setup.approve(review['id'],True)


def test_owner_auth_origin_and_no_secret_echo(bundle):
    g,*_=bundle
    client=TestClient(owner_app(g,'owner-test',8791),base_url='http://127.0.0.1:8791')
    endpoint='/api/near-setup-key'
    assert client.post(endpoint,json={'api_key':'sk-fictional-secret'}).status_code==401
    headers={'Authorization':'Bearer owner-test'}
    assert client.post(endpoint,headers={**headers,'Origin':'https://evil.example'},json={'api_key':'sk-fictional-secret'}).status_code==403
    result=client.post(endpoint,headers=headers,json={'api_key':'sk-fictional-secret'})
    assert result.status_code==200 and 'sk-fictional-secret' not in result.text
    with g.store.transaction() as saved:
        assert 'sk-fictional-secret' not in json.dumps(saved)
    assert client.post('/api/near-setup-probe',headers=headers,json={'approved':False}).status_code==400
    assert client.get('/near-setup').status_code==200


def test_safe_start_near_demo_does_not_open_personal_sources(tmp_path):
    controller=SafeTest(__import__('pathlib').Path(__file__).parents[1],tmp_path)
    client=TestClient(controller.app('owner-test',8791),base_url='http://127.0.0.1:8791')
    headers={'Authorization':'Bearer owner-test'}
    assert client.get('/near-demo').status_code==200
    assert client.get('/near-setup').status_code==200
    response=client.post('/api/near-state',headers=headers,json={})
    assert client.get('/memory.css').status_code==200
    assert response.status_code==200 and response.json()['loaded']
    assert controller.personal is None
    assert client.post('/api/near-setup-status',headers=headers,json={}).status_code==200
    assert client.post('/api/near-setup-status',json={}).status_code==401
    assert client.post('/api/library',headers=headers,json={}).status_code==400
