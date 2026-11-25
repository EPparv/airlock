import asyncio
import json
import os
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


@pytest.mark.skipif(not os.environ.get('AIRLOCK_TEST_CODEX'), reason='Requires an explicitly supplied Codex binary')
def test_installed_codex_daemon_reloads_scoped_connection(bundle, serving, tmp_path, monkeypatch):
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
        shim = home/'Applications/Codex.app/Contents/Resources/codex'
        shim.parent.mkdir(parents=True); shim.symlink_to(binary)
        root = tmp_path/'installed app'
        (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').symlink_to(sys.executable)
        (root/'privacy_layer').symlink_to(Path(clients.__file__).parent)
        (root/'.private').mkdir(); (root/'release.json').write_text('{}')
        (root/'.private/launch.json').write_text(json.dumps({'mcp_url':serving[0]}))
        monkeypatch.setattr(clients, 'ROOT', root)
        control = profile/'app-server-control/app-server-control.sock'

        async def check():
            daemon = await asyncio.create_subprocess_exec(str(binary), 'app-server', '--listen','unix://',
                cwd=home, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proxy = None
            try:
                for _ in range(200):
                    if control.is_socket() or daemon.returncode is not None: break
                    await asyncio.sleep(.05)
                assert control.is_socket(), 'The supplied Codex daemon did not expose its control socket.'
                proxy = await asyncio.create_subprocess_exec(str(binary),'app-server','proxy','--sock',str(control),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=home, limit=2*1024*1024)
                async def request(number, method, params):
                    proxy.stdin.write((json.dumps({'id':number,'method':method,'params':params})+'\n').encode())
                    await proxy.stdin.drain()
                    while True:
                        line = await proxy.stdout.readline()
                        assert line, 'Codex closed the test proxy.'
                        reply = json.loads(line)
                        if reply.get('id')==number: return reply
                assert 'result' in await request(1,'initialize',{'clientInfo':{'name':'airlock_test','version':'1'},
                    'capabilities':{'experimentalApi':True}})
                proxy.stdin.write(b'{"method":"initialized"}\n')
                initial=(await request(2,'mcpServerStatus/list',{'detail':'toolsAndAuthOnly'}))['result']['data']
                assert not any(r['name']=='airlock' for r in initial)
                selected=next(r for r in clients.connection_context(gateway)['records'] if r['ref']=='skills:s1')
                scope=clients.selected_scope(gateway,{selected['ref']:selected['text_hash']})
                saved=await asyncio.to_thread(clients.connect,gateway,agent='codex',approved=True,home=home,scope=scope)
                assert saved['reload_requested'] and Path(saved['path'])==profile/'config.toml'
                current=(await request(3,'mcpServerStatus/list',{'detail':'toolsAndAuthOnly'}))['result']['data']
                assert 'get_private_context' in next(r['tools'] for r in current if r['name']=='airlock')
                thread=await request(4,'thread/start',{'cwd':str(home),'ephemeral':True,'approvalPolicy':'never',
                    'sandbox':'read-only','model':'fixture','modelProvider':'fixture'})
                params={'threadId':thread['result']['thread']['id'],'server':'airlock','tool':'get_private_context',
                        'arguments':{'query':''}}
                received=(await request(5,'mcpServer/tool/call',params))['result']
                assert not received.get('isError') and 'Be concise' in str(received) and 'Hyderabad' not in str(received)
                gateway.revoke(saved['id'])
                denied=await request(6,'mcpServer/tool/call',params)
                assert 'error' in denied or denied['result'].get('isError')
            finally:
                for child in (proxy, daemon):
                    if child and child.returncode is None:
                        child.kill(); await child.wait()
        asyncio.run(asyncio.wait_for(check(), timeout=60))

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
    ('muse-code', ('mcp_servers',)),
    ('gemini-cli', ('mcpServers',)),
    ('vscode', ('mcpServers',)),
    ('openclaw', ('mcp','servers')),
])
def test_new_client_profile_runs_shipped_bridge(bundle,serving,tmp_path,monkeypatch,agent,keys):
    """Use the exact command in the installed profile against a temporary gateway."""
    from privacy_layer import clients
    gateway = bundle[0]
    for key in ('XDG_CONFIG_HOME','COPILOT_HOME','OPENCLAW_CONFIG_PATH','OPENCLAW_STATE_DIR','OPENCLAW_PROFILE'):
        monkeypatch.delenv(key,raising=False)
    url, _ = serving
    install_root = tmp_path/'Airlock App'
    (install_root/'.venv/bin').mkdir(parents=True)
    (install_root/'.venv/bin/python').symlink_to(sys.executable)
    (install_root/'privacy_layer').symlink_to(Path(clients.__file__).resolve().parent)
    (install_root/'release.json').write_text('{}')
    (install_root/'.private').mkdir()
    (install_root/'.private/launch.json').write_text(json.dumps({'mcp_url':url}))
    monkeypatch.setattr(clients,'ROOT',install_root)
    rows = clients.connection_context(gateway)['records']
    chosen = next(r for r in rows if r['ref']=='skills:s1')
    scope = clients.selected_scope(gateway,{chosen['ref']:chosen['text_hash']})
    result = clients.connect(gateway,agent=agent,approved=True,home=tmp_path/'profile',scope=scope)
    config = json.loads(Path(result['path']).read_text())
    for key in keys:
        config = config[key]
    entry = config['airlock']

    async def probe():
        command = StdioServerParameters(command=entry['command'],args=entry['args'])
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
