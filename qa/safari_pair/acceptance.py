"""Run the shipped Airlock phone companion through Mobile Safari on a disposable Mac."""
import functools
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CLIENT = Path(__file__).resolve().parent / 'client'
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import uvicorn
from smoke_iphone import certificates, choose_phone, output, run
from phone_fixture import FictionalSources
from privacy_layer.core import Gateway, EncryptedStore, digest
from privacy_layer.device_apps import ExampleApps
from privacy_layer.phone_companion import PhoneCompanion
from privacy_layer.remote_clients import BridgeApp
from privacy_layer.workspace import Workspace

class SafariWitness:
    def __init__(self, app, start, origin):
        self.app = app
        self.start = start
        self.origin = origin
        self.pair_count = None
        self.session = None
        self.events = []

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        path = scope['path']
        agent = headers.get(b'user-agent', b'')
        if path == '/qa/start' and scope['method'] == 'GET':
            ok = self.start()
            await send({'type':'http.response.start','status':204 if ok else 410,'headers':[(b'cache-control',b'no-store')]})
            await send({'type':'http.response.body','body':b''})
            return
        mobile = b'Mobile/' in agent and b'Safari/' in agent
        known = {'/phone','/phone/pair','/phone/context','/phone/actions','/phone/request','/phone/disconnect','/phone/status'}
        async def watch(event):
            if event['type'] == 'http.response.start' and path in known:
                origin = headers.get(b'origin')
                origin_kind = {None:'absent', b'null':'null',self.origin.encode('ascii'):'same-origin'}.get(origin,'other')
                print('Airlock QA HTTP:',scope['method'],path,event['status'],'Origin:',origin_kind,
                      'Mobile Safari:',mobile,'JSON:',b'application/json' in headers.get(b'content-type',b''),
                      'Fetch-Site:',{None:'absent',b'same-origin':'same-origin'}.get(headers.get(b'sec-fetch-site'),'other'),flush=True)
                if mobile:
                    self.events.append((path,event['status']))
                    if path == '/phone/context' and event['status'] == 200:
                        self.session = headers.get(b'authorization')
            if mobile and path == '/phone/pair' and event['type'] == 'http.response.body':
                try:
                    self.pair_count = json.loads(event.get('body',b'{}')).get('count')
                except (ValueError,TypeError):
                    pass
            await send(event)
        return await self.app(scope, receive, watch)

def ensure(ok, message):
    if not ok:
        raise RuntimeError(message)

def xcode(args, tmp, stage, markers=()):
    with open(tmp / (stage + '.log'), 'w+') as f:
        rc = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT, timeout=540).returncode
        f.seek(0)
        log = f.read()
    for hint in re.findall(r'AIRLOCK_SAFARI_HINT ([a-z_0-9]+)',log):
        print('Mobile Safari diagnosis:', hint)
    for mark in markers:
        if 'AIRLOCK_SAFARI_PAIR ' + mark in log:
            print('Mobile Safari:', mark, flush=True)
    if rc:
        # Avoid XCTest transcripts or screenshots. Only emit known marker and allowlisted error classes.
        known = ['Connect to Mac in Mobile Safari', 'Phone did not receive its Mac scope', 'Approved synthetic result was missing',
                 'Action did not reach Mac approval queue','Disconnect did not complete on the Mac','query field','list assigned actions',
                 'request Mac approval','submit query','Unable to find a destination','Failed to launch','not hittable','timed out',
                 'Signing for','requires a development team','could not be found','missing required','No such module']
        msg = [s for s in known if s.lower() in log.lower()]
        safe_errors = [line.split('error:',1)[1].strip()[:450] for line in log.splitlines() if stage == 'build' and 'error:' in line.lower() and 'error:' in line]
        for line in safe_errors[:5]:
            print('Build diagnostic:', line)
        raise RuntimeError(f'{stage} failed with {rc}; safe diagnostics: {msg}')
    ensure(all('AIRLOCK_SAFARI_PAIR ' + m in log for m in markers),'Missing XCTest acceptance markers')

def post(origin, ca, path, data, session=None):
    parsed = urlsplit(origin)
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, context=ssl.create_default_context(cafile=str(ca)),timeout=5)
    heads = {'Origin':origin, 'Content-Type':'application/json','Sec-Fetch-Site':'same-origin'}
    if session:
        heads['Authorization'] = session.decode('ascii')
    try:
        conn.request('POST',path,json.dumps(data),heads)
        resp=conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()

