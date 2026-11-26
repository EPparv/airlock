import asyncio
from contextlib import ExitStack
import json
import os
import plistlib
import shutil
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import httpx
import pytest
import uvicorn
from mcp import ClientSession,StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client
from starlette.testclient import TestClient
from privacy_layer.server import mcp_app,owner_app


class _CodexStdioRPC:
    def __init__(self, process):
        self.process = process
        self.buffer = b''

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b'\n')
        self.process.stdin.flush()

    def call(self, number, method, params):
        self.send({'id':number, 'method':method, 'params':params})
        deadline = time.monotonic() + 20
        while True:
            if b'\n' not in self.buffer:
                remaining = deadline - time.monotonic()
                assert remaining > 0 and select.select([self.process.stdout], [], [], remaining)[0], f'Codex timed out at {method}'
                data = os.read(self.process.stdout.fileno(), 65536)
                assert data, f'Codex exited at {method} (status {self.process.poll()})'
                self.buffer += data
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            reply = json.loads(line)
            if reply.get('id') == number:
                return reply


@pytest.mark.parametrize('mode', ['cold-stdio', 'running-socket', 'discovery-only'])
@pytest.mark.skipif(not os.environ.get('AIRLOCK_TEST_CODEX'), reason='Requires an explicitly supplied Codex binary')
def test_installed_codex_daemon_reloads_scoped_connection(bundle, serving, tmp_path, monkeypatch, mode):
    """Use a real, disposable vendor daemon and its actual MCP tool-call API without a model turn."""
    from privacy_layer import clients
    binary = Path(os.environ['AIRLOCK_TEST_CODEX']).resolve(strict=True)
    gateway = bundle[0]
    # Unix sockets have a short maximum path on macOS.
    with tempfile.TemporaryDirectory(prefix='al-',dir='/tmp') as temp:
        home = Path(temp); profile = home/'cli'; profile.mkdir()
        monkeypatch.setenv('HOME', str(home)); monkeypatch.setenv('CODEX_HOME', str(profile))
        for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL'):
            monkeypatch.delenv(key, raising=False)
        (profile/'config.toml').write_text('model="fixture"\nmodel_provider="fixture"\n'
            '[model_providers.fixture]\nname="Offline test"\nbase_url="http://127.0.0.1:1"\nwire_api="responses"\n')
        app = home/'Applications/ChatGPT.app'
        app.parent.mkdir()
        supplied_app = next((p for p in reversed(binary.parents) if p.suffix == '.app'), None)
        if supplied_app:
            # Preserve the real bundle layout, code signature, and relative framework paths.
            app.symlink_to(supplied_app, target_is_directory=True)
            assert clients.codex_bundle_binary(app) == binary
        else:
            embedded = app/'Contents/Resources/codex'
            embedded.parent.mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.openai.codex'}))
            shutil.copy2(binary, embedded)
        root = tmp_path/'installed app'
        (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').symlink_to(sys.executable)
        (root/'privacy_layer').symlink_to(Path(clients.__file__).parent)
        (root/'.private').mkdir(); (root/'release.json').write_text('{}')
        (root/'.private/launch.json').write_text(json.dumps({'mcp_url':serving[0]}))
        monkeypatch.setattr(clients, 'ROOT', root)
        control = profile/'app-server-control/app-server-control.sock'

        selected = next(r for r in clients.connection_context(gateway)['records'] if r['ref']=='skills:s1')
        scope = clients.selected_scope(gateway,{selected['ref']:selected['text_hash']})
        def install():
            saved = clients.connect(gateway, agent='codex', approved=True, home=home, scope=scope)
            assert saved['installed'] and Path(saved['path']) == profile/'config.toml'
            return saved

        with ExitStack() as processes:
            def launch(*arguments):
                child = subprocess.Popen([str(binary), *arguments], cwd=home, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                processes.enter_context(child)
                processes.callback(lambda: child.kill() if child.poll() is None else None)
                return child

            if mode != 'running-socket':
                saved = install()
                rpc = _CodexStdioRPC(launch('app-server','--stdio'))
            else:
                daemon = launch('app-server','--listen','unix://')
                for _ in range(200):
                    if control.is_socket() or daemon.poll() is not None:
                        break
                    time.sleep(.05)
                assert control.is_socket(), f'Codex did not expose its control socket (status {daemon.poll()})'
                physical = clients._codex_socket(control)
                assert physical, 'Codex started, but the profile socket identity could not be verified.'
                proxy = launch('app-server','proxy','--sock',str(physical))
                rpc = clients._CodexSocketRPC(proxy, timeout=55, max_bytes=4*1024*1024)
            def result(number, method, params):
                reply = rpc.call(number, method, params)
                assert 'result' in reply, f"Codex rejected {method} (error code {reply.get('error',{}).get('code')})"
                return reply['result']
            result(1,'initialize',{'clientInfo':{'name':'airlock_test','version':'1'},'capabilities':{'experimentalApi':True}})
            rpc.send({'method':'initialized'})
            if mode == 'running-socket':
                initial = result(2,'mcpServerStatus/list',{'detail':'toolsAndAuthOnly'})['data']
                assert not any(r['name']=='airlock' for r in initial)
                saved = install()
                assert saved['reload_requested'], 'The already-running Codex daemon did not acknowledge the Airlock config reload.'
            servers = result(3,'mcpServerStatus/list',{'detail':'toolsAndAuthOnly'})['data']
            assert any(r['name']=='airlock' and 'get_private_context' in r['tools'] for r in servers), 'Codex did not discover the configured Airlock tool.'
            assert clients.connection_status(gateway,saved['id'])['last_discovery'] is not None
            if mode == 'discovery-only':
                # No thread, sandbox or model credentials are needed to exercise
                # the actual vendor host's registered stdio discovery.
                assert clients.connection_status(gateway,saved['id'])['last_call'] is None
                return
            thread = result(4,'thread/start',{'cwd':str(home),'ephemeral':True,'approvalPolicy':'never',
                                              'sandbox':'read-only','model':'fixture','modelProvider':'fixture'})
            params = {'threadId':thread['thread']['id'],'server':'airlock','tool':'get_private_context','arguments':{'query':''}}
            received = result(5,'mcpServer/tool/call',params)
            assert not received.get('isError') and 'Be concise' in str(received) and 'Hyderabad' not in str(received)
            gateway.revoke(saved['id'])
            denied = rpc.call(6,'mcpServer/tool/call',params)
            assert 'error' in denied or denied['result'].get('isError')

EXPECTED_TOOLS = {'privacy_status','get_private_context','search_gmail','read_gmail','stage_context_import','context_status','list_local_skills','read_local_skill','run_local_skill','prepare_private_brief','update_shared_context','request_private_task','get_private_task_result','list_private_actions','request_private_action','private_action_status','read_private_fields','prepare_private_followup','list_agent_handoffs','claim_agent_handoff','submit_agent_handoff','read_agent_handoff'}

@pytest.fixture
def serving(bundle):
    g=bundle[0]
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    app,_=mcp_app(g,port)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='critical',access_log=False))
    t=threading.Thread(target=server.run,daemon=True);t.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{port}/mcp',port
    server.should_exit=True;t.join(timeout=5)

