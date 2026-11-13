"""NEAR-only, deployment-first inference. No generic URL, fallback or payload logs.

Uses the official nearai/inference-sdk public API (pinned in requirements-near.txt).
The SDK owns quote/GPU verification, TLS pinning and exact-byte signature checks.
Application policy additionally pins measured configurations and requires a unique
model signature. Missing evidence is a failure, never a green status.
"""
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Protocol

from .core import Denied

BASE_URL = 'https://cloud-api.near.ai/v1'
DESTINATION = BASE_URL + '/chat/completions'
DEFAULT_MODEL = 'z-ai/glm-5.3-flash'
SDK_VERSION = '0.3.0'


class Provider(Protocol):
    async def complete(self, body: bytes, authorize): ...


def model_name():
    value = os.environ.get('NEARAI_MODEL', DEFAULT_MODEL)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise Denied('Use a canonical NEAR model ID, not an alias or URL.')
    return value


def pins(name):
    values = os.environ.get(name, '').split(',')
    return {x.strip().lower() for x in values if re.fullmatch(r'[a-fA-F0-9]{64}', x.strip())}


def readiness():
    missing = []
    if not os.environ.get('NEARAI_API_KEY'): missing.append('NEARAI_API_KEY is not configured')
    if importlib.util.find_spec('nearai_inference_sdk') is None: missing.append('official NEAR verifier SDK is not installed')
    for name in ('NEARAI_GATEWAY_COMPOSE_SHA256', 'NEARAI_MODEL_COMPOSE_SHA256'):
        if not pins(name): missing.append(name + ' needs reviewed deployment hashes')
    return {'ready': not missing, 'missing': missing, 'verified': False}


def accept_deployment(deployment, allowed):
    raw = getattr(deployment, 'app_compose', None)
    if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() not in allowed:
        raise Denied('NEAR deployment is outside the reviewed configuration allowlist. Nothing sent.')


