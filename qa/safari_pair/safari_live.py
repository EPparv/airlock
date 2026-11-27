"""QA-only driver in genuine Mobile Safari, scoped to this runner's loopback."""
from pathlib import Path
import json, os, secrets, socket, subprocess, tempfile, threading, time
from acceptance import ROOT, FictionalSources, ExampleApps, Gateway, EncryptedStore, PhoneCompanion, Workspace, BridgeApp, SafariWitness, certificates, choose_phone, digest, ensure, output, post, run, uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

STAGES=('boot','connect','scoped_read','scope_isolation','pending_mac_approval','disconnect','done')
HINTS={'none','missing_control','closed','offline','invalid_response','unavailable','rate_limit','pending','empty','unexpected_view','timeout','query_result','private_field','unexpected_record','storage','other'}

class PilotPages:
    def __init__(self, app, offer, origin):
        self.app,self.offer,self.origin=app,offer,origin
        self.done=threading.Event()
        self.issued=False
        self.stages=[]
        self.prelude_seen=False
        self.source_html=(ROOT/'ui/phone.html').read_bytes()
        self.test_html=self.source_html.replace(b'<script defer src="/phone/phone.js"></script>',b'<script src="/qa/observe.js"></script><script defer src="/phone/phone.js"></script><script defer src="/qa/pilot.js"></script>')
        ensure(self.test_html!=self.source_html and self.test_html.replace(b'<script src="/qa/observe.js"></script>',b'').replace(b'<script defer src="/qa/pilot.js"></script>',b'')==self.source_html,'Shipped phone HTML changed unexpectedly')
        self.script=(Path(__file__).with_name('pilot.js')).read_bytes()
    async def __call__(self, scope, receive, send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        req=Request(scope,receive)
        path=req.url.path
        if path=='/qa/open' and req.method=='GET' and not self.issued:
            self.issued=True
            url=self.offer()
            response=RedirectResponse(url,status_code=302,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
        elif path=='/qa/observe.js' and req.method=='GET':
            js="""fetch('/qa/fragment', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({valid:/^#pair=[A-Za-z0-9_-]{43}$/.test(location.hash)})});"""
            response=Response(js,media_type='application/javascript')
        elif path=='/qa/pilot.js' and req.method=='GET':
            response=Response(self.script,media_type='application/javascript')
        elif path=='/qa/fragment' and req.method=='POST':
            data=await req.json()
            self.prelude_seen=data=={'valid':True}
            print('Mobile Safari pairing fragment valid on arrival:',self.prelude_seen,flush=True)
            response=Response(status_code=204)
        elif path=='/qa/evidence' and req.method=='POST':
            data=await req.json()
            ua=req.headers.get('user-agent','')
            ensure('Mobile/' in ua and 'Safari/' in ua,'UI witness did not originate from Mobile Safari')
            ensure(isinstance(data,dict) and set(data)=={'stage','ok','notice'} and data['stage'] in STAGES and type(data['ok']) is bool and data['notice'] in HINTS,'Unsupported UI witness')
            self.stages.append(data)
            print('Mobile Safari UI:',data['stage'],data['ok'],data['notice'],flush=True)
            if data['stage']=='done' or not data['ok']:
                self.done.set()
            response=Response(status_code=204)
        elif path=='/phone' and req.method=='GET':
            # Preserve normal app routing, security headers and the exact released HTML, except the two local test tags.
            status=None
            chunks=[]
            async def capture(event):
                nonlocal status
                if event['type']=='http.response.start': status=event
                else: chunks.append(event)
            await self.app(scope,receive,capture)
            ensure(status and status['status']==200 and b''.join(e.get('body',b'') for e in chunks)==self.source_html,'Mac did not serve released phone HTML')
            hdr=[(k,v) for k,v in status['headers'] if k!=b'content-length']
            ensure(any(k==b'content-security-policy' for k,_ in hdr),'Missing shipped browser security headers')
            await send({**status,'headers':hdr+[(b'content-length',str(len(self.test_html)).encode())]})
            await send({'type':'http.response.body','body':self.test_html})
            return
        else:
            return await self.app(scope,receive,send)
        await response(scope,receive,send)

def main():
    runtime,model=choose_phone()
    sim=output('xcrun','simctl','create','Safari DOM Airlock',model,runtime)
    try:
        with tempfile.TemporaryDirectory() as directory, socket.socket() as sock:
            tmp=Path(directory)
            run('xcrun','simctl','boot',sim)
            ca,cert=certificates(tmp)
            run('xcrun','simctl','bootstatus',sim,'-b',timeout=380)
            run('xcrun','simctl','keychain',sim,'add-root-cert',ca)
            sock.bind(('127.0.0.1',0));sock.listen(32)
            port=sock.getsockname()[1];origin='https://127.0.0.1:'+str(port)
            src=FictionalSources();g=Gateway(EncryptedStore(tmp/'fictional.enc',secrets.token_bytes(32)),src)
            g.device_apps=ExampleApps()
            with g.store.transaction() as d:
                d['remote_bridge']={'enabled':True,'port':port,'origin':origin}
            phone=PhoneCompanion(g);issued={}
            def issue():
                ref=src.library()[0]
                grant=phone.owner('phone-create',{'approved':True,'selection':{'memories:schedule':digest(ref['text'])}})
                act=Workspace(g).create('email','Review fictional follow-up',[grant['id']],
                       {'recipients':'review@example.test','subject':'Fictional rehearsal','body':'Fixture only.'})
                issued.update(grant=grant,action=act)
                return grant['url']
            witness=SafariWitness(BridgeApp(lambda:g,port),lambda:False,origin)
            pilot=PilotPages(witness,issue,origin)
            server=uvicorn.Server(uvicorn.Config(pilot,ssl_keyfile=str(tmp/'site.key'),ssl_certfile=str(cert),log_level='error',access_log=False,proxy_headers=False))
            th=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);th.start()
            try:
                end=time.monotonic()+12
                while not server.started and time.monotonic()<end: time.sleep(.1)
                ensure(server.started,'Mac gateway not ready')
                run('xcrun','simctl','openurl',sim,origin+'/qa/open',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                ensure(pilot.done.wait(220),'Safari did not finish UI steps')
                ensure([d['stage'] for d in pilot.stages]==list(STAGES) and all(v['ok'] for v in pilot.stages),'Safari did not pass all acceptance stages')
                ensure(witness.pair_count==1 and pilot.prelude_seen,'Mobile Safari did not redeem a fresh one-record pairing')
                expect=('/phone/pair','/phone/context','/phone/request','/phone/actions','/phone/disconnect')
                ensure(all((p,200) in witness.events for p in expect) and witness.session,'Missing authenticated Safari round-trip')
                grant,action=issued['grant'],issued['action']
                with g.store.transaction() as d:
                    item=d['device_actions'][action['id']]
                    ensure(item['state']=='pending' and not item['completed'] and item['applicant']==grant['id'],'Mac approval queue failed')
                    ensure(d['grants'][grant['id']]['revoked'],'Mac grant not revoked')
                ensure(not phone.owner('phone-state',{})['devices'],'Mac still lists a phone')
                ensure(post(origin,ca,'/phone/context',{'query':'Cypress'},witness.session)==401,'Revoked session still works')
                ensure(post(origin,ca,'/phone/pair',{'code':grant['url'].split('#pair=')[1]})==403,'Consumed link still works')
                receipt={'client':'Apple Mobile Safari','method':'DOM-driven controls using released JS and live HTTPS','os':runtime,'physical_device':False,
                         'source_commit':'572db1759c52e8c02bae9e5a715044a62768f7ae','paired':True,'one_selected_record':True,'redacted':True,
                         'unselected_withheld':True,'device_only_withheld':True,'write_pending':True,'write_executed':False,
                         'mac_verified_revoked':True,'old_session_http':401,'consumed_link_http':403}
                Path('pairing-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
                print('Matched Mac receipt: approved record redacted, write pending, grant revoked, old session HTTP 401, used link HTTP 403.',flush=True)
                witness.session=None
            finally:
                server.should_exit=True;th.join(timeout=10)
    finally:
        subprocess.run(['xcrun','simctl','shutdown',sim],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['xcrun','simctl','delete',sim],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if __name__=='__main__':
    main()
