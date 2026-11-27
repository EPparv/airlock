"""CI-only, two-device acceptance for a disposable Mac with no personal sources."""
import argparse
import base64
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HOST = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com')
ROUTE = re.compile(r'/link-check/[a-f0-9]{32}')
CODE = re.compile(rb'<output id="airlock-code">([0-9]{8})</output>')


class Failure(Exception):
    """Safe-to-log stage description."""


def require(condition, detail):
    if not condition:
        raise Failure(detail)


def write(directory, name, value):
    p = directory / (name + '.writing')
    p.write_text(json.dumps(value))
    p.replace(directory / name)


def read(directory, name):
    p = directory / name
    require(p.stat().st_size < 8192, 'Unexpected artifact size')
    return json.loads(p.read_text())


def wait_for_file(directory, name, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (directory / name).is_file():
            return read(directory, name)
        if (directory / 'failed.json').exists() or (directory / 'stop').exists():
            raise Failure('Mac fixture has stopped')
        time.sleep(.5)
    raise Failure('Timed out waiting for ' + name)


def checked_offer(directory):
    offer = read(directory, 'offer.json')
    url = urlsplit(offer['url'])
    require(url.scheme == 'https' and HOST.fullmatch(url.netloc) and ROUTE.fullmatch(url.path)
            and not url.query and not url.fragment and len(url.netloc) <= 100
            and offer['url'] == 'https://' + url.netloc + url.path
            and re.fullmatch('[0-9a-f]{32}', offer['nonce']), 'Invalid route offer')
    return offer, 'https://' + url.netloc


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_fetch(url, payload=None, *, witness_token=None):
    # Never follow redirects or forward a credential outside the fixed test service.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    headers={'Accept':'application/json, text/html', 'Cache-Control':'no-store', 'Content-Type':'application/json'}
    if witness_token is not None:
        parts=urlsplit(url)
        require(parts.scheme=='https' and HOST.fullmatch(parts.netloc) and not parts.fragment and not parts.query
                and parts.path in ('/mcp','/v1/privacy_status') and re.fullmatch(r'pal_[\w-]{43}', witness_token, re.ASCII),
                'Invalid external status destination or credential')
        headers.update(Authorization='Bearer '+witness_token, Accept='application/json, text/event-stream')
    request = Request(url, data=payload, headers=headers)
    try:
        with opener.open(request, timeout=6) as r:
            body = r.read(262145)
            require(len(body) <= 262144, 'Public response exceeded its bound')
            return r.status, body
    except HTTPError as e:
        with e:
            return e.code, b''


def poll_public(url, accept, seconds, label):
    deadline = time.monotonic() + seconds
    last = 'DNS or connection unavailable'
    while time.monotonic() < deadline:
        try:
            status, body = public_fetch(url)
            last = 'HTTP ' + str(status)
            result = accept(status, body)
            if result:
                return result
        except (URLError, OSError):
            last = 'DNS or connection unavailable'
        time.sleep(min(4, max(0, deadline - time.monotonic())))
    raise Failure(label + ' timed out (' + last + ')')


def witness(directory, discovery=False):
    offer, origin = checked_offer(directory)
    if not discovery:
        def code(status, body):
            matched = CODE.search(body) if status == 200 else None
            return matched.group(1).decode('ascii') if matched else None
        value = poll_public(offer['url'], code, 225, 'External challenge')
        # Only this runner ever sees the private key. All uploaded artifacts are
        # individual allowlisted files. The Mac receives the public half.
        private_key=directory/'witness.private'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',private_key],
                       check=True,stderr=subprocess.DEVNULL)
        private_key.chmod(0o600)
        public_key=subprocess.check_output(['openssl','pkey','-in',private_key,'-pubout'],text=True)
        write(directory, 'proof.json', {'nonce':offer['nonce'], 'code':value, 'public_key':public_key})
        print('Second device read the eight-digit challenge over public HTTPS.')
        return
    def valid_schema(status, body):
        if status != 200:
            return False
        try:
            schema = json.loads(body)
            return (schema['openapi'].startswith('3.') and schema['servers'] == [{'url':origin}]
                    and '/v1/privacy_status' in schema['paths'])
        except (TypeError, KeyError, ValueError, AttributeError):
            return False
    poll_public(origin + '/openapi.json', valid_schema, 180, 'External discovery')
    # Browser-based connector importers must be able to inspect the public
    # contract before they have a token. They receive no credentialed CORS access.
    importer = build_opener(ProxyHandler({}), NoRedirect())
    for method in ('OPTIONS','HEAD','GET'):
        headers={'Origin':'https://importer.example.org'}
        if method=='OPTIONS':
            headers['Access-Control-Request-Method']='GET'
        request=Request(origin+'/openapi.json',method=method,headers=headers)
        with importer.open(request,timeout=8) as response:
            require(response.status==(204 if method=='OPTIONS' else 200)
                    and response.headers.get('Access-Control-Allow-Origin')=='*'
                    and response.headers.get('Access-Control-Allow-Credentials') is None,
                    'External anonymous schema import failed')
            if method=='GET':
                require(valid_schema(200,response.read(262145)), 'Cross-origin discovery returned the wrong schema')
    require(public_fetch(offer['url'])[0] == 404, 'A consumed verification link still responded')
    require(public_fetch(origin + '/api/workspace-state')[0] == 404, 'Owner route was visible')
    require(public_fetch(origin + '/v1/privacy_status', b'{}')[0] == 401, 'Missing credential was accepted')
    sealed=read(directory,'sealed.json')
    private_key=directory/'witness.private'
    try:
        clear=subprocess.check_output(['openssl','pkeyutl','-decrypt','-inkey',private_key,'-pkeyopt','rsa_padding_mode:oaep',
                                      '-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],
                                     input=base64.b64decode(sealed['ciphertext'],validate=True),stderr=subprocess.DEVNULL)
    finally:
        private_key.unlink(missing_ok=True)
    calls=json.loads(clear)
    require(calls['nonce']==offer['nonce'], 'External status request did not match this run')
    rpc={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'privacy_status','arguments':{}}}
    for route,payload,token in [('/v1/privacy_status',{},calls['rest']),('/mcp',rpc,calls['mcp'])]:
        status,body=public_fetch(origin+route,json.dumps(payload).encode(),witness_token=token)
        require(status==200, 'External status call returned HTTP '+str(status))
        result=json.loads(body)
        if route=='/mcp':
            result=json.loads(result['result']['content'][0]['text'])
        require(result['execution']['status']=='success' and result['scope_selection']['records']==[],
                'External status response was unsuccessful or had a nonempty scope')
    write(directory, 'witness.json', {'nonce':offer['nonce'], 'authenticated_status':True})
    print('Independent runner completed authenticated REST and MCP status calls over public HTTPS.')


