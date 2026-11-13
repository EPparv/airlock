"""JSON stdin/out bridge to actual ASGI routes for DOM QA, without sockets."""
import json
import sys
import os
from starlette.testclient import TestClient
from privacy_layer.demo_server import make_app

request=json.load(sys.stdin)
outbound=[]
if os.environ.get('AIRLOCK_DOM_MOCK_LOCAL')=='1':
    # Test-only HTTP mock. No such switch exists in production code.
    import httpx
    import privacy_layer.founder_demo as module
    from privacy_layer.local_provider import LocalProvider,DEFAULT_LOCAL_MODEL
    def handle(req):
        outbound.append({'url':str(req.url),'body':req.content.decode()})
        if req.url.path=='/api/show':return httpx.Response(200,json={'details':{'format':'gguf'},'capabilities':['completion'],'model_info':{'general.architecture':'qwen3','qwen3.context_length':32768}})
        return httpx.Response(200,json={'model':DEFAULT_LOCAL_MODEL,'done':True,'message':{'content':'Mocked Ollama draft for frontend tests. Thursday walkthrough.'}})
    module.LocalProvider=lambda:LocalProvider(httpx.MockTransport(handle))
app=make_app(sys.argv[1],'fixture-owner',8795)
with TestClient(app,base_url='http://127.0.0.1:8795') as client:
    response=client.post(request['url'],json=request.get('body',{}),headers={
        'Authorization':'Bearer fixture-owner','Origin':'http://127.0.0.1:8795'})
    print(json.dumps({'status':response.status_code,'body':response.json(),'outbound':outbound}))
