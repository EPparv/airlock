"""CI-only, two-device acceptance for a disposable Mac with no personal sources."""
import argparse
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


def public_fetch(url, payload=None):
    # No caller-provided headers, credentials, proxies or HTTP redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, data=payload, headers={'Accept':'application/json, text/html',
                                                  'Cache-Control':'no-store', 'Content-Type':'application/json'})
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
        write(directory, 'proof.json', {'nonce':offer['nonce'], 'code':value})
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
    require(public_fetch(offer['url'])[0] == 404, 'A consumed verification link still responded')
    require(public_fetch(origin + '/api/workspace-state')[0] == 404, 'Owner route was visible')
    require(public_fetch(origin + '/v1/privacy_status', b'{}')[0] == 401, 'Missing credential was accepted')
    write(directory, 'witness.json', {'nonce':offer['nonce'], 'public_discovery':True})
    print('Second device confirmed public discovery, spent challenge, protected tools and private owner routes.')


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
                mcp = remote.create('manus', 120, 2)
                response = client.post('/mcp', headers={'Authorization':'Bearer ' + mcp['credential'],
                                       'Accept':'application/json, text/event-stream'}, json={'jsonrpc':'2.0',
                                       'id':1, 'method':'tools/call', 'params':{'name':'privacy_status','arguments':{}}})
                require(response.status_code == 200 and response.headers.get('content-type','').startswith('application/json')
                        and json.loads(response.json()['result']['content'][0]['text'])['execution']['status'] == 'success',
                        'Synthetic MCP grant failed')
                gateway.revoke(rest['id'])
                require(client.post('/v1/privacy_status', json={}, headers=auth).status_code == 401, 'Revocation failed')
            print('Scoped REST, MCP and revocation passed over ' + ('public HTTPS.' if use_public else 'Mac loopback.'))
            acknowledgement = wait_for_file(directory, 'witness.json', 240)
            require(acknowledgement == {'nonce':nonce,'public_discovery':True}, 'External discovery acknowledgement failed')
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
