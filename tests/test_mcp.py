import asyncio
import json
import socket
import sys
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
    assert names=={'privacy_status','get_private_context','search_gmail','read_gmail','stage_context_import','context_status','list_local_skills','read_local_skill','run_local_skill','prepare_private_brief','update_shared_context','request_private_task','get_private_task_result'}
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
                tools=await session.list_tools();assert len(tools.tools)==13
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
