"""Isolated first-run checks. Personal sources are constructed only after opt-in."""
import asyncio
import copy
import json
import os
from pathlib import Path
import secrets
import threading
import time

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .core import Gateway, EncryptedStore, Denied, digest, normalized
from .context import ContextHub
from .agent_memory import AgentMemory
from .device_apps import ExampleApps, NativeApps
from .workspace import Workspace, TOOLS as DEVICE_TOOLS, WORKSPACE_ASSETS

REHEARSAL = 'Cypress product rehearsal is November 18.'
PRIVATE = 'FICTIONAL-ORCHID-7429'
ALLOWED = ('privacy_status', 'get_private_context', 'context_status', 'update_shared_context')


class TestSources:
    """No legacy vault, file discovery, credentials, mailbox, or model adapter."""
    def __init__(self, store):
        self.connection_store = store
        self.context_home = store.path.parent / 'empty-profile'

    def library(self):
        return ContextHub(self.connection_store, home=self.context_home).rows()

    def protected(self):
        return [PRIVATE]

    def read(self, kind, identifier):
        return next(r for r in self.library() if r['kind'] == kind and r['source_id'] == identifier)


class TestGateway(Gateway):
    def call(self, token, tool, args):
        if tool not in ALLOWED and tool not in DEVICE_TOOLS:
            raise Denied('The isolated test has no email, real files, imports, execution or inference access.')
        if tool == 'update_shared_context' and (
            args.get('operation') != 'add' or args.get('kind') != 'memories' or
            normalized(args.get('text', '')) != normalized(REHEARSAL) or
            args.get('reference', '') or args.get('expected_revision', 0) != 0
        ):
            raise Denied('Safe test accepts only this fictional proposal: ' + REHEARSAL)
        return super().call(token, tool, args)


class GatewayRouter:
    def __init__(self, controller):
        self.controller = controller

    def authenticate(self, token, *, discovered=False, initialized=False):
        """The HTTP boundary authenticates before dispatching any MCP method."""
        c = self.controller
        try:
            return c.g.authenticate(token, discovered=discovered, initialized=initialized)
        except Denied:
            personal = c.personal
            if personal is None:
                raise Denied('Personal access is closed.') from None
            result = personal.authenticate(token, discovered=discovered, initialized=initialized)
            if c.personal is not personal:
                raise Denied('The personal workspace closed during authentication.')
            return result

    def call(self, token, tool, args):
        c = self.controller
        try:
            c.g.authenticate(token)
        except Denied:
            personal = c.personal
            if personal is None:
                raise Denied('Personal access is closed. Open the personal workspace explicitly in Airlock.') from None
            result = personal.call(token, tool, args)
            if c.personal is not personal:
                raise Denied('The personal workspace closed during this request.')
            return result
        return c.g.call(token, tool, args)


