"""Run the existing Airlock owner UI with an isolated, fictional-only store.

No original vault/Keychain, real Gmail, agent tokens, MCP listener or imports.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import webbrowser

from starlette.responses import JSONResponse
import uvicorn

from .core import Gateway, EncryptedStore
from .server import owner_app


class DemoSources:
    demo_only = True
    def __init__(self, home): self.context_home = home
    def library(self): return []
    def protected(self): return []
    def gmail_state(self): return {'configured':False, 'sign_in':'not_connected'}


class DemoOnly:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        path = scope.get('path','')
        if path.startswith('/api/') and not path.startswith('/api/near-') and path not in ('/api/dashboard','/api/state'):
            return await JSONResponse({'error':'Only the fictional founder workflow is enabled in this demo process.'},status_code=403)(scope,receive,send)
        return await self.app(scope, receive, send)


def make_app(state, token, port):
    state = Path(state); state.mkdir(parents=True,exist_ok=True,mode=0o700)
    key_file = state/'demo.key'
    if not key_file.exists():
        fd=os.open(key_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out: out.write(secrets.token_bytes(32))
    gateway=Gateway(EncryptedStore(state/'demo.enc',key_file.read_bytes()),DemoSources(state/'empty-home'))
    from .founder_demo import FounderDemo
    demo=FounderDemo(gateway)
    if not demo.state()['loaded']:demo.reset()
    return DemoOnly(owner_app(gateway,token,port))


class DemoServer(uvicorn.Server):
    """Open the private launch link only once the listener is ready."""
    def __init__(self, config, state, token, port, open_browser=True):
        super().__init__(config)
        self.state, self.token, self.port = state, token, port
        self.open_browser = open_browser

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if not self.started:
            return
        url=f'http://127.0.0.1:{self.port}/#'+self.token
        fd=os.open(self.state/'launch.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as out:json.dump({'url':url},out)
        print(f'Founder demo ready on 127.0.0.1:{self.port}. Local AI selected; approval is required before generation. Press Ctrl+C to stop.',flush=True)
        if self.open_browser:
            import asyncio
            opened=await asyncio.to_thread(webbrowser.open,url)
            if not opened:
                print('Browser did not open. Reopen the saved private link with Run-NEAR-Demo.command --open-existing.',flush=True)


def main():
    parser=argparse.ArgumentParser(description='Airlock fictional NEAR founder demo')
    parser.add_argument('--state',type=Path,default=Path('.near-demo'))
    parser.add_argument('--port',type=int,default=8795)
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--open-existing',action='store_true',help='Reopen the last private launch link without starting another server')
    args=parser.parse_args()
    if args.open_existing:
        saved=args.state/'launch.json'
        if not saved.exists():parser.error('No previous demo launch. Start the demo first.')
        from urllib.parse import urlsplit
        url=json.loads(saved.read_text())['url']; parsed=urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.fragment:
            parser.error('Invalid saved demo address.')
        webbrowser.open(url)
        return
    token=secrets.token_urlsafe(32)
    # Bind before touching state or launch.json. Port 0 selects a free local port.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        try:listener.bind(('127.0.0.1',args.port))
        except OSError:
            parser.error('Cannot open the local demo port. Try --port 0 for a free port, or check local runtime restrictions.')
        port=listener.getsockname()[1]
        app=make_app(args.state,token,port)
        config=uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='error')
        DemoServer(config,args.state,token,port,not args.no_open).run(sockets=[listener])


if __name__=='__main__': main()