async def check_session(s):
    await s.initialize()
    tools=(await s.list_tools()).tools
    names={t.name for t in tools}
    assert names == EXPECTED_TOOLS
    for tool in tools:
        if tool.name in ('get_private_context','search_gmail'):
            assert tool.inputSchema['properties']['query']['maxLength']==2000
    c=await s.call_tool('get_private_context',{'query':'interview'})
    assert not c.isError,c
    r=json.loads(c.content[0].text)
    assert r['execution']=={'tool':'get_private_context','status':'success'}
    assert {x['kind'] for x in r['items']}=={'memories','skills'}
    results=await s.call_tool('search_gmail',{'query':'pickup'})
    ref=json.loads(results.content[0].text)['items'][0]['ref']
    email=await s.call_tool('read_gmail',{'reference':ref})
    assert not email.isError and 'No visa decision is stated' in email.content[0].text
    denied=await s.call_tool('read_gmail',{'reference':'../../vault.enc'})
    assert denied.isError and 'HIDDEN_' not in denied.content[0].text
    assert json.loads(denied.content[0].text)['execution']=={'tool':'read_gmail','status':'error'}

def test_official_sdk_http(bundle,serving):
    token=bundle[4]() ['token'];url,port=serving
    async def run():
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token}) as client:
            async with streamable_http_client(url,http_client=client) as (read,write,_):
                async with ClientSession(read,write) as session:await check_session(session)
    asyncio.run(run())


