"""Real pinned-SDK cryptography with local keys; no live NEAR attestation claim."""
import asyncio
import json
import httpx
import pytest

sdk=pytest.importorskip('nearai_inference_sdk')
from nearai_inference_sdk import E2eeModelKey, prepare_e2ee_chat_request
from nearai_inference_sdk.core.e2ee import (create_e2ee_client_key_pair, decrypt_e2ee_text,
    encrypt_e2ee_text, build_e2ee_request_aad, e2ee_field_aad)
from privacy_layer.near_provider import sdk_client


def test_official_encryption_roundtrip_and_fresh_keys():
    model=create_e2ee_client_key_pair()
    key=E2eeModelKey(signing_algo='ed25519',public_key=model.public_key)
    payload={'model':'z-ai/glm-5.3-flash','messages':[{'role':'user','content':'APPROVED-CONTEXT-LOCAL-TEST'}],'stream':False}
    async def run():
        async def trace(event,info):pass
        request=lambda:httpx.Request('POST','https://cloud-api.near.ai/v1/chat/completions',json=payload,extensions={'trace':trace})
        a=await prepare_e2ee_chat_request(request(),key);b=await prepare_e2ee_chat_request(request(),key)
        assert b'APPROVED-CONTEXT-LOCAL-TEST' not in a.request.content
        assert a.request.content!=b.request.content
        assert a.request.headers['x-client-pub-key']!=b.request.headers['x-client-pub-key']
        assert a.request.headers['x-model-pub-key']==model.public_key
        assert a.request.headers['x-encryption-version']=='3'
        assert a.request.headers['x-encrypt-all-fields']=='true'
        assert a.request.extensions['trace'] is trace
        reply=E2eeModelKey(signing_algo='ed25519',public_key=a.request.headers['x-client-pub-key'])
        aad=e2ee_field_aad(build_e2ee_request_aad(reply),'messages[].content')
        encrypted=json.loads(a.request.content)['messages'][0]['content']
        assert decrypt_e2ee_text(encrypted,model,'content',aad)=='APPROVED-CONTEXT-LOCAL-TEST'
        response=httpx.Response(200,json={'id':'local-fixture','model':payload['model'],
            'choices':[{'message':{'role':'assistant','content':encrypt_e2ee_text('Generated fixture response',reply)}}]})
        decrypted=await a.decrypt_response(response)
        assert decrypted.json()['choices'][0]['message']['content']=='Generated fixture response'
    asyncio.run(run())


def test_production_sdk_enables_e2ee_and_requires_reviewed_pins(monkeypatch):
    from privacy_layer.core import Denied
    monkeypatch.delenv('NEARAI_GATEWAY_COMPOSE_SHA256',raising=False)
    async def missing():
        async with sdk_client('fixture'):pytest.fail('Must reject missing pins')
    with pytest.raises(Denied):asyncio.run(missing())
    monkeypatch.setenv('NEARAI_GATEWAY_COMPOSE_SHA256','a'*64)
    monkeypatch.setenv('NEARAI_MODEL_COMPOSE_SHA256','b'*64)
    async def configured():
        async with sdk_client('fixture') as client:
            assert client._e2ee is True
            assert client._openai.max_retries==0
    asyncio.run(configured())
