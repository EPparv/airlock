"""Boot a disposable iPhone simulator and exercise Airlock in iOS WebKit over locally trusted HTTPS."""
import argparse
import contextlib
import functools
import http.client
import http.server
import json
import os
from pathlib import Path
import platform
import plistlib
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = 'com.airlock.fixture.phone'


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def choose_phone():
    data = json.loads(output('xcrun', 'simctl', 'list', 'devices', 'available', '-j'))
    for runtime in reversed(sorted(data['devices'])):
        for device in data['devices'][runtime]:
            if '.iOS-' in runtime and device['name'].startswith('iPhone') and device.get('isAvailable'):
                return runtime, device['deviceTypeIdentifier']
    raise RuntimeError('Xcode must have an available iPhone simulator runtime.')


def certificates(tmp):
    ca, cert = tmp/'root.crt', tmp/'site.crt'
    (tmp/'root.ext').write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ca\n[dn]\nCN=Airlock simulator fixture\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n')
    (tmp/'site.ext').write_text('[site]\nbasicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n')
    for args in (
        ['req','-x509','-newkey','rsa:2048','-nodes','-sha256','-days','3','-config',tmp/'root.ext','-keyout',tmp/'root.key','-out',ca],
        ['req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',tmp/'site.key','-out',tmp/'site.csr'],
        ['x509','-req','-in',tmp/'site.csr','-CA',ca,'-CAkey',tmp/'root.key','-CAcreateserial','-days','2','-sha256','-extfile',tmp/'site.ext','-extensions','site','-out',cert],
    ):
        run('openssl', *args, stderr=subprocess.DEVNULL)
    return ca, cert


class TestServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == getattr(self.server, 'pair_path', None):
            with self.server.pair_lock:
                if self.server.issue_pair is None:
                    self.send_error(410)
                    return
                issue = self.server.issue_pair
                self.server.issue_pair = None
            path = issue()
            self.send_response(302)
            self.send_header('Location', path)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            return
        if urlsplit(self.path).path.startswith('/phone'):
            return self.proxy()
        return super().do_GET()

    def do_POST(self):
        return self.proxy()

    def proxy(self):
        if not self.server.fixture_port or not urlsplit(self.path).path.startswith('/phone'):
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length') or 0)
        headers = {k: v for k, v in self.headers.items() if k.lower() in
                   ('host', 'content-type', 'authorization', 'origin', 'accept', 'cookie', 'content-length', 'sec-fetch-site')}
        conn = http.client.HTTPConnection('127.0.0.1', self.server.fixture_port, timeout=10)
        try:
            conn.request(self.command, self.path, self.rfile.read(length) if length else None, headers)
            response = conn.getresponse()
            if self.command == 'POST':
                expected_origin = f'https://127.0.0.1:{self.server.server_port}'
                origin = self.headers.get('Origin')
                origin_kind = {None:'absent', 'null':'null', expected_origin:'same-origin'}.get(origin, 'other')
                # Do not include URLs, form values, credential headers or private records.
                print('iPhone WebKit companion POST:', response.status, 'origin classification:', origin_kind,
                      flush=True)
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ('transfer-encoding', 'connection', 'content-length', 'server', 'date'):
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            conn.close()