def test_scoped_agents_over_real_mcp_http(bundle,serving):
    from privacy_layer.agent_memory import AgentMemory
    g=bundle[0];m=AgentMemory(g);url,_=serving
    a=g.create(agent='codex',purpose='Scoped MCP test',views=[],mode='automatic',approved=True)
    b=g.create(agent='mcp',purpose='Compute-only MCP test',views=[],mode='automatic',approved=True)
    m.configure(a['id'],['skills:s1'],disclose=True,compute=False)
    m.configure(b['id'],['memories:m1'],disclose=False,compute=True)
    async def client(gr):
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+gr['token']},trust_env=False) as http:
            async with streamable_http_client(url,http_client=http) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    r=await session.call_tool('get_private_context',{'query':''})
                    if gr is a:
                        assert not r.isError and 'Be concise' in r.content[0].text and 'Hyderabad' not in r.content[0].text
                    else:
                        assert r.isError and 'compute-only' in r.content[0].text
                        t=await session.call_tool('request_private_task',{'instruction':'Summarize the approved interview facts.','records':[],'route':'local'})
                        assert not t.isError and 'Hyderabad' not in t.content[0].text
                        task_id=json.loads(t.content[0].text)['task_id']
                        result=await session.call_tool('get_private_task_result',{'task_id':task_id})
                        assert not result.isError and json.loads(result.content[0].text)['text'] is None
                    denied=await session.call_tool('search_gmail',{'query':'pickup'})
                    assert denied.isError
    async def run():await asyncio.gather(client(a),client(b))
    asyncio.run(run())

def test_automatic_mode_over_real_mcp_transport(bundle,serving):
    g,s,_,_,make=bundle;grant=make(max_calls=10);g.set_automatic(grant['id'],enabled=True,approved=True)
    s.search_gmail_page=lambda q,cursor=None:{'items':[{'kind':'gmail','source_id':'e1',**s.read('gmail','e1')}],'next_cursor':None}
    url,_=serving
    async def run():
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+grant['token']}) as client:
            async with streamable_http_client(url,http_client=client) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    result=await session.call_tool('get_private_context',{'query':'interview Hyderabad'})
                    data=json.loads(result.content[0].text)
                    assert data['mode']=='automatic' and 'Hyderabad' in result.content[0].text
                    assert 'HIDDEN_FINANCE_CANARY' not in result.content[0].text
                    found=await session.call_tool('search_gmail',{'query':'pickup'})
                    ref=json.loads(found.content[0].text)['items'][0]['ref']
                    email=await session.call_tool('read_gmail',{'reference':ref})
                    assert not email.isError and 'ready for pickup' in email.content[0].text
                    assert 'HIDDEN_PASSPORT_CANARY' not in email.content[0].text
    asyncio.run(run())

def test_independent_http_clients_can_initialize_and_call_concurrently(bundle,serving):
    token=bundle[4]() ['token'];url,_=serving
    async def one():
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token}) as client:
            async with streamable_http_client(url,http_client=client) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    result=await session.call_tool('privacy_status',{})
                    assert not result.isError
                    return json.loads(result.content[0].text)['remaining_calls']
    async def run():
        remaining=await asyncio.gather(*(one() for _ in range(4)))
        assert len(set(remaining))==4
    asyncio.run(run())

def test_natural_language_query_and_explicit_upper_bound(bundle):
    from privacy_layer.core import Denied,QUERY_LIMIT
    gateway,_,_,_,make=bundle;token=make()['token']
    result=gateway.call(token,'get_private_context',{'query':'interview '+('background '*50)})
    assert {i['kind'] for i in result['items']}=={'memories','skills'}
    with pytest.raises(Denied,match='2,000 characters'):
        gateway.call(token,'get_private_context',{'query':'x'*(QUERY_LIMIT+1)})

