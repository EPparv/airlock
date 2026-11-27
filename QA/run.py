from pathlib import Path
import functools, http.server, os, ssl, subprocess, sys, tempfile, threading
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import smoke_iphone as fixtures

import json
devices = json.loads(fixtures.output('xcrun','simctl','list','devices','available','-j'))['devices']
pairs = [(r,d['deviceTypeIdentifier']) for r,ds in devices.items() if '.iOS-18-' in r for d in ds if d.get('isAvailable') and d['name'].startswith('iPhone')]
runtime, device = sorted(pairs)[-1] if pairs else fixtures.choose_phone()
udid = fixtures.output('xcrun','simctl','create','Airlock Actual Safari Share Probe',device,runtime)
print("iOS runtime",runtime,flush=True)
try:
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        fixtures.run('xcrun','simctl','boot',udid)
        ca,cert=fixtures.certificates(tmp)
        fixtures.run('xcrun','simctl','bootstatus',udid,'-b',timeout=360)
        fixtures.run('xcrun','simctl','keychain',udid,'add-root-cert',ca)
        server = http.server.ThreadingHTTPServer(('127.0.0.1',8742), functools.partial(http.server.SimpleHTTPRequestHandler,directory=ROOT/'web'))
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert,tmp/'site.key')
        server.socket=ctx.wrap_socket(server.socket,server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            fixtures.run('xcodegen','generate','--spec',ROOT/'QA/project.yml')
            fixtures.run('xcodebuild','-project',ROOT/'QA/SafariShareProbe.xcodeproj','-scheme','ShareAcceptance','-destination','id='+udid,'-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1','CODE_SIGNING_ALLOWED=NO','test',timeout=720)
        finally:
            server.shutdown()
            server.server_close()
finally:
    subprocess.run(['xcrun','simctl','shutdown',udid],check=False)
    subprocess.run(['xcrun','simctl','delete',udid],check=False)