class SafeTest:
    def __init__(self, root, state, clock=time.time, profile_home=None):
        self.root, self.state, self.clock = Path(root), Path(state), clock
        self.profile_home = profile_home
        self.folder = self.state / 'safe-test'
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        key_file = self.folder / 'fictional.key'
        if not key_file.exists():
            fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(secrets.token_bytes(32))
        self.key = key_file.read_bytes()
        self.g = self.reopen()
        self.personal = self.personal_app = self.personal_token = None
        self.lock = threading.RLock()
        with self.g.store.transaction() as data:
            initialized = bool(data.get('safe_test'))
        if not initialized:
            self.reset()

    def reopen(self):
        store = EncryptedStore(self.folder / 'fictional.enc', self.key)
        gateway = TestGateway(store, TestSources(store), self.clock)
        gateway.device_apps = ExampleApps()
        return gateway

    def metadata(self):
        with self.g.store.transaction() as d:
            return copy.deepcopy(d['safe_test'])

    def grant(self, agent='test'):
        meta = self.metadata()
        result = self.g.create(agent=agent, purpose='Fictional Airlock test only', views=[], approved=True,
                               mode='automatic', lifetime=604800, max_calls=1000)
        AgentMemory(self.g).configure(result['id'], meta['public_refs'], disclose=True, proposals=True)
        return result

    def reset(self):
        with self.lock, self.g.store.transaction() as d:
            # This store has no path to personal state. Old test tokens stop working.
            d.clear()
            d.update(grants={}, audit=[], audit_head='0'*64)
        hub = ContextHub(self.g.store, home=self.g.sources.context_home, clock=self.clock)
        p = hub.preview('Fictional test.json', json.dumps({'memories':[
            '[CORE] Fictional project: Cypress launches November 20.',
            {'text':'Fictional private note: '+PRIVATE, 'device_only':True}],
            'skills':['[CORE] For Cypress updates, use two concise bullets.']}).encode())
        hub.commit(p['id'], list(range(len(p['items']))), [])
        rows = AgentMemory(self.g).snapshot()
        public = [ref for ref, r in rows.items() if not r['never_share']]
        project = next(ref for ref, r in rows.items() if 'launches' in r['text'])
        with self.g.store.transaction() as d:
            d['safe_test'] = {'public_refs':public, 'project_ref':project, 'checks':{}, 'live':[], 'proposal':None}
        grant = self.grant()
        with self.g.store.transaction() as d:
            d['safe_test']['local'] = grant
        return self.status()

    def read(self, query='Cypress'):
        return self.g.call(self.metadata()['local']['token'], 'get_private_context', {'query':query})

    def record(self, step, passed, detail, result=None):
        value = {'passed':bool(passed), 'detail':detail, 'at':self.clock()}
        if result is not None:
            value['response'] = result
        with self.g.store.transaction() as d:
            d['safe_test']['checks'][step] = value
        return value

    def check(self, step):
        if step not in ('recall','privacy','correction','propose','approve','persistence','revoke'):
            raise Denied('Choose a test step.')
        with self.lock:
            meta = self.metadata()
            if step == 'recall':
                result = self.read()
                text = str(result['items'])
                expected = 'November 27' if meta['checks'].get('correction',{}).get('passed') else 'November 20'
                return self.record(step, expected in text and 'two concise bullets' in text,
                                   'The real retrieval engine returned the fictional launch and writing preference.', result)
            if step == 'privacy':
                result = self.read('private note '+PRIVATE)
                denied = False
                try:
                    self.g.call(meta['local']['token'], 'search_gmail', {'query':'anything'})
                except Denied:
                    denied = True
                return self.record(step, PRIVATE not in json.dumps(result) and denied,
                                   'The restricted fictional value was withheld. Email access was blocked.', result)
            if step == 'correction':
                m = AgentMemory(self.g); row = m.snapshot()[meta['project_ref']]
                m.edit(meta['project_ref'], 'Fictional project: Cypress launches November 27.', digest(row['text']))
                result = self.read()
                return self.record(step, 'November 27' in str(result['items']) and 'November 20' not in str(result['items']),
                                   'New requests use November 27. Text already sent to an AI cannot be recalled.', result)
            if step == 'propose':
                if meta.get('proposal'):
                    raise Denied('A proposal already exists. Approve it below, or reset the fictional test.')
                result = self.g.call(meta['local']['token'], 'update_shared_context',
                    dict(operation='add',kind='memories',text=REHEARSAL,reference='',expected_revision=0))
                with self.g.store.transaction() as d:
                    d['safe_test']['proposal'] = result['proposal_id']
                before = self.read('Cypress rehearsal')
                return self.record(step, REHEARSAL not in str(before['items']),
                                   'The proposed rehearsal date is pending. It is not yet available to agents.', before)
            if step == 'approve':
                with self.g.store.transaction() as d:
                    pending = [p for p in d.get('memory_proposals',{}).values() if p['status']=='pending']
                if not pending:
                    raise Denied('Propose the fictional rehearsal note first.')
                p = next((p for p in pending if p['id']==meta.get('proposal')), pending[0])
                if normalized(p['text']) != normalized(REHEARSAL):
                    raise Denied('Only the fixed fictional rehearsal note can be approved in this test.')
                m = AgentMemory(self.g); saved = m.decide(p['id'], True)
                ref = 'memories:shared:'+saved['reference']
                with self.g.store.transaction() as d:
                    public = d['safe_test']['public_refs']
                    if ref not in public:public.append(ref)
                # The button explicitly approves sharing this fictional note with test agents.
                for grant in self.g.list_grants():
                    if not grant['revoked'] and grant['expires']>self.clock():
                        m.configure(grant['id'], self.metadata()['public_refs'], disclose=True, proposals=True)
                # A live AI can propose after the guided revocation check. Use a
                # fresh verifier; never reactivate the revoked simulated token.
                verifier = self.grant()
                try:
                    result = self.g.call(verifier['token'], 'get_private_context', {'query':'Cypress rehearsal'})
                finally:
                    self.g.revoke(verifier['id'])
                return self.record(step, REHEARSAL in str(result['items']),
                                   'Approved locally and added to the test agents’ selected records.', result)
            if step == 'persistence':
                expected = self.read()['items']
                reopened = self.reopen()
                result = reopened.call(meta['local']['token'], 'get_private_context', {'query':'Cypress'})
                return self.record(step, result['items']==expected,
                                   'A fresh vault reader recovered the same authorized context. Quit and reopen the app to test a full restart.', result)
            self.g.revoke(meta['local']['id'])
            blocked = False
            try:self.read()
            except Denied:blocked = True
            return self.record(step, blocked, 'The local test connection was revoked and its next request was denied.')

    def status(self):
        meta = self.metadata()
        rows = AgentMemory(self.g).snapshot()
        with self.g.store.transaction() as d:
            pending = [dict(id=p['id'],text=p['text'],agent=p['agent']) for p in d.get('memory_proposals',{}).values() if p['status']=='pending']
            receipts = copy.deepcopy(d.get('disclosures',[])[-12:])
        grants = {g['id']:g for g in self.g.list_grants()}
        live = [dict(id=g['id'],agent=g['agent'],revoked=g['revoked'],expires=g['expires'],
                     last_context_read=g.get('last_context_read')) for key in meta['live'] if (g:=grants.get(key))]
        return {'isolated':True, 'personal_open':self.personal is not None, 'checks':meta['checks'],
                'records':[dict(text=r['text'],kind=r['kind'],private=r['never_share']) for r in rows.values()],
                'pending':pending, 'live':live, 'receipts':receipts, 'rehearsal':REHEARSAL,
                'coverage':'These checks run the real local gateway with fictional data. They do not test an AI model or provider retention.'}

    def connect(self, agent, approved):
        from . import clients
        if agent not in clients.RELATIVE_CONFIGS or approved is not True:
            raise Denied('Choose a supported local AI and approve sharing only the displayed fictional records.')
        grant = self.grant(agent)
        token_path = self.folder / 'clients' / (grant['id']+'.token')
        from .setup import private_write
        try:
            private_write(token_path, grant['token'])
            entry = clients.server_entry(token_path)
            # Always use the running service, including development builds.
            if '--session-file' not in entry['args']:
                entry['args'] += ['--session-file',str(self.state/'launch.json')]
            clients.install_config(agent, entry, home=self.profile_home, server_name='airlock-test')
            with self.g.store.transaction() as d:
                d['safe_test']['live'].append(grant['id'])
            return {'id':grant['id'], 'installed':True,
                    'message':'Airlock Test was added separately. Restart your AI and enable only Airlock Test for this check. Other tools and the AI’s own memories are outside Airlock’s control.'}
        except Exception as error:
            self.g.revoke(grant['id']);token_path.unlink(missing_ok=True)
            if isinstance(error,Denied):raise
            raise Denied('The test connection could not be installed. Its access was revoked.') from None

    def open_personal(self, approved, port, host=None):
        if approved is not True:
            raise Denied('Confirm before opening personal sources and previously approved connections.')
        with self.lock:
            if self.personal is None:
                from .sources import LocalSources
                from .server import owner_app
                sources = LocalSources(context_home=self.profile_home)
                personal = Gateway(EncryptedStore(self.state/'connections.enc',sources.key),sources)
                sources.connection_store = personal.store
                personal.device_apps = NativeApps()
                token = secrets.token_urlsafe(32)
                app = owner_app(personal, token, port)
                self.personal, self.personal_app, self.personal_token = personal, app, token
            authority = f'localhost:{port}' if host == f'localhost:{port}' else f'127.0.0.1:{port}'
            return {'url':f'http://{authority}/personal#'+self.personal_token}

    def app(self, owner_token, port):
        async def asset(req):
            name = {'/workspace':'workspace.html','/workspace/personal':'workspace.html',**WORKSPACE_ASSETS,'/':'safe-test.html','/safe-test.js':'safe-test.js','/safe-test.css':'safe-test.css','/icon.svg':'icon.svg'}.get(req.url.path)
            if not name:return Response(status_code=404)
            return FileResponse(self.root/'ui'/name,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
                'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"})

        async def api(req):
            if req.headers.get('host') not in (f'127.0.0.1:{port}',f'localhost:{port}') or req.headers.get('origin') not in (None,f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                return Response(status_code=403)
            if not secrets.compare_digest(req.headers.get('authorization',''),'Bearer '+owner_token):
                return Response(status_code=401)
            raw=b''
            async for chunk in req.stream():
                raw+=chunk
                if len(raw)>4096:return Response(status_code=413)
            try:
                body=json.loads(raw or '{}'); action=req.path_params['action']
                expected={'workspace-launch-options':set(),'state':set(),'test-state':set(),'test-check':{'step'},'test-reset':{'approved'},
                          'test-connect':{'agent','approved'},'test-disconnect':set(),'open-personal':{'approved'},'close-personal':set()}
                allowed_example = {'workspace-state', 'workspace-try', 'workspace-decide', 'workspace-sources'}
                if action in allowed_example and isinstance(body, dict):
                    with self.lock:
                        work = Workspace(self.g)
                        work.seed()
                        result = work.owner(action, body)
                    return JSONResponse(result, headers={'Cache-Control':'no-store'})
                if not isinstance(body,dict) or action not in expected or set(body)!=expected[action]:
                    raise Denied('Only the guided fictional test is available here.')
                if action == 'workspace-launch-options':
                    # This advertises static Mac capabilities without opening the owner vault.
                    from .quick_connect import launch_options
                    result = {'agents':launch_options()}
                elif action in ('state','test-state'):result=self.status()
                elif action=='test-check':result=self.check(body['step'])
                elif action=='test-reset':
                    if body['approved'] is not True:raise Denied('Confirm resetting the fictional test.')
                    result=self.reset()
                elif action=='test-connect':result=self.connect(**body)
                elif action=='test-disconnect':
                    for key in self.metadata()['live']:self.g.revoke(key)
                    result={'revoked':True}
                elif action=='open-personal':
                    result=await asyncio.to_thread(self.open_personal, body['approved'], port, req.headers.get('host'))
                else:
                    with self.lock:
                        closing = self.personal_app
                        if self.personal is not None and hasattr(self.personal.sources, 'cancel_gmail_sign_in'):
                            self.personal.sources.cancel_gmail_sign_in()
                        self.personal=self.personal_app=self.personal_token=None
                        if closing is not None:
                            closing.state.prompt_gateway.close()
                            closing.state.remote_clients.close()
                    result={'closed':True}
                return JSONResponse(result,headers={'Cache-Control':'no-store'})
            except (Denied,ValueError,TypeError) as e:return JSONResponse({'error':str(e)},status_code=400)
            except Exception:return JSONResponse({'error':'The test could not finish. Review the workspace status, or reopen Airlock to close personal access.'},status_code=400)

        test_app=Starlette(routes=[Route('/workspace',asset),Route('/workspace/personal',asset),*[Route(path,asset) for path in WORKSPACE_ASSETS],Route('/',asset),Route('/safe-test.js',asset),Route('/safe-test.css',asset),Route('/icon.svg',asset),Route('/api/{action}',api,methods=['POST'])])
        near_app = None
        async def dispatch(scope, receive, send):
            nonlocal near_app
            if scope['type']!='http':return await test_app(scope,receive,send)
            path=scope.get('path','');headers=dict(scope.get('headers',[]))
            # Explicit, separate fictional NEAR workspace. It never constructs
            # LocalSources or opens personal memory. Agent test tools stay unchanged.
            near_auth = secrets.compare_digest(headers.get(b'authorization',b''),('Bearer '+owner_token).encode())
            near_path = path in ('/near-demo','/near-setup','/near-setup.js','/near.js','/near.css')
            near_api = path.startswith('/api/near-') and near_auth
            near_asset = near_app and path in ('/ui.js','/ui.css','/memory.css','/context.js','/workbench.js','/onboarding.js')
            near_dashboard = near_app and near_auth and path == '/api/dashboard'
            if near_path or near_api or near_asset or near_dashboard:
                if near_app is None:
                    from .demo_server import make_app
                    near_app = make_app(self.state/'near-fictional',owner_token,port)
                if path == '/near-demo': scope={**scope,'path':'/','raw_path':b'/'}
                return await near_app(scope,receive,send)
            personal_app, token = self.personal_app, self.personal_token
            personal_auth = token and secrets.compare_digest(headers.get(b'authorization',b''),('Bearer '+token).encode())
            personal_asset = path not in ('/','/workspace',*WORKSPACE_ASSETS,'/safe-test.js','/safe-test.css','/icon.svg') and not path.startswith('/api/')
            if personal_app and (personal_auth or personal_asset):
                if path=='/personal':scope={**scope,'path':'/','raw_path':b'/'}
                return await personal_app(scope,receive,send)
            return await test_app(scope,receive,send)
        return dispatch