def test_official_sdk_stdio(bundle,serving,tmp_path):
    token=bundle[4]() ['token'];url,port=serving
    p=tmp_path/'agent.token';p.write_text(token)
    params=StdioServerParameters(command=sys.executable,args=[str(Path(__file__).resolve().parents[1]/'privacy_layer/stdio.py'),'--token-file',str(p),'--port',str(port)])
    async def run():
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:await check_session(session)
    asyncio.run(run())

def test_http_auth_origin_and_host_checks(bundle,serving):
    token=bundle[4]() ['token'];url,port=serving
    r=httpx.post(url,json={});assert r.status_code==401
    r=httpx.post(url,headers={'Authorization':'Bearer '+token,'Origin':'https://evil.test'},json={});assert r.status_code==403
    r=httpx.post(url,headers={'Authorization':'Bearer '+token,'Host':'evil.test','Accept':'application/json, text/event-stream'},json={});assert r.status_code==421

def test_owner_interface_is_separate(bundle):
    g=bundle[0];token=bundle[4]() ['token']
    with TestClient(owner_app(g,'owner-secret'),base_url='http://127.0.0.1:8791') as c:
        assert c.post('/api/library',json={}).status_code==401
        assert c.post('/api/library',json={},headers={'Authorization':'Bearer '+token}).status_code==401
        assert c.post('/api/library',json={},headers={'Authorization':'Bearer owner-secret','Origin':'https://evil.test'}).status_code==403
        r=c.post('/api/library',json={},headers={'Authorization':'Bearer owner-secret'});assert r.status_code==200
        assert 'HIDDEN_FINANCE_CANARY' in r.text
        page=c.get('/');assert page.status_code==200 and "frame-ancestors 'none'" in page.headers['Content-Security-Policy']
        assert c.post('/api/library',content=b'x'*(1024*1024+1),headers={'Authorization':'Bearer owner-secret'}).status_code==413

@pytest.mark.parametrize('agent',['codex','claude-desktop','claude-code','cursor','mcp'])
def test_native_client_export_over_real_stdio(bundle,serving,tmp_path,monkeypatch,agent):
    from privacy_layer import clients
    g,s,_,_,_=bundle;_,port=serving
    s.search_gmail_page=lambda q,cursor=None:{'items':[{'kind':'gmail','source_id':'e1',**s.read('gmail','e1')}],'next_cursor':None}
    original_entry=clients.server_entry
    def entry(token_path):
        root=Path(__file__).resolve().parents[1]
        return {'command':sys.executable,'args':[str(root/'privacy_layer/stdio.py'),'--token-file',str(token_path),'--port',str(port)]}
    monkeypatch.setattr(clients,'ROOT',tmp_path/'app');monkeypatch.setattr(clients,'server_entry',entry)
    result=clients.connect(g,agent=agent,approved=True,install=agent!='mcp',home=tmp_path/'home')
    config=json.loads(result['config'])['mcpServers'][clients.SERVER]
    async def run():
        async with stdio_client(StdioServerParameters(**config)) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools=await session.list_tools()
                assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
                context=await session.call_tool('get_private_context',{'query':'interview'})
                assert not context.isError
                assert 'Hyderabad' in context.content[0].text
                assert 'PRIVATE_MEDICAL_CANARY' not in context.content[0].text
                found=await session.call_tool('search_gmail',{'query':'pickup'})
                ref=json.loads(found.content[0].text)['items'][0]['ref']
                message=await session.call_tool('read_gmail',{'reference':ref})
                assert not message.isError and 'ready for pickup' in message.content[0].text
                assert 'HIDDEN_PASSPORT_CANARY' not in message.content[0].text
                g.revoke(result['id'])
                with pytest.raises(Exception):await session.call_tool('privacy_status',{})
    asyncio.run(run())