def build_app(tmp):
    out = tmp/'PhoneProbe.app'
    out.mkdir()
    sdk = output('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path')
    version = output('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version')
    cpu = platform.machine()
    run('xcrun','--sdk','iphonesimulator','clang','-fobjc-arc','-target',f'{cpu}-apple-ios16.0-simulator','-isysroot',sdk,
        '-framework','Foundation','-framework','UIKit','-framework','WebKit',ROOT/'scripts/smoke_iphone.m','-o',out/'PhoneProbe')
    info = dict(CFBundleIdentifier=BUNDLE, CFBundleName='PhoneProbe', CFBundleExecutable='PhoneProbe',
                CFBundleVersion='1', CFBundleShortVersionString='1.0', CFBundlePackageType='APPL',
                MinimumOSVersion='16.0', CFBundleSupportedPlatforms=['iPhoneSimulator'],
                DTPlatformName='iphonesimulator', DTSDKName='iphonesimulator'+version, LSRequiresIPhoneOS=True,
                UIDeviceFamily=[1], UILaunchScreen={},
                UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'])
    (out/'Info.plist').write_bytes(plistlib.dumps(info))
    for name in ('iphone_flow', 'iphone_companion_flow'):
        src = ROOT/'tests'/(name+'.js')
        if src.is_file():
            (out/src.name).write_bytes(src.read_bytes())
    run('codesign','--sign','-','--force',out)
    return out


def check(include_companion):
    runtime, device_type = choose_phone()
    simulator = output('xcrun', 'simctl', 'create', 'Airlock Phone Check', device_type, runtime)
    try:
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            tmp = Path(directory)
            run('xcrun','simctl','boot',simulator)
            app = build_app(tmp)
            ca, cert = certificates(tmp)
            run('xcrun','simctl','bootstatus',simulator,'-b',timeout=360)
            run('xcrun','simctl','keychain',simulator,'add-root-cert',ca)
            handler = functools.partial(TestServer, directory=ROOT/'web')
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            server.fixture_port = None
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, tmp/'site.key')
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            origin = 'https://127.0.0.1:' + str(server.server_port)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.server_close)
            stack.callback(server.shutdown)
            env = {**os.environ, 'SIMCTL_CHILD_AIRLOCK_TEST_URL': origin+'/iphone/'}
            if include_companion:
                # Mint the real five-minute grant only when WebKit opens the companion.
                server.pair_path = '/fixture-pair/' + secrets.token_urlsafe(32)
                server.pair_lock = threading.Lock()

                def issue_pair():
                    with socket.socket() as probe:
                        probe.bind(('127.0.0.1',0))
                        server.fixture_port = probe.getsockname()[1]
                    pair_file = tmp/'pair.json'
                    fixture = subprocess.Popen([sys.executable, str(ROOT/'scripts/phone_fixture.py'), '--port', str(server.fixture_port),
                        '--public-origin', origin, '--state', str(tmp/'phone-fixture'), '--pair-output', str(pair_file)],
                        cwd=ROOT, env={**os.environ,'PYTHONPATH':str(ROOT)})
                    def stop_fixture():
                        fixture.terminate()
                        try: fixture.wait(timeout=5)
                        except subprocess.TimeoutExpired: fixture.kill(); fixture.wait()
                    stack.callback(stop_fixture)
                    end = time.monotonic() + 35
                    while not pair_file.exists():
                        if fixture.poll() is not None or time.monotonic() > end:
                            raise RuntimeError('Personal Mac fixture failed to open.')
                        time.sleep(.1)
                    path = json.loads(pair_file.read_text())['path']
                    if not path.startswith('/phone#pair='): raise RuntimeError('Unexpected pairing fixture URL.')
                    return path

                server.issue_pair = issue_pair
                env['SIMCTL_CHILD_AIRLOCK_PAIR_URL'] = origin + server.pair_path
            run('xcrun','simctl','install',simulator,app)
            run('xcrun','simctl','launch',simulator,BUNDLE,env=env)
            container = Path(output('xcrun','simctl','get_app_container',simulator,BUNDLE,'data'))
            result = container/'Documents/phone-result.txt'
            end = time.monotonic() + 170
            while not result.is_file() and time.monotonic() < end: time.sleep(.25)
            if not result.is_file(): raise RuntimeError('iPhone simulator app did not return a result.')
            if result.read_text() != 'passed': raise RuntimeError(result.read_text())
            print('iPhone WebKit passed on '+runtime.rsplit('.',1)[-1]+
                  '. Encrypted storage and reload, isolation, filtered reads, reviewed proposals, revocation'+
                  (', and pairing with the live Mac fixture.' if include_companion else '.'))
    finally:
        subprocess.run(['xcrun','simctl','shutdown',simulator], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['xcrun','simctl','delete',simulator], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only',action='store_true',help='Skip the separately hosted Mac companion fixture.')
    check(not parser.parse_args().local_only)
