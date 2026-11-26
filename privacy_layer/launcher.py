"""Double-click lifecycle for the local service. No user data in process arguments."""
import argparse
import base64
import hmac
from http.client import HTTPException
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import stat
import uuid
import time
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.parse import urlsplit
import webbrowser

ROOT=Path(__file__).resolve().parents[1]

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def session_proof(token, challenge):
    payload = ('Airlock session v1 ' + challenge).encode('ascii')
    return base64.b64encode(hmac.digest(token.encode('ascii'), payload, 'sha256')).decode('ascii')


def probe_session(path, timeout=2):
    """Authenticate the live listener from its private local launch receipt."""
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 8192):
            return None
        record = json.loads(path.read_bytes())
        url = urlsplit(record['url'])
        if (url.scheme != 'http' or url.hostname != '127.0.0.1'
                or url.username or url.password or not url.port):
            return None
        base = f'http://127.0.0.1:{url.port}'
        opener = build_opener(ProxyHandler({}), NoRedirect())
        if record.get('session_check') == 1:
            # The process that currently holds the port proves its identity first.
            challenge = str(uuid.uuid4())
            request = Request(base + '/_airlock/session', headers={'X-Airlock-Challenge':challenge})
            with opener.open(request, timeout=timeout) as response:
                expected = session_proof(record['owner_token'], challenge).encode('ascii')
                if response.status == 200 and hmac.compare_digest(response.read(65), expected):
                    return record
        else:
            # Existing installations predate the challenge endpoint.
            request = Request(base + '/api/state', data=b'{}', headers={
                'Authorization':'Bearer '+record['owner_token'], 'Content-Type':'application/json'})
            with opener.open(request, timeout=timeout) as response:
                if response.status == 200:
                    return record
    except (HTTPException, KeyError, OSError, ValueError, TypeError):
        pass
    return None


def start():
    state=ROOT/'.private';state.mkdir(mode=0o700,exist_ok=True)
    with open(state/'launcher.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        record=probe_session(state/'launch.json')
        if record:
            if record.get("mode")!="safe-test":raise RuntimeError("An older personal service is running. Quit Airlock completely, then reopen this version to start the isolated test.")
            return record
        log=state/'service.log';fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'ab') as out:
            args=[sys.executable,'-m','privacy_layer.server','--safe-start']
            if (ROOT/'release.json').exists():
                args += ['--owner-port', '0', '--mcp-port', '0']
            process = subprocess.Popen(args,cwd=ROOT,stdout=out,stderr=out,stdin=subprocess.DEVNULL,start_new_session=True)
        for _ in range(80):
            time.sleep(.15)
            record=probe_session(state/'launch.json')
            if record:
                return record
            if process.poll() is not None:
                break
        raise RuntimeError('Could not start Airlock. Open Airlock again to restart its local service.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--no-open',action='store_true');a=p.parse_args()
    record=start()
    if record.get('mode')=='safe-test':
        if not a.no_open:
            if sys.platform=='darwin':subprocess.run(['/usr/bin/open',record['url']],check=True)
            else:webbrowser.open(record['url'])
        print('Airlock is ready in an isolated fictional test workspace.')
        return
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