class EmptySources:
    def library(self):
        return []

    def protected(self):
        return []


def host(directory):
    import httpx
    from privacy_layer.core import Gateway, EncryptedStore
    from privacy_layer.remote_clients import RemoteClients, set_active_gateway
    with tempfile.TemporaryDirectory(prefix='airlock-ci-empty-') as folder:
        gateway = Gateway(EncryptedStore(Path(folder)/'empty.enc', secrets.token_bytes(32)), EmptySources())
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        with gateway.store.transaction() as data:
            data['remote_bridge'] = {'port':port, 'enabled':False}
        set_active_gateway(lambda:gateway)
        remote = RemoteClients(gateway)
        nonce = secrets.token_hex(16)
        try:
            print('Starting pinned Cloudflare helper and checking the agent-only listener.')
            state = remote.owner('remote-quick-start', {'approved':True, 'verification_method':'device'})
            require(not state['verified'] and state['verification'], 'Temporary link was not awaiting device verification')
            write(directory, 'offer.json', {'url':state['verification']['url'], 'nonce':nonce})
            offer, origin = checked_offer(directory)
            require(state['origin'] == origin, 'Origin mismatch')
            print('Waiting for a challenge response from the independent device.')
            proof = wait_for_file(directory, 'proof.json', 420)
            require(proof.get('nonce') == nonce and re.fullmatch('[0-9]{8}', str(proof.get('code'))), 'Invalid returned proof')
            require(remote.owner('remote-quick-confirm', {'code':proof['code']})['verified'], 'Device confirmation failed')
            print('Mac owner confirmed the code returned by the external device.')
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
            recipient=serialization.load_pem_public_key(proof['public_key'].encode('ascii'))
            require(isinstance(recipient,rsa.RSAPublicKey) and recipient.key_size==3072, 'Invalid external witness key')
            grants={name:remote.create(vendor,300,1) for name,vendor in [('rest','muse'),('mcp','custom')]}
            witness_payload={'nonce':nonce, **{name:grant['credential'] for name,grant in grants.items()}}
            ciphertext=recipient.encrypt(json.dumps(witness_payload).encode(),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
            write(directory,'sealed.json',{'ciphertext':base64.b64encode(ciphertext).decode('ascii')})
            # Some managed Mac runners cannot resolve freshly allocated names.
            # The independent witness must still verify the public endpoint in both cases.
            try:
                use_public = public_fetch(origin + '/openapi.json')[0] == 200
            except (URLError, OSError):
                use_public = False
            target = origin if use_public else f'http://127.0.0.1:{port}'
            with httpx.Client(base_url=target, timeout=10, trust_env=False, follow_redirects=False) as client:
                rest = remote.create('muse', 120, 2)
                auth = {'Authorization':'Bearer ' + rest['credential']}
                response = client.post('/v1/privacy_status', json={}, headers=auth)
                require(response.status_code == 200 and response.json()['execution']['status'] == 'success'
                        and response.json()['scope_selection']['records'] == [], 'Synthetic REST grant failed')
                for vendor in ('manus', 'ironclaw', 'custom'):
                    mcp = remote.create(vendor, 120, 2)
                    response = client.post('/mcp', headers={'Authorization':'Bearer ' + mcp['credential'],
                                           'Accept':'application/json, text/event-stream'}, json={'jsonrpc':'2.0',
                                           'id':1, 'method':'tools/call', 'params':{'name':'privacy_status','arguments':{}}})
                    require(response.status_code == 200 and response.headers.get('content-type','').startswith('application/json')
                            and json.loads(response.json()['result']['content'][0]['text'])['execution']['status'] == 'success',
                            'Synthetic MCP grant failed for ' + vendor)
                from privacy_layer.phone_companion import PhoneCompanion
                phone = PhoneCompanion(gateway).owner('phone-create', {'selection':{},'approved':True})
                # When the Mac's own resolver cannot reach the new name, preserve the
                # browser's public Host and Origin on our local request to its bridge.
                headers = {'Host':urlsplit(origin).netloc, 'Origin':origin, 'Sec-Fetch-Site':'same-origin'}
                code = urlsplit(phone['url']).fragment.removeprefix('pair=')
                response = client.post('/phone/pair', json={'code':code}, headers=headers)
                require(response.status_code == 200, 'Empty phone pairing failed')
                headers['Authorization'] = 'Bearer ' + response.json()['session']
                response = client.post('/phone/status', json={}, headers=headers)
                require(response.status_code == 200 and response.json()['count'] == 0, 'Empty phone status failed')
                require(client.post('/phone/status', json={}, headers={**headers,
                        'Origin':'https://other.example.test','Sec-Fetch-Site':'cross-site'}).status_code == 403,
                        'Cross-origin phone request was accepted')
                require(client.post('/phone/disconnect',json={},headers=headers).status_code == 200,
                        'Empty phone cleanup failed')
                gateway.revoke(rest['id'])
                require(client.post('/v1/privacy_status', json={}, headers=auth).status_code == 401, 'Revocation failed')
            print('Scoped REST, three MCP grants, phone pairing, cross-origin rejection and revocation passed over ' + ('public HTTPS.' if use_public else 'Mac loopback.'))
            acknowledgement = wait_for_file(directory, 'witness.json', 240)
            require(acknowledgement == {'nonce':nonce,'authenticated_status':True}, 'External status acknowledgement failed')
            for grant in grants.values():
                receipt=next(g for g in gateway.list_grants() if g['id']==grant['id'])
                require(receipt['last_call'] is not None and receipt['remaining']==0,'Missing external tool call receipt')
        finally:
            set_active_gateway(lambda: None)
            remote.close()
        require(not remote.state()['enabled'], 'Mac link remained enabled')
        write(directory, 'done.json', {'passed':True})
        print('External witness acknowledged. Mac stopped the temporary link.')


def artifact(run_directory, name, peer, seconds):
    repo = os.environ['GITHUB_REPOSITORY']
    run, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    deadline = time.monotonic() + seconds

    def gh_json(resource):
        try:
            result = subprocess.run(['gh','api',f'repos/{repo}/actions/runs/{run}/{resource}'],
                                    capture_output=True, timeout=12, check=True)
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, ValueError):
            return {}
    while time.monotonic() < deadline:
        if (run_directory/'failed.json').exists():
            raise Failure('Local test host failed')
        found = gh_json('artifacts?per_page=50').get('artifacts', [])
        if any(a['name'] == name and not a['expired'] for a in found):
            return
        jobs = gh_json(f'attempts/{attempt}/jobs?per_page=50').get('jobs', [])
        if any(j['name'] == peer and j['status'] == 'completed' and j.get('conclusion') != 'success' for j in jobs):
            raise Failure('Partner job failed before the required artifact was available')
        time.sleep(6)
    raise Failure('Timed out waiting for partner artifact')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['host','witness','discovery','wait-file','wait-artifact'])
    p.add_argument('directory', type=Path)
    p.add_argument('--name')
    p.add_argument('--peer')
    p.add_argument('--seconds', type=int, default=240)
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.disable(logging.CRITICAL)
    try:
        if args.mode == 'host':
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
            host(args.directory)
        elif args.mode in ('witness','discovery'):
            witness(args.directory, args.mode == 'discovery')
        elif args.mode == 'wait-file':
            wait_for_file(args.directory, args.name, args.seconds)
        else:
            artifact(args.directory, args.name, args.peer, args.seconds)
    except Exception as e:
        # Keep hostname, proof and all credentials out of logs even on failure.
        detail = str(e) if isinstance(e, Failure) else type(e).__name__
        print('Temporary HTTPS acceptance: ' + detail, file=sys.stderr)
        if args.mode == 'host':
            write(args.directory, 'failed.json', {'failed':True})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