def main():
    runtime, device_type = choose_phone()
    device = output('xcrun','simctl','create','Airlock Safari Pair QA',device_type,runtime)
    try:
        with tempfile.TemporaryDirectory() as d:
            tmp=Path(d)
            run('xcrun','simctl','boot',device)
            ca,cert=certificates(tmp)
            run('xcrun','simctl','bootstatus',device,'-b',timeout=380)
            run('xcrun','simctl','keychain',device,'add-root-cert',ca)
            run('xcodegen','generate','--spec',CLIENT/'project.yml',cwd=CLIENT)
            xargs = ['xcodebuild','-project',str(CLIENT/'SafariPairProbe.xcodeproj'),'-scheme','PairAcceptance',
                     '-destination','id='+device, '-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1',
                     '-derivedDataPath',str(tmp/'Derived'),'CODE_SIGNING_ALLOWED=NO']
            xcode(xargs+['build-for-testing'],tmp,'build')
            src=FictionalSources()
            vault=Gateway(EncryptedStore(tmp/'synthetic.enc',secrets.token_bytes(32)),src)
            vault.device_apps=ExampleApps()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',39791))
                sock.listen(32)
                port=sock.getsockname()[1]
                origin='https://127.0.0.1:'+str(port)
                with vault.store.transaction() as state:
                    state['remote_bridge']={'enabled':True,'port':port,'origin':origin}
                phone=PhoneCompanion(vault)
                ref=src.library()[0]
                issued = {}
                def start():
                    if issued: return False
                    offer=phone.owner('phone-create',{'approved':True,'selection':{'memories:schedule':digest(ref['text'])}})
                    ws=Workspace(vault)
                    action=ws.create('email','Review fictional follow-up',[offer['id']],
                              {'recipients':'review@example.test','subject':'Fictional rehearsal','body':'Fixture only.'})
                    issued.update(offer=offer,action=action)
                    def launch():
                        rc=subprocess.run(['xcrun','simctl','openurl',device,offer['url']],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode
                        print('Fresh link sent to active Mobile Safari:',rc==0, flush=True)
                    threading.Timer(.2,launch).start()
                    return True
                witness=SafariWitness(BridgeApp(lambda:vault,port),start,origin)
                server=uvicorn.Server(uvicorn.Config(witness,ssl_keyfile=str(tmp/'site.key'),ssl_certfile=str(cert),
                       log_level='error',access_log=False,proxy_headers=False))
                th=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); th.start()
                try:
                    wait=time.monotonic()+10
                    while not server.started and time.monotonic()<wait: time.sleep(.1)
                    ensure(server.started,'Mac gateway did not start')
                    marks=('connected','scoped_read','pending_mac_approval','disconnected')
                    xcode(xargs+['test-without-building'],tmp,'ui',marks)
                    ensure(issued and witness.pair_count==1,'Missing the Mac-confirmed selected record count')
                    offer,action=issued['offer'],issued['action']
                    expect=('/phone/pair','/phone/context','/phone/actions','/phone/request','/phone/disconnect')
                    ensure(all((p,200) in witness.events for p in expect),'Mobile Safari did not complete every successful HTTP action')
                    ensure(witness.session is not None,'Missing HTTP witness for real Mobile Safari')
                    with vault.store.transaction() as state:
                        real=state['device_actions'][action['id']]
                        ensure(real['state']=='pending' and real['applicant']==offer['id'] and not real['completed'],
                               'Phone did not queue a single approval without executing it')
                        ensure(state['grants'][offer['id']]['revoked'],'The Mac did not revoke the phone grant')
                    ensure(phone.owner('phone-state',{})['devices']==[],'Mac still lists a paired phone')
                    ensure(post(origin,ca,'/phone/context',{'query':'Cypress'},witness.session)==401,'Previous session remained usable')
                    ensure(post(origin,ca,'/phone/pair',{'code':offer['url'].split('#pair=')[1]})==403,'Consumed link was reusable')
                    print('Verified on Mac: pending approval, no action execution, revoked phone, old session HTTP 401, used link HTTP 403.', flush=True)
                    receipt={'client':'Apple Mobile Safari, iOS Simulator','runtime':runtime,'physical_device':False,
                             'production_airlock_gateway':True,'synthetic_selected_records':1,'scoped_read':True,
                             'safari_ui_request_pending':True,'action_executed':False,'mac_verified_revoked':True,
                             'old_session_http':401,'consumed_link_http':403}
                    Path('pairing-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
                    witness.session=None
                finally:
                    server.should_exit=True
                    th.join(timeout=12)
    finally:
        subprocess.run(['xcrun','simctl','shutdown',device],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['xcrun','simctl','delete',device],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

if __name__=='__main__':
    main()
