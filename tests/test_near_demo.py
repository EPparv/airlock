"""Boundary tests with fictional fixtures and an explicitly mocked NEAR SDK.

No successful test below is evidence of a live NEAR attestation or completion.
"""
import asyncio
import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import httpx
import pytest
from starlette.testclient import TestClient

from privacy_layer.core import Denied
from privacy_layer.founder_demo import FounderDemo, MEETING, FINANCE, RESTRICTED_VALUE
from privacy_layer.near_provider import NearProvider, DESTINATION, DEFAULT_MODEL, accept_deployment
from privacy_layer.server import owner_app


def run(awaitable): return asyncio.run(awaitable)


class FakeSDK:
    def __init__(self):
        self.sent = []
        self.hook = None
        self.fail_at = None
        report = lambda: NS(tcb_status='UpToDate', advisory_ids=(), gpu_evidence='verified')
        self.evidence = NS(gateway=report(), models=(report(),))
        self.evidence.gateway.tls_binding = NS(kind='attested')
        self.receipt = NS(signature_kind='provider_tee', attestations=(report(),))
        self.response_model = DEFAULT_MODEL

    async def verify(self, model):
        if self.hook: self.hook()
        if self.fail_at == 'verify': raise RuntimeError(RESTRICTED_VALUE)
        return self.evidence

    async def send(self, request):
        if self.fail_at == 'revoke_before_wire':
            self.hook()
            await request.extensions['trace']('http11.send_request_headers.started', {})
        self.sent.append(request)
        if self.fail_at == 'send': raise RuntimeError(RESTRICTED_VALUE)
        if self.fail_at == 'timeout': raise TimeoutError(RESTRICTED_VALUE)
        return httpx.Response(200, request=request, json={'id':'fixture-response', 'model':self.response_model,
            'choices':[{'message':{'content':'Hi Maya, thanks for meeting. Can we do a 20-minute walkthrough Thursday?'}}]})

    async def verify_response(self, identifier):
        assert identifier == 'fixture-response'
        if self.fail_at == 'signature': raise RuntimeError(RESTRICTED_VALUE)
        return self.receipt

    @asynccontextmanager
    async def factory(self, key):
        yield self


@pytest.fixture
def demo(bundle, monkeypatch):
    monkeypatch.delenv('NEARAI_MODEL', raising=False)
    sdk = FakeSDK()
    g = bundle[0]
    service = FounderDemo(g, NearProvider(sdk.factory, key='fictional-key'))
    service.reset(); service.grant()
    return service, sdk, bundle[2]


def send(d, p):
    return run(d.send(p['approval_id'], True, p['sha256']))


def test_approved_payload_is_exact_and_restricted_value_never_leaves(demo, caplog):
    d,sdk,_ = demo
    p=d.review([MEETING]); result=send(d,p)
    assert result['mode']=='live'  # mocked SDK; not a live integration test
    assert len(sdk.sent)==1
    request=sdk.sent[0]
    assert str(request.url)==DESTINATION
    assert request.content==p['payload'].encode()
    assert json.loads(request.content)['model']==DEFAULT_MODEL
    assert b'Maya Chen' in request.content
    assert RESTRICTED_VALUE.encode() not in request.content
    assert 'ORCHID-NEVER-SHARE-83Q' not in str(request.headers)+str(request.url)+caplog.text
    assert result['payload_sha256']==p['sha256']
    assert result['checks']['response_signature']=='passed (model TEE)'


def test_never_share_blocks_before_provider_or_verifier(demo):
    d,sdk,_=demo
    sdk.hook=lambda: pytest.fail('No verification network allowed for restricted request')
    p=d.review([MEETING,FINANCE])
    assert p['blocked'] and p['provider_calls']==0
    assert 'never share' in p['reason']
    assert not sdk.sent


