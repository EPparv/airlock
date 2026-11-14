"""Owner-only NEAR setup. Keys live in this process, never in fixture stores.

Deployment discovery verifies hardware but sends no inference payload. Accepting
its exact, expiring review pins the observed configurations for this session.
"""
import asyncio
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import time

from .core import Denied, canonical
from . import near_provider as provider

PROBE_PROMPT = 'This is a fictional Airlock connection test. Reply with AIRLOCK_NEAR_OK and nothing else.'


class NearSetup:
    def __init__(self, client_factory=None, clock=time.time):
        self.clock = clock
        self.client_factory = client_factory or provider.sdk_client
        self.key = os.environ.get('NEARAI_API_KEY', '')
        self.gateway_pins = provider.pins('NEARAI_GATEWAY_COMPOSE_SHA256')
        self.model_pins = provider.pins('NEARAI_MODEL_COMPOSE_SHA256')
        self.revision = 0
        self.pending = None
        self.last_test = None
        self.busy = False

    def readiness(self):
        missing = []
        if not self.key: missing.append('Add a NEAR AI key for this session')
        sdk = self.sdk_status()
        if not sdk['ready']: missing.append(sdk['message'])
        if not self.gateway_pins or not self.model_pins:
            missing.append('Verify and review the NEAR deployment')
        return {'ready': not missing, 'missing': missing, 'verified': False}

    @staticmethod
    def sdk_status():
        try:
            installed = importlib.metadata.version('nearai-inference-sdk')
            present = importlib.util.find_spec('nearai_inference_sdk') is not None
        except (importlib.metadata.PackageNotFoundError, ValueError):
            installed, present = None, False
        ready = present and installed == provider.SDK_VERSION
        return {'ready': ready, 'version': installed, 'required': provider.SDK_VERSION,
                'message': 'NEAR verifier installed' if ready else 'Install the pinned NEAR verifier'}

    def status(self):
        review = copy.deepcopy(self.pending) if self.pending and self.pending['expires'] > self.clock() else None
        return {**self.readiness(), 'key_present': bool(self.key), 'key_storage': 'session only',
                'sdk': self.sdk_status(), 'model': provider.model_name(), 'endpoint': provider.BASE_URL,
                'deployment_review': review, 'deployment_approved': bool(self.gateway_pins and self.model_pins),
                'last_test': copy.deepcopy(self.last_test), 'probe_prompt': PROBE_PROMPT,
                'busy': self.busy}

    def configure(self, api_key):
        if self.busy: raise Denied('Wait for the current NEAR operation to finish.')
        if not isinstance(api_key, str) or not 8 <= len(api_key) <= 4096 or any(c.isspace() for c in api_key):
            raise Denied('Enter a valid API key without spaces or newlines.')
        self.key = api_key
        self.revision += 1
        self.pending = self.last_test = None
        # A new account/key requires a new review; never reuse an old green badge.
        self.gateway_pins = set()
        self.model_pins = set()
        return self.status()

    def clear(self):
        # Clearing is allowed during verification and cancels subsequent dispatch.
        self.key = ''
        self.gateway_pins = self.model_pins = set()
        self.pending = self.last_test = None
        self.revision += 1
        return self.status()

    async def discover(self):
        if self.busy: raise Denied('A NEAR operation is already running.')
        if not self.key: raise Denied('Add a NEAR key in this local panel first.')
        if not self.sdk_status()['ready']: raise Denied('Install the pinned NEAR verifier first.')
        self.busy = True
        revision, key = self.revision, self.key
        observed = {'gateway': {}, 'model': {}}
        def observe(kind, deployment):
            raw = getattr(deployment, 'app_compose', None)
            if not isinstance(raw, str) or not raw or len(raw.encode()) > 256000:
                raise Denied('Deployment configuration is unavailable or too large. No inference sent.')
            # Configuration is untrusted text for review, never HTML or commands.
            observed[kind][hashlib.sha256(raw.encode()).hexdigest()] = raw
        try:
            async with asyncio.timeout(90):
                async with self.client_factory(key, observer=observe) as client:
                    evidence = await client.verify(provider.model_name())
                    checks = provider.validate_preflight(evidence)
            if revision != self.revision: raise Denied('NEAR settings changed. Verify again.')
            if not observed['gateway'] or not observed['model']:
                raise Denied('Verified deployment configurations were not returned. No inference sent.')
            self.pending = {'id': secrets.token_urlsafe(24), 'expires': self.clock()+600,
                            'model': provider.model_name(), 'checks': checks,
                            'deployments': [{'kind': kind, 'sha256': sha, 'configuration': raw}
                                            for kind, entries in observed.items() for sha, raw in entries.items()]}
            return self.status()
        except Denied:
            self.pending = None
            raise
        except Exception as error:
            self.pending = None
            raise Denied('NEAR deployment verification failed.' + provider.failure_detail(error) + ' Check the key, credits and network. No inference prompt was sent; no fallback was used.') from None
        finally:
            self.busy = False

    def approve(self, review_id, approved):
        if self.busy: raise Denied('Wait for the current NEAR operation to finish.')
        review = self.pending
        if approved is not True or not review or review_id != review['id'] or review['expires'] <= self.clock() or review['model'] != provider.model_name():
            raise Denied('Review the current deployment configuration before approving it.')
        self.gateway_pins = {x['sha256'] for x in review['deployments'] if x['kind']=='gateway'}
        self.model_pins = {x['sha256'] for x in review['deployments'] if x['kind']=='model'}
        self.pending = None
        self.last_test = None
        self.revision += 1
        return self.status()

    async def complete(self, body, authorize):
        if not self.readiness()['ready']: raise Denied('Complete NEAR setup before sending a private task.')
        revision = self.revision
        config = {'gateway_pins': set(self.gateway_pins), 'model_pins': set(self.model_pins)}
        def check():
            if revision != self.revision: raise Denied('NEAR settings changed. Request cancelled.')
        def allowed():
            check()
            authorize()
        def recheck():
            check()
            fn = getattr(authorize, 'recheck', None)
            if fn is None: raise Denied('A final permission check is required.')
            fn()
        allowed.recheck = recheck
        backend = provider.NearProvider(key=self.key, client_factory=lambda key: self.client_factory(key, settings=config))
        result = await backend.complete(body, allowed)
        check()
        return result

    async def probe(self, approved):
        if approved is not True: raise Denied('Approve the displayed fictional test prompt first.')
        if self.busy: raise Denied('A NEAR operation is already running.')
        self.busy = True
        self.last_test = None
        revision = self.revision
        try:
            body = canonical({'model': provider.model_name(), 'messages': [{'role':'user','content':PROBE_PROMPT}],
                              'stream':False, 'max_tokens':96, 'chat_template_kwargs':{'enable_thinking':False}})
            def authorize(): pass
            authorize.recheck = authorize
            started = time.monotonic()
            result = await self.complete(body, authorize)
            if result['draft'].strip() != 'AIRLOCK_NEAR_OK':
                raise Denied('The signed response did not match the expected test output. Live test is not marked passed.')
            self.last_test = {'passed':True, 'at':self.clock(), 'model':provider.model_name(),
                              'checks':result['checks'], 'inference_calls':result['inference_calls'],
                              'receipt':result.get('receipt'),
                              'elapsed_ms':round((time.monotonic()-started)*1000), 'fictional_data_only':True}
            return self.status()
        except Denied as error:
            if revision == self.revision:
                self.last_test = {'passed':False,'at':self.clock(),'error':str(error)}
            raise
        finally:
            self.busy = False

    async def install(self, approved):
        if approved is not True: raise Denied('Approve installing the NEAR verifier first.')
        if self.busy: raise Denied('A NEAR operation is already running.')
        if self.sdk_status()['ready']: return self.status()
        requirements = Path(__file__).resolve().parents[1] / 'requirements-near.txt'
        if not requirements.is_file(): raise Denied('This build is missing the NEAR installer. Update Airlock.')
        self.busy = True
        process = None
        try:
            # Only this shipped, pinned manifest is installable; no user command,
            # URL or package name is accepted. Keep credentials out of subprocesses.
            uv = Path(sys.prefix).parent / 'uv'
            command = ([str(uv), '--no-config', 'pip', 'install', '--python', sys.executable]
                       if uv.is_file() else [sys.executable, '-m', 'pip', 'install'])
            env = {k:v for k,v in os.environ.items() if not k.startswith('NEARAI_')}
            process = await asyncio.create_subprocess_exec(*command, '-r', str(requirements),
                       stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=env)
            await asyncio.wait_for(process.wait(), 300)
            importlib.invalidate_caches()
            if process.returncode or not self.sdk_status()['ready']:
                raise Denied('Verifier installation failed. Check internet access and retry. No key or prompt was sent to a model.')
            return self.status()
        except (OSError, TimeoutError):
            raise Denied('Verifier installation could not finish. Check internet access and retry.') from None
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            self.busy = False
