"""Double-click lifecycle for the local service. No user data in process arguments."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import socket
import time
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.parse import urlsplit
import webbrowser

ROOT=Path(__file__).resolve().parents[1]

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def start():
    state=ROOT/'.private';state.mkdir(mode=0o700,exist_ok=True)
    with open(state/'launcher.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        def running():
            try:
                record=json.loads((state/'launch.json').read_text())
                u=urlsplit(record['url'])
                if u.scheme!='http' or u.hostname!='127.0.0.1' or u.username or u.password or not u.port:return None
                r=Request(f'http://127.0.0.1:{u.port}/api/state',data=b'{}',headers={'Authorization':'Bearer '+record['owner_token'],'Content-Type':'application/json'})
                with build_opener(ProxyHandler({}),NoRedirect()).open(r,timeout=2) as response:
                    if response.status==200:return record
            except Exception:return None
        record=running()
        if record:return record
        log=state/'service.log';fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'ab') as out:
            args=[sys.executable,'-m','privacy_layer.server']
            if (ROOT/'release.json').exists():
                with socket.socket() as owner_socket,socket.socket() as mcp_socket:
                    owner_socket.bind(('127.0.0.1',0));mcp_socket.bind(('127.0.0.1',0))
                    args+=['--owner-port',str(owner_socket.getsockname()[1]),'--mcp-port',str(mcp_socket.getsockname()[1])]
            subprocess.Popen(args,cwd=ROOT,stdout=out,stderr=out,stdin=subprocess.DEVNULL,start_new_session=True)
        for _ in range(80):
            time.sleep(.15);record=running()
            if record:return record
        raise RuntimeError('Could not start Airlock. Check that the desktop app can open your saved library, and that ports 8791 and 8792 are free.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--no-open',action='store_true');a=p.parse_args()
    record=start()
    # Restoring an already approved connection changes neither its scope nor
    # lifetime. Expired/revoked grants remain closed and require owner review.
    try:
        from .sources import LocalSources
        from .core import EncryptedStore,Gateway
        from .setup import saved_dot_available,restore_dot
        sources=LocalSources(context_home=os.environ.get('PRIVATE_AI_PROFILE_HOME'))
        gateway=Gateway(EncryptedStore(ROOT/'.private/connections.enc',sources.key),sources)
        if saved_dot_available(gateway):restore_dot(gateway)
    except Exception:
        print('Dot needs attention. Review its access or reconnect in the screen that opens.')
    if not a.no_open:
        if sys.platform=='darwin':subprocess.run(['/usr/bin/open',record['url']],check=True)
        else:webbrowser.open(record['url'])
    print('Airlock is running on this Mac.')

if __name__=='__main__':main()