def test_native_mcp_context_transfer_stages_only_until_owner_saves(bundle,serving):
    import re
    from privacy_layer.context import ContextHub
    g,s,_,_,make=bundle;grant=make(max_calls=8);hub=ContextHub(g.store,clock=g.clock)
    code=re.search(r'transfer_code "([^"]+)"',hub.transfer_start()['prompt'])[1]
    async def run():
        url,_=serving
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+grant['token']}) as client:
            async with streamable_http_client(url,http_client=client) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    tools=(await session.list_tools()).tools
                    tool=next(t for t in tools if t.name=='stage_context_import')
                    assert tool.annotations.readOnlyHint is False
                    result=await session.call_tool('stage_context_import',{'transfer_code':code,'memories':['Fictional Phoenix interview November 12.'],'skills':['Use the solar launch example.'],'scope':'Fictional test context only.'})
                    assert not result.isError and 'Phoenix' not in str(result)
                    assert not hub.rows()
                    p=hub.transfer_status()['preview'];saved=hub.commit(p['id'],[0,1],s.library())
                    assert saved['added']==2
                    base=s.library;s.library=lambda:base()+hub.rows()
                    g.set_automatic(grant['id'],enabled=True,approved=True)
                    result=await session.call_tool('get_private_context',{'query':'Phoenix solar interview'})
                    assert not result.isError and 'November 12' in str(result) and 'solar launch example' in str(result)
    asyncio.run(run())


@pytest.mark.parametrize('agent,keys', [
    ('codex', ('mcp_servers',)),
    ('claude-code', ('mcpServers',)),
    ('claude-desktop', ('mcpServers',)),
    ('cursor', ('mcpServers',)),
    ('muse-code', ('mcp_servers',)),
    ('gemini-cli', ('mcpServers',)),
    ('vscode', ('mcpServers',)),
    ('openclaw', ('mcp','servers')),
])
def test_new_client_profile_runs_shipped_bridge(bundle,serving,tmp_path,monkeypatch,agent,keys):
    """Use the exact command in the installed profile against a temporary gateway."""
    from privacy_layer import clients
    gateway = bundle[0]
    for key in ('CODEX_HOME','CLAUDE_CONFIG_DIR','XDG_CONFIG_HOME','GEMINI_CLI_HOME','COPILOT_HOME','OPENCLAW_CONFIG_PATH','OPENCLAW_STATE_DIR','OPENCLAW_PROFILE'):
        monkeypatch.delenv(key,raising=False)
    url, _ = serving
    install_root = tmp_path/"Mac Owner's Home/Library/Application Support/Airlock/app"
    (install_root/'.venv/bin').mkdir(parents=True)
    (install_root/'.venv/bin/python').symlink_to(sys.executable)
    (install_root/'privacy_layer').symlink_to(Path(clients.__file__).resolve().parent)
    (install_root/'release.json').write_text('{}')
    (install_root/'.private').mkdir()
    (install_root/'.private/mcp-endpoint.json').write_text(json.dumps({'mcp_url':url}))
    monkeypatch.setattr(clients,'ROOT',install_root)
    rows = clients.connection_context(gateway)['records']
    chosen = next(r for r in rows if r['ref']=='skills:s1')
    scope = clients.selected_scope(gateway,{chosen['ref']:chosen['text_hash']})
    home = tmp_path/'Mac Profile'
    result = clients.connect(gateway,agent=agent,approved=True,home=home,scope=scope)
    import tomllib
    saved = Path(result['path']).read_text()
    config = tomllib.loads(saved) if agent == 'codex' else json.loads(saved)
    for key in keys:
        config = config[key]
    entry = config['airlock']

    async def probe():
        command = StdioServerParameters(command=entry['command'], args=entry['args'], cwd=home,
                                        env={'PATH':'/usr/bin:/bin','HOME':str(home), 'HTTPS_PROXY':'http://127.0.0.1:1'})
        async with stdio_client(command) as (read,write), ClientSession(read,write) as session:
            await session.initialize()
            assert clients.connection_status(gateway,result['id'])['last_discovery'] is None
            assert 'get_private_context' in {tool.name for tool in (await session.list_tools()).tools}
            status = clients.connection_status(gateway,result['id'])
            assert status['last_discovery'] is not None
            assert status['last_call'] is None and status['last_context_read'] is None
            answer = await session.call_tool('get_private_context',{'query':''})
            assert not answer.isError
            assert 'Be concise' in answer.content[0].text and 'Hyderabad' not in answer.content[0].text
            assert clients.connection_status(gateway,result['id'])['status'] == 'verified'
            gateway.revoke(result['id'])
            with pytest.raises(Exception):
                await session.call_tool('privacy_status',{})
    asyncio.run(probe())