@pytest.mark.parametrize('change',['revoked','grant_expired','approval_expired','changed_text','device_only','never_share','derived','reset','new_grant'])
def test_permissions_rechecked_after_review(demo,change):
    d,sdk,now=demo; p=d.review([MEETING])
    if change=='revoked': d.revoke()
    elif change=='reset': d.reset()
    elif change=='new_grant': d.grant()
    elif change=='approval_expired': now[0]+=121
    else:
        with d.store.transaction() as data:
            demo_state=data['founder_demo']; row=demo_state['records'][MEETING]
            if change=='grant_expired': demo_state['grant']['expires']=now[0]-1
            elif change=='changed_text': row['text']+=' Changed locally.'
            elif change=='derived': row['derived_from']=[FINANCE]
            else: row[change]=True
    with pytest.raises(Denied):send(d,p)
    assert not sdk.sent


@pytest.mark.parametrize('change',['revoked','expired','reset','changed_text'])
def test_permission_changes_during_verification_block_dispatch(demo,change):
    d,sdk,now=demo; p=d.review([MEETING])
    def mutate():
        if change=='revoked': d.revoke()
        elif change=='expired': now[0]+=601
        elif change=='reset': d.reset()
        else:
            with d.store.transaction() as data:data['founder_demo']['records'][MEETING]['text']='Changed meeting.'
    sdk.hook=mutate
    with pytest.raises(Denied):send(d,p)
    assert not sdk.sent


@pytest.mark.parametrize('kind',['no_gateway','no_models','no_tls','bad_tcb','advisory','no_gpu','exception'])
def test_verification_failures_prevent_transmission(demo,kind):
    d,sdk,_=demo; p=d.review([MEETING])
    if kind=='no_gateway':sdk.evidence.gateway=None
    elif kind=='no_models':sdk.evidence.models=()
    elif kind=='no_tls':sdk.evidence.gateway.tls_binding.kind='none'
    elif kind=='bad_tcb':sdk.evidence.models[0].tcb_status='OutOfDate'
    elif kind=='advisory':sdk.evidence.gateway.advisory_ids=('INTEL-SA-fixture',)
    elif kind=='no_gpu':sdk.evidence.models[0].gpu_evidence='not_provided'
    else:sdk.fail_at='verify'
    with pytest.raises(Denied) as error:send(d,p)
    assert RESTRICTED_VALUE not in str(error.value)
    assert not sdk.sent


@pytest.mark.parametrize('kind',['send','timeout','signature','gateway_signature','ambiguous_signer','wrong_model'])
def test_failure_hides_answer_and_never_falls_back(demo,kind,caplog):
    d,sdk,_=demo; p=d.review([MEETING])
    if kind=='gateway_signature':sdk.receipt.signature_kind='gateway'
    elif kind=='ambiguous_signer':sdk.receipt.attestations=(*sdk.receipt.attestations,*sdk.receipt.attestations)
    elif kind=='wrong_model':sdk.response_model='incognito/other'
    else:sdk.fail_at=kind
    with pytest.raises(Denied) as error:send(d,p)
    assert len(sdk.sent)==1
    assert d.state()['result'] is None
    assert RESTRICTED_VALUE not in str(error.value)+caplog.text
    with pytest.raises(Denied):send(d,p)
    assert len(sdk.sent)==1


def test_approval_mandatory_and_single_use(demo):
    d,sdk,_=demo; p=d.review([MEETING])
    for approved,sha in [(False,p['sha256']),('true',p['sha256']),(True,'modified')]:
        with pytest.raises(Denied):run(d.send(p['approval_id'],approved,sha))
    assert not sdk.sent
    send(d,p)
    with pytest.raises(Denied):send(d,p)
    assert len(sdk.sent)==1


def test_reset_preserves_real_connections_and_clears_only_demo(demo):
    d,_,_=demo
    with d.store.transaction() as data:data['unrelated']={'preserve':True}
    p=d.review([MEETING],mode='rehearsal');send(d,p)
    d.reset();s=d.state()
    assert s['grant'] is None and s['result'] is None and not s['events']
    with d.store.transaction() as data:assert data['unrelated']=={'preserve':True}


