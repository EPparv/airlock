"""Production ASGI routes for DOM QA. Ollama responses explicitly mocked here."""
import json
import sys
from pathlib import Path
import httpx
from starlette.testclient import TestClient
from privacy_layer.memory_demo import make_gateway, DemoBoundary
from privacy_layer.server import owner_app
from privacy_layer.local_provider import LocalProvider

request=json.load(sys.stdin);sent=[]
def handle(req):
    if req.url.path=='/api/show':return httpx.Response(200,json={'details':{'format':'gguf'},'capabilities':['completion'],'model_info':{'general.architecture':'qwen','qwen.context_length':8192}})
    sent.append(req.content.decode())
    return httpx.Response(200,json={'model':json.loads(req.content)['model'],'done':True,'done_reason':'stop','message':{'content':'MOCK AI OUTPUT: Hi Maya, can we schedule the Northstar walkthrough Thursday?'}})
LocalProvider.client=lambda self:httpx.AsyncClient(transport=httpx.MockTransport(handle),trust_env=False)
g=make_gateway(Path(sys.argv[1]))
with TestClient(DemoBoundary(owner_app(g,'test-owner')),base_url='http://127.0.0.1:8791') as c:
    r=c.post(request['url'],json=request.get('body',{}),headers={'Authorization':'Bearer test-owner'})
    print(json.dumps({'status':r.status_code,'body':r.json(),'outbound':sent}))
