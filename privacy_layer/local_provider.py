"""Explicit local inference for the founder task, never a cloud fallback.

Uses the companion Private_AI/private_ai/network.py Ollama contract and its
GGUF/remote-alias/context checks. The transport here retains reviewed bytes.
The local Ollama daemon and installed weights are trusted, not TEE-attested.
"""
import asyncio
import json
import os
import re

import httpx

from .core import Denied

LOCAL_BASE = 'http://127.0.0.1:11434'
LOCAL_DESTINATION = LOCAL_BASE + '/api/chat'
DEFAULT_LOCAL_MODEL = 'qwen3:4b-instruct'


def local_model_name():
    model = os.environ.get('AIRLOCK_DEMO_LOCAL_MODEL', DEFAULT_LOCAL_MODEL)
    if len(model)>120 or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*(?::[A-Za-z0-9_.-]+)?',model) or 'cloud' in model.lower():
        raise Denied('Select an installed local Ollama model. Cloud aliases are disabled.')
    return model


class LocalProvider:
    def __init__(self, transport=None, timeout=120):
        self.transport, self.timeout = transport, timeout

    def client(self):
        return httpx.AsyncClient(transport=self.transport,trust_env=False,
                                follow_redirects=False,timeout=self.timeout)

    async def _preflight(self, client, model):
        response=await client.post(LOCAL_BASE+'/api/show',json={'model':model},timeout=8)
        response.raise_for_status()
        info=response.json(); metadata=info.get('model_info') or {}
        if info.get('remote_host') or info.get('remote_model') or (info.get('details') or {}).get('format')!='gguf' or not metadata:
            raise Denied('Ollama must use local GGUF weights. Remote aliases are blocked. Nothing sent for inference.')
        capacity=metadata.get(str(metadata.get('general.architecture',''))+'.context_length')
        if type(capacity) is not int or capacity<4096 or 'completion' not in info.get('capabilities',[]):
            raise Denied('Choose a local chat model with at least 4,096 context tokens.')
        thinking=(info.get('thinking') or {}).get('values')
        if str(metadata.get('general.finetune','')).lower()=='thinking' or isinstance(thinking,list) and True in thinking and False not in thinking:
            raise Denied('Use an instruction model for this short demo, such as qwen3:4b-instruct.')
        return info

    async def check(self):
        try:
            async with self.client() as client:
                await self._preflight(client,local_model_name())
            return {'ready':True,'message':'Ollama answered and reports local GGUF weights. No note content was sent.','verified':False}
        except Denied as error:
            return {'ready':False,'message':str(error),'verified':False}
        except Exception:
            return {'ready':False,'message':'Cannot reach the selected local model. Open Ollama and install '+local_model_name()+'. No note content was sent.','verified':False}

    async def complete(self,body,authorize):
        dispatched=False
        try:
            payload=json.loads(body)
            if payload['model']!=local_model_name():raise Denied('Local model changed. Review the request again.')
            if len(body)+payload['options']['num_predict']+1024>payload['options']['num_ctx']:
                raise Denied('Selected context exceeds the local demo budget. Nothing sent for inference.')
            async with asyncio.timeout(self.timeout):
                async with self.client() as client:
                    info=await self._preflight(client,payload['model'])
                    metadata=info['model_info']
                    if metadata.get(str(metadata.get('general.architecture',''))+'.context_length',0)<payload['options']['num_ctx']:
                        raise Denied('The selected local model cannot fit this context window. Nothing sent for inference.')
                    authorize()
                    dispatched=True
                    async with client.stream('POST',LOCAL_DESTINATION,content=body,headers={'Content-Type':'application/json'}) as response:
                        response.raise_for_status()
                        raw=bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw)>1024*1024:raise ValueError('response size')
                    result=json.loads(raw)
                    draft=result.get('message',{}).get('content')
                    if result.get('model')!=payload['model'] or result.get('done') is not True or result.get('done_reason')=='length':
                        raise Denied('Local generation was incomplete or used a different model. Draft withheld. No fallback.')
                    if not isinstance(draft,str) or not draft.strip() or '<think>' in draft:
                        raise Denied('The local model did not return a final draft. No fallback.')
                    return {'draft':draft.strip(),'mode':'local','inference_calls':1,'cloud_inference_calls':0,
                            'checks':{'local_weights':'Ollama reports local GGUF weights; daemon is trusted',
                                      'destination':'fixed loopback address; proxy and redirects disabled',
                                      'gateway':'not performed (local mode)', 'model':'not TEE-attested (local mode)',
                                      'response_signature':'not performed (local mode)'}}
        except Denied:raise
        except (TimeoutError,httpx.TimeoutException):
            raise Denied('Local AI timed out. '+('The approved request may have reached Ollama. ' if dispatched else 'No inference request sent. ')+'No retry or cloud fallback.') from None
        except Exception:
            raise Denied('Local AI could not complete the request. Open Ollama and check the installed model. No retry or cloud fallback.') from None