def test_rehearsal_is_explicit_and_performs_no_network(demo):
    d,sdk,_=demo
    sdk.hook=lambda:pytest.fail('Rehearsal cannot reach live provider')
    p=d.review([MEETING],'rehearsal');r=send(d,p)
    assert r['mode']=='rehearsal' and r['inference_calls']==0
    assert all('not performed' in v for v in r['checks'].values())
    assert 'Thursday' in r['draft'] and RESTRICTED_VALUE not in r['draft']
    assert not sdk.sent


def test_model_change_invalidates_review(demo,monkeypatch):
    d,sdk,_=demo;p=d.review([MEETING])
    monkeypatch.setenv('NEARAI_MODEL','other/canonical')
    with pytest.raises(Denied):send(d,p)
    assert not sdk.sent


def test_unknown_and_derived_restricted_records_fail_closed(demo):
    d,sdk,_=demo
    assert d.review(['unknown'])['blocked']
    with d.store.transaction() as data:
        data['founder_demo']['records'][MEETING]['derived_from']=[FINANCE]
    assert d.review([MEETING])['blocked']
    assert not sdk.sent


def test_store_is_encrypted_and_audit_has_no_content(demo):
    d,_,_=demo
    d.review([FINANCE])
    assert RESTRICTED_VALUE.encode() not in d.store.path.read_bytes()
    with d.store.transaction() as data:
        assert RESTRICTED_VALUE not in json.dumps(data['audit'])+json.dumps(data['founder_demo']['events'])


def test_measured_config_pin_rejects_changed_config():
    import hashlib
    measured=NS(app_compose='{"fixture":true}')
    pin=hashlib.sha256(measured.app_compose.encode()).hexdigest()
    accept_deployment(measured,{pin})
    with pytest.raises(Denied):accept_deployment(NS(app_compose='{"fixture": true}'),{pin})


def test_owner_api_complete_rehearsal_and_access_boundary(bundle):
    app=owner_app(bundle[0],'fixture-owner',8791)
    with TestClient(app,base_url='http://127.0.0.1:8791') as client:
        assert client.post('/api/near-reset',json={}).status_code==401
        headers={'Authorization':'Bearer fixture-owner','Origin':'http://127.0.0.1:8791'}
        def call(action,body={}):return client.post('/api/near-'+action,json=body,headers=headers)
        assert call('reset').status_code==200
        assert call('grant').status_code==200
        assert call('review',{'ids':[MEETING],'mode':'rehearsal','prompt':'extra data'}).status_code==400
        p=call('review',{'ids':[MEETING],'mode':'rehearsal'}).json()
        assert RESTRICTED_VALUE not in p['payload']
        r=call('send',{'approval_id':p['approval_id'],'approved':True,'payload_hash':p['sha256']})
        assert r.status_code==200 and r.json()['inference_calls']==0
        assert call('review',{'ids':[FINANCE],'mode':'live'}).json()['provider_calls']==0
        assert client.post('/api/near-reset',json={},headers={**headers,'Origin':'https://attacker.invalid'}).status_code==403
        assert client.get('/near.js').status_code==200
        assert client.get('/near.css').status_code==200


def test_near_final_transport_guard_rechecks_revocation(demo):
    d,sdk,_=demo
    p=d.review([MEETING])
    sdk.fail_at='revoke_before_wire'
    # Initial verification remains valid; revoke only in the SDK send path.
    original_verify=sdk.verify
    async def verify(model):
        saved=sdk.hook;sdk.hook=None
        try:return await original_verify(model)
        finally:sdk.hook=saved
    sdk.verify=verify;sdk.hook=d.revoke
    with pytest.raises(Denied):send(d,p)
    assert sdk.sent==[]