@asynccontextmanager
async def sdk_client(key):
    # Import errors, unsupported native verifier builds and SDK drift fail closed.
    from importlib.metadata import version
    if version('nearai-inference-sdk') != SDK_VERSION:
        raise Denied('Install the pinned NEAR verifier version before live inference.')
    from nearai_inference_sdk import (
        InferenceClient, AttestationPolicy, ModelAttestationPolicy,
        GatewayVerificationOptions, ModelVerificationOptions, AttestationVerifiers,
    )
    gateway_pins = pins('NEARAI_GATEWAY_COMPOSE_SHA256')
    model_pins = pins('NEARAI_MODEL_COMPOSE_SHA256')
    if not gateway_pins or not model_pins:
        raise Denied('Review and configure NEAR deployment hashes before live inference.')
    # Suppress third-party HTTP diagnostics; exceptions are never logged or echoed.
    for name in ('httpx', 'httpcore', 'nearai_inference_sdk'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    async with InferenceClient(
        key, base_url=BASE_URL, signing_algo='ed25519', e2ee=True,
        headers={'x-no-aliasing': 'true', 'Accept-Encoding': 'identity'},
        attestation_cache_time_to_live_ms=60000,
        gateway_verification=GatewayVerificationOptions(
            include_spki_fingerprint=True,
            policy=AttestationPolicy(accepted_tcb_statuses=('UpToDate',)),
            verifiers=AttestationVerifiers(deployment=lambda d: accept_deployment(d, gateway_pins)),
        ),
        model_verification=ModelVerificationOptions(
            policy=ModelAttestationPolicy(accepted_tcb_statuses=('UpToDate',), gpu_evidence='required'),
        ),
        deployment_policy=lambda model, d: accept_deployment(d, model_pins),
    ) as client:
        yield client


def validate_preflight(evidence):
    gateway = getattr(evidence, 'gateway', None)
    models = getattr(evidence, 'models', ())
    if gateway is None or not models:
        raise Denied('Gateway and model verification evidence is required. Nothing sent.')
    if getattr(getattr(gateway, 'tls_binding', None), 'kind', None) != 'attested':
        raise Denied('Gateway TLS binding is unverified. Nothing sent.')
    for report in (gateway, *models):
        if getattr(report, 'tcb_status', None) != 'UpToDate' or getattr(report, 'advisory_ids', ()):
            raise Denied('NEAR hardware status or advisories do not meet this demo policy. Nothing sent.')
    if any(getattr(m, 'gpu_evidence', None) != 'verified' for m in models):
        raise Denied('Model GPU evidence is required. Nothing sent.')
    return {'gateway': 'passed', 'model': 'passed', 'tls': 'passed', 'response_signature': 'pending'}


class NearProvider:
    def __init__(self, client_factory=None, key=None, timeout=90):
        self.factory = client_factory or sdk_client
        self.key = key if key is not None else os.environ.get('NEARAI_API_KEY', '')
        self.timeout = timeout

    async def complete(self, body, authorize):
        if not self.key or '\n' in self.key or '\r' in self.key:
            raise Denied('NEAR API key is missing or invalid. No inference request sent.')
        checks = {'gateway': 'not checked', 'model': 'not checked', 'tls': 'not checked', 'response_signature': 'not checked'}
        dispatched = False
        try:
            import httpx
            payload = json.loads(body)
            async with asyncio.timeout(self.timeout):
                async with self.factory(self.key) as client:
                    evidence = await client.verify(payload['model'])
                    checks = validate_preflight(evidence)
                    # Last local permission check after all preflight I/O. Commits
                    # a single-use dispatch marker before handing bytes to the SDK.
                    authorize()
                    dispatched = True
                    async def transmission_guard(event, info):
                        # The SDK may await cached verification/encryption after
                        # verify(). HTTPcore's trace survives SDK preparation and
                        # pinned TLS and runs before inference headers are sent.
                        if event in ('http11.send_request_headers.started', 'http2.send_request_headers.started'):
                            recheck = getattr(authorize, 'recheck', None)
                            if recheck is None:
                                raise Denied('A final permission check is required before NEAR transmission.')
                            recheck()
                    response = await client.send(httpx.Request('POST', DESTINATION, content=body,
                        headers={'Content-Type': 'application/json', 'x-no-aliasing': 'true', 'Accept-Encoding': 'identity'},
                        extensions={'trace':transmission_guard}))
                    try:
                        response.raise_for_status()
                        raw = await response.aread()
                        if len(raw) > 1024 * 1024: raise ValueError('Response size')
                        result = json.loads(raw)
                        receipt = await client.verify_response(result['id'])
                        if receipt.signature_kind != 'provider_tee' or len(getattr(receipt, 'attestations', ())) != 1:
                            raise Denied('A unique model-signature binding is required. Response withheld.')
                        if result.get('model') != payload['model']:
                            raise Denied('Response model differs from the approved model. Response withheld.')
                        text = result['choices'][0]['message']['content']
                        if not isinstance(text, str) or not text.strip(): raise ValueError('Empty draft')
                        checks['response_signature'] = 'passed (model TEE)'
                        checks['encryption'] = 'official SDK client-side encryption to attested model key'
                        return {'draft': text, 'checks': checks, 'mode': 'live', 'inference_calls': 1}
                    finally:
                        await response.aclose()
        except Denied:
            raise
        except TimeoutError:
            raise Denied('NEAR timed out. ' + ('An approved request may have reached NEAR; response withheld.' if dispatched else 'No inference request sent.') + ' No retry or fallback.') from None
        except Exception:
            raise Denied('NEAR verification or provider request failed. ' + ('An approved request may have reached NEAR; response withheld.' if dispatched else 'No inference request sent.') + ' No retry or fallback.') from None


class RehearsalProvider:
    """Explicit offline fixture, never selected as a fallback from NEAR."""
    async def complete(self, body, authorize):
        from .founder_demo import REHEARSAL_DRAFT
        authorize()
        return {'draft': REHEARSAL_DRAFT, 'mode': 'rehearsal', 'inference_calls': 0,
                'checks': {k: 'not performed (offline rehearsal)' for k in ('gateway', 'model', 'tls', 'response_signature')}}