def test_stdio_negotiates_gateway_protocol_and_recovers_after_restart(tmp_path):
    """An existing agent process follows the new port and emits one frame per request."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    token = tmp_path/'agent.token'
    token.write_text('fictional-scoped-token')
    endpoint = tmp_path/'mcp-endpoint.json'
    root = Path(__file__).resolve().parents[1]
    received = []

    class GatewayHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            version = self.headers.get('MCP-Protocol-Version')
            received.append((request['method'], version, self.server.server_port))
            if self.headers.get('Authorization') != 'Bearer fictional-scoped-token':
                self.send_error(401)
                return
            if request['method'] == 'initialize':
                result = {'protocolVersion':'2025-11-25'}
            elif version != '2025-11-25':
                self.send_error(400)
                return
            elif 'id' not in request:
                self.send_response(202)
                self.end_headers()
                self.wfile.write(b'Accepted')
                return
            else:
                result = {'tools':[]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'jsonrpc':'2.0', 'id':request['id'], 'result':result}, indent=2).encode())

    with ExitStack() as stack:
        def start():
            server = stack.enter_context(ThreadingHTTPServer(('127.0.0.1', 0), GatewayHandler))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stack.callback(server.shutdown)
            endpoint.write_text(json.dumps({'mcp_url':f'http://127.0.0.1:{server.server_port}/mcp'}))
            return server.server_port

        first = start()
        process = stack.enter_context(subprocess.Popen(
            [sys.executable, str(root/'privacy_layer/stdio.py'), '--token-file', str(token), '--session-file', str(endpoint)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp_path, text=True,
        ))
        stack.callback(process.terminate)
        def send(method, number=None):
            data = {'jsonrpc':'2.0','method':method}
            if number is not None:
                data['id'] = number
            process.stdin.write(json.dumps(data)+'\n')
            process.stdin.flush()
            if number is not None:
                assert select.select([process.stdout], [], [], 5)[0]
                response = json.loads(process.stdout.readline())
                assert response['id'] == number
                return response
        assert send('initialize', 1)['result']['protocolVersion'] == '2025-11-25'
        send('notifications/initialized')
        assert send('tools/list', 2)['result'] == {'tools':[]}
        second = start()
        assert send('tools/list', 3)['result'] == {'tools':[]}
        assert received == [('initialize',None,first), ('notifications/initialized','2025-11-25',first),
                            ('tools/list','2025-11-25',first), ('tools/list','2025-11-25',second)]
        token.unlink()
        err = send('tools/list', 4)['error']['message']
        assert 'unavailable' in err and str(tmp_path) not in err
        token.write_text('different')
        assert 'Unlock the workspace' in send('tools/list', 5)['error']['message']


@pytest.mark.parametrize('agent,variable,args', [
    ('claude-code', 'AIRLOCK_TEST_CLAUDE_CODE', ['mcp','get','airlock']),
    ('gemini-cli', 'AIRLOCK_TEST_GEMINI_CLI', ['mcp','list']),
    ('muse-code', 'AIRLOCK_TEST_MUSE_CODE', ['mcp','get','airlock','--json']),
])
def test_installed_cli_checks_registered_server(bundle, serving, tmp_path, monkeypatch, agent, variable, args):
    """Exercise the real vendor's non-inference check in an isolated Mac profile."""
    from privacy_layer import clients

    if not os.environ.get(variable):
        pytest.skip(f'Requires an explicitly supplied {agent} binary')
    binary = Path(os.environ[variable]).resolve(strict=True)
    gateway, url = bundle[0], serving[0]
    home = tmp_path/"Mac CLI User's Home"
    root = home/'Library/Application Support/Airlock/app'
    (root/'.venv/bin').mkdir(parents=True)
    (root/'.venv/bin/python').symlink_to(sys.executable)
    (root/'privacy_layer').symlink_to(Path(clients.__file__).resolve().parent)
    (root/'.private').mkdir()
    (root/'.private/mcp-endpoint.json').write_text(json.dumps({'mcp_url':url}))
    monkeypatch.setattr(clients,'ROOT',root)
    profile_var = {'claude-code':'CLAUDE_CONFIG_DIR', 'gemini-cli':'GEMINI_CLI_HOME', 'muse-code':'XDG_CONFIG_HOME'}[agent]
    profile = str(home/'CLI configuration')
    monkeypatch.setenv(profile_var, profile)
    saved = clients.connect(gateway, agent=agent, approved=True, home=home,
                            scope={'records':[],'compute':False,'disclose':False,'proposals':False})
    before = clients.connection_status(gateway, saved['id'])
    assert saved['installed'] and before['last_initialized'] is None
    workspace = home/'Library/Caches/Airlock Agent Checks'/agent
    workspace.mkdir(parents=True)
    env = {'HOME':str(home),'PATH':os.environ['PATH'],profile_var:profile,'NO_COLOR':'1','CI':'1',
           'LANG':'en_US.UTF-8','DISABLE_TELEMETRY':'1','DISABLE_AUTOUPDATER':'1'}
    if os.environ.get('TMPDIR'):
        env['TMPDIR'] = os.environ['TMPDIR']
    if agent == 'muse-code':
        from privacy_layer import agent_launch
        env['MUSE_NO_AUTO_UPDATE'] = '1'
        registered = subprocess.run([str(binary), *args], cwd=workspace, env=env, capture_output=True,
                                    check=True, timeout=60, text=True)
        assert json.loads(registered.stdout)['name'] == 'airlock'
        assert clients.connection_status(gateway,saved['id'])['last_initialized'] is None
        monkeypatch.setenv('HOME', str(home))
        workspace.parent.chmod(0o700)
        workspace.chmod(0o700)
        monkeypatch.setattr(agent_launch, '_cli', lambda command: str(binary) if command == 'muse' else None)
        def terminal_callback(bundle_id, script):
            assert bundle_id == 'com.apple.Terminal'
            completed = subprocess.run([str(script)], env=env, input='\n', text=True, capture_output=True, timeout=60)
            assert completed.returncode == 0, 'Muse Code did not complete its offline check.'
            assert 'trust an empty Airlock folder for this run' in completed.stdout
            return True
        monkeypatch.setattr(agent_launch, '_open', terminal_callback)
        assert agent_launch._terminal('muse-code')['method'] == 'check'
        after = clients.connection_status(gateway,saved['id'])
        assert after['last_initialized'] is not None and after['last_discovery'] is not None
        assert after['last_call'] is None and after['last_context_read'] is None
        return
    def vendor_check():
        report = subprocess.run([str(binary), *args], cwd=workspace, env=env, text=True,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=90)
        assert report.returncode == 0, f'{agent} returned {report.returncode}'
        return (report.stdout + report.stderr).lower()
    transcript = vendor_check()
    if agent == 'gemini-cli':
        assert 'because this folder is untrusted' in transcript and 'disabled' in transcript
        assert clients.connection_status(gateway,saved['id'])['last_initialized'] is None
        # Reproduce selecting “Trust folder” for this disposable test workspace
        # only. The production launcher opens Gemini's own consent dialog.
        trusted = Path(profile)/'.gemini/trustedFolders.json'
        assert not trusted.exists()
        trusted.write_text(json.dumps({str(workspace.resolve()):'TRUST_FOLDER'}))
        trusted.chmod(0o600)
        transcript = vendor_check()
    # The process may print local configuration paths. Keep its raw output out of CI.
    assert 'airlock' in transcript and 'connected' in transcript and 'disconnected' not in transcript
    after = clients.connection_status(gateway, saved['id'])
    assert after['last_initialized'] is not None, f'{agent} did not authenticate and complete MCP initialization'
    assert after['last_call'] is None and after['last_context_read'] is None
    print(f'{agent}: installed vendor CLI completed MCP initialization with zero shared records and no model turn.')
