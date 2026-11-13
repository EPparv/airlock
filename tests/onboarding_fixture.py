"""Real owner/MCP/OAuth services with an explicitly fictional Google transport."""
import asyncio,json,sys
from pathlib import Path
import uvicorn
from privacy_layer import sources,server,clients
from privacy_layer.core import EncryptedStore,Gateway
from test_portable import GoogleFixture

root=Path(sys.argv[1]);owner_port=int(sys.argv[2]);mcp_port=int(sys.argv[3]);home=root/'home';home.mkdir()
runtime=root/'runtime';runtime.mkdir();(runtime/'release.json').write_text('{}')
real=Path(__file__).resolve().parents[1]
(runtime/'.venv').symlink_to(real/'.venv');(runtime/'privacy_layer').symlink_to(real/'privacy_layer')
(runtime/'.private').mkdir()
(runtime/'.private/launch.json').write_text(json.dumps({'mcp_url':f'http://127.0.0.1:{mcp_port}/mcp'}))
sources.bundled_client=lambda:({'client_id':'fictional.apps.googleusercontent.com','client_secret':'fictional-desktop-identity'},'')
s=sources.LocalSources(key=b't'*32,context_home=home,transport=GoogleFixture())
st=EncryptedStore(root/'context.enc',s.key);s.connection_store=st;g=Gateway(st,s);clients.ROOT=runtime
async def serve():
 apps=[(server.owner_app(g,'fictional-setup-owner',owner_port),owner_port),(server.mcp_app(g,mcp_port)[0],mcp_port)]
 await asyncio.gather(*(uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=p,log_level='critical',access_log=False)).serve() for app,p in apps))
asyncio.run(serve())
