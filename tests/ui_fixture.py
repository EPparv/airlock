"""Isolated browser-test owner service; never opens the personal vault."""
import sys
import asyncio
import time
from pathlib import Path
import uvicorn
from conftest import Sources
from privacy_layer.core import EncryptedStore,Gateway
from privacy_layer import server,clients

root=Path(sys.argv[1]);port=int(sys.argv[2]);sources=Sources()
for i in range(3,169):sources.data['memories',f'm{i}']={'text':f'Fictional project background item {i}.','device_only':False}
for i in range(2,40):sources.data['skills',f's{i}']={'text':f'Writing skill {i}: prefer concise, evidenced answers.','device_only':False}
sources.gmail_state=lambda:{'configured':True,'sign_in':'connected','account':'fictional@example.test'}
sources.google=lambda path:{'messagesTotal':1}
clients.ROOT=root/'runtime'
gateway=Gateway(EncryptedStore(root/'test.enc',b'x'*32),sources)
from privacy_layer.context import ContextHub
sources.context_home=root/'home'
base_library=sources.library;base_read=sources.read
sources.library=lambda:base_library()+ContextHub(gateway.store,sources.context_home).rows()
def read_context(kind,identifier):
    if (kind,identifier) in sources.data:return base_read(kind,identifier)
    row=next(x for x in sources.library() if x['kind']==kind and x['source_id']==identifier)
    return {'text':row['text'],'device_only':row.get('device_only',False)}
sources.read=read_context
note=root/'home/.claude/projects/fictional/memory/MEMORY.md';note.parent.mkdir(parents=True,exist_ok=True);note.write_text('Fictional linked interview is on November 16.')
grant=gateway.create(agent='dot',purpose='Fictional test connection',views=[],mode='automatic',approved=True)
gateway.call(grant['token'],'get_private_context',{'query':'interview'})
real_connect=server.connect
def fixture_connect(g,**kwargs):
    kwargs.pop('home',None)
    return real_connect(g,home=root/'home',**kwargs)
server.connect=fixture_connect
async def serve():
    apps=[(server.owner_app(gateway,'fictional-ui-owner',port),port)]
    if len(sys.argv)>3:
        mcp_port=int(sys.argv[3]);apps.append((server.mcp_app(gateway,mcp_port)[0],mcp_port))
    await asyncio.gather(*(uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=p,log_level='critical',access_log=False)).serve() for app,p in apps))
asyncio.run(serve())
