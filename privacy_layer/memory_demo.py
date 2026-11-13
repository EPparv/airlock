"""Fictional cross-agent walkthrough using the real gateway and encrypted store.

No provider fixture is substituted for AI output. The two browser clients are
explicit simulators. The MCP listener also accepts real clients with independent
tokens stored locally in this isolated demo directory.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import webbrowser

import uvicorn
from starlette.responses import JSONResponse, RedirectResponse

from .agent_memory import AgentMemory
from .context import ContextHub
from .core import Denied, EncryptedStore, Gateway
from .server import owner_app, mcp_app

RECORDS = [
    {'kind':'memories','source_id':'demo-meeting','text':'Fictional founder: Alex leads Northstar, a workflow tool. Investor Maya asked for a product walkthrough on Thursday. Follow up with two possible meeting times.','origin':'Fictional meeting notes','device_only':False},
    {'kind':'skills','source_id':'demo-style','text':'Writing style: use plain language, keep follow-ups under 120 words, and end with one clear next step.','origin':'Follow-up writing skill','device_only':False},
    {'kind':'memories','source_id':'demo-project','text':'Northstar engineering uses Python. The next milestone is a read-only calendar integration.','origin':'Fictional engineering context','device_only':False},
    {'kind':'memories','source_id':'demo-finance','text':'Never share. Fictional confidential reserve: FINANCE-ORCHID-9247.','origin':'Fictional financial note','device_only':True},
]


class MemoryDemoSources:
    memory_demo = True
    def __init__(self, store): self.store=store; self.context_home=store.path.parent/'empty-home'
    def library(self): return [dict(r) for r in RECORDS]+ContextHub(self.store,home=self.context_home).rows()
    def protected(self):
        with self.store.transaction() as d:return d.get('automatic_private_phrases', [])
    def read(self,kind,identifier):
        return next(r for r in self.library() if r['kind']==kind and r['source_id']==identifier)
    def gmail_state(self):return {'configured':False,'sign_in':'not_connected'}


def reset_demo(g):
    if not getattr(g.sources,'memory_demo',False): raise Denied('Reset is only available in the isolated fictional demo.')
    with g.store.transaction() as d:
        if any(t['status'] in ('verifying','dispatched') for t in d.get('private_tasks',{}).values()):
            raise Denied('Wait for the current generation to finish before resetting.')
        for key in ('grants','memory_proposals','private_tasks','shared_context','memory_policy','context_batches','context_clock'):
            d[key]={}
        d['context_changes']=[]
        d['audit']=[];d['audit_head']='0'*64
    agents={}
    for name, records in [('codex',['skills:demo-style','memories:demo-project']),('ironclaw',['skills:demo-style','memories:demo-meeting'])]:
        grant=g.create(agent=name,purpose='Fictional cross-agent demonstration',views=[],approved=True,mode='automatic',max_calls=1000,lifetime=86400)
        AgentMemory(g).configure(grant['id'], records, disclose=True,compute=True,proposals=True)
        agents[name]=grant
    with g.store.transaction() as d:d['memory_demo_agents']=agents
    for name, grant in agents.items():
        write_private(g.store.path.parent/(name+'.token'),grant['token'])
    return {'reset':True,'message':'Fictional data reset. Previous demo tokens revoked.'}


def demo_call(g, agent, tool, args):
    if not getattr(g.sources,'memory_demo',False): raise Denied('Not a demo workspace.')
    with g.store.transaction() as d:a=d.get('memory_demo_agents',{}).get(agent)
    if not a:raise Denied('Choose one of the fictional agent connections.')
    if tool not in ('get_private_context','context_status','update_shared_context','request_private_task','get_private_task_result'):
        raise Denied('Unsupported walkthrough action.')
    return g.call(a['token'],tool,args)


class DemoBoundary:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        path=scope.get('path','')
        if path=='/':return await RedirectResponse('/memory')(scope,receive,send)
        allowed=('memory-state','memory-scope','memory-policy','memory-decide','memory-send','memory-release','memory-forget','memory-local-check','memory-demo-reset','memory-demo-call','revoke')
        if path.startswith('/api/') and path[5:] not in allowed:
            return await JSONResponse({'error':'Only fictional shared-memory operations are enabled here.'},status_code=403)(scope,receive,send)
        return await self.app(scope,receive,send)


def write_private(path, value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out:out.write(value)


def make_gateway(state):
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=state/'demo.key'
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:out.write(secrets.token_bytes(32))
    store=EncryptedStore(state/'memory.enc',path.read_bytes())
    g=Gateway(store,MemoryDemoSources(store))
    with store.transaction() as d:loaded=bool(d.get('memory_demo_agents'))
    if not loaded:reset_demo(g)
    return g


def main():
    p=argparse.ArgumentParser(description='Airlock: shared local memory for independent agents')
    p.add_argument('--state',type=Path,default=Path('.agent-demo'))
    p.add_argument('--port',type=int,default=0)
    p.add_argument('--mcp-port',type=int,default=0)
    p.add_argument('--no-open',action='store_true')
    a=p.parse_args();g=make_gateway(a.state);token=secrets.token_urlsafe(32)
    with socket.socket() as ui_socket, socket.socket() as mcp_socket:
        ui_socket.bind(('127.0.0.1',a.port));mcp_socket.bind(('127.0.0.1',a.mcp_port))
        port=ui_socket.getsockname()[1];mp=mcp_socket.getsockname()[1]
        app,_=mcp_app(g,mp)
        owner=DemoBoundary(owner_app(g,token,port))
        url=f'http://127.0.0.1:{port}/memory#'+token
        write_private(a.state/'launch.json',json.dumps({'url':url,'owner_token':token,'mcp_url':f'http://127.0.0.1:{mp}/mcp'}))
        with g.store.transaction() as d:agents=dict(d['memory_demo_agents'])
        for name,grant in agents.items():
            path=(a.state/(name+'.token')).resolve();write_private(path,grant['token'])
            if name=='ironclaw':
                from .ironclaw_adapter import manifest
                write_private(a.state/'ironclaw-manifest.toml.example',manifest())
            else:
                write_private(a.state/(name+'-mcp.json'),json.dumps({'mcpServers':{'airlock':{'command':sys.executable,'args':[str(Path(__file__).with_name('stdio.py').resolve()),'--token-file',str(path),'--port',str(mp)]}}},indent=2))
        async def serve():
            servers=[uvicorn.Server(uvicorn.Config(x,host='127.0.0.1',log_level='error',access_log=False)) for x in (owner,app)]
            async def open_when_ready():
                while not all(s.started for s in servers):await asyncio.sleep(.05)
                print(f'Airlock ready at http://127.0.0.1:{port}/memory. Fictional data only. Press Ctrl+C to stop.',flush=True)
                if not a.no_open:await asyncio.to_thread(webbrowser.open,url)
            await asyncio.gather(servers[0].serve(sockets=[ui_socket]),servers[1].serve(sockets=[mcp_socket]),open_when_ready())
        asyncio.run(serve())


if __name__=='__main__':main()
