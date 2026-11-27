"""Empty, status-only public demonstration on a disposable CI runner."""
import argparse
from collections import Counter
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sys
import tempfile
import time

from starlette.responses import Response

from privacy_layer import remote_clients
from privacy_layer.core import Denied, EncryptedStore, Gateway
from privacy_layer.provider_checks import ProviderChecks
from smoke_quick_link import (
    EmptySources, checked_offer, poll_public, public_fetch, require,
    wait_for_file, write,
)

# This deliberately public example is useless outside the fresh, empty fixture.
DEMO_INPUT = 'pal_Airlock_Public_Demo_Time_Bounded_Only_00001'
WINDOW = 18 * 60
GRACE = 90
SCHEMA = '/openapi.json'
STATUS = '/v1/privacy_status'
COUNTS = Counter()


class StatusOnly(Gateway):
    def call(self, token, tool, args, **kwargs):
        if (tool, args) != ('privacy_status', {}):
            raise Denied('The public demo has only a status operation.')
        return super().call(token, tool, args, **kwargs)


class DemoBridge(remote_clients.BridgeApp):
    async def response(self, request):
        path = request.url.path
        if re.fullmatch(r'/link-check/[a-f0-9]{32}', path):
            return await super().response(request)
        if path not in (SCHEMA, STATUS):
            return Response(status_code=404)
        response = await super().response(request)
        method = request.method if request.method in ('HEAD', 'GET', 'POST', 'OPTIONS') else 'OTHER'
        raw = request.headers.get('Authorization', '')
        auth_present = bool(raw)
        standard = hmac.compare_digest(raw.encode(), ('Bearer ' + DEMO_INPUT).encode())
        # The counters carry no header values, URLs, clients, request bodies or tool results.
        key = (method, 'schema' if path == SCHEMA else 'status', auth_present, standard, response.status_code)
        COUNTS[key] += 1
        return response


def public_input(grant, gateway):
    require(type(gateway.sources) is EmptySources, 'This setup requires isolated empty data sources')
    with gateway.store.transaction() as state:
        require(set(state['grants']) == {grant['id']}, 'The disposable workspace must have exactly one grant')
        record = state['grants'][grant['id']]
        require(record['cloud_client'] == 'muse' and not record['views'] and
                not record['scope']['records'] and not record['revoked'], 'The demo must have no records')
        record['token_hash'] = hashlib.sha256(DEMO_INPUT.encode()).hexdigest()


def verify_baseline(origin):
    def only_status(status, body):
        if status != 200:
            return False
        schema = json.loads(body)
        return (schema.get('servers') == [{'url': origin}] and
                set(schema.get('paths', {})) == {STATUS})
    poll_public(origin + SCHEMA, only_status, 55, 'Public status-only schema')
    for path in ('/api/workspace-state', '/mcp', '/phone', '/v1/get_private_context'):
        require(public_fetch(origin + path)[0] == 404, 'Unexpected public route')
    require(public_fetch(origin + STATUS, b'{}')[0] == 401, 'A missing credential was accepted')


def session(directory):
    remote_clients.BridgeApp = DemoBridge
    remote_clients.REST_TOOLS = {'privacy_status': ()}
    with tempfile.TemporaryDirectory() as tmp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        gateway = StatusOnly(EncryptedStore(Path(tmp) / 'empty.enc', secrets.token_bytes(32)), EmptySources())
        with gateway.store.transaction() as state:
            state['remote_bridge'] = {'port': port, 'enabled': False}
        remote_clients.set_active_gateway(lambda: gateway)
        service = remote_clients.RemoteClients(gateway)
        checks = ProviderChecks(gateway, service)
        grant_id = None
        receipt = {'authenticated_status_call': False}
        try:
            offer = service.owner('remote-quick-start', {'approved': True, 'verification_method': 'device'})
            nonce = secrets.token_hex(16)
            write(directory, 'offer.json', {'url': offer['verification']['url'], 'nonce': nonce})
            _, origin = checked_offer(directory)
            proof = wait_for_file(directory, 'proof.json', 270)
            require(proof.get('nonce') == nonce, 'Independent challenge mismatch')
            service.owner('remote-quick-confirm', {'code': proof['code']})
            verify_baseline(origin)
            grant = service.create('muse', WINDOW, 4)
            grant_id = grant['id']
            public_input(grant, gateway)
            checks.owner('provider-check-start', {'id': grant_id})
            with gateway.store.transaction() as state:
                deadline = state['grants'][grant_id]['expires']
            write(directory, 'ready.json', {'origin': origin, 'schema': origin + SCHEMA, 'nonce': nonce,
                                           'expires': deadline, 'unauthenticated_status': 401, 'source_count': 0})
            end = time.monotonic() + WINDOW
            while time.monotonic() < end and gateway.clock() < deadline and not (directory / 'stop').exists():
                with gateway.store.transaction() as state:
                    tracking = dict(state['grants'][grant_id].get('provider_check', {}))
                if tracking.get('received') and tracking.get('code'):
                    digest = hashlib.sha256((nonce + tracking['code']).encode()).hexdigest()
                    receipt.update(authenticated_status_call=True, returned_code_hash=digest,
                                   received=tracking['received'])
                    end = min(end, time.monotonic() + max(0, GRACE - (gateway.clock() - tracking['received'])))
                elif tracking.get('expires', 0) <= gateway.clock() and gateway.clock() < deadline:
                    checks.owner('provider-check-start', {'id': grant_id})
                time.sleep(.4)
        finally:
            if grant_id:
                gateway.revoke(grant_id)
            remote_clients.set_active_gateway(lambda: None)
            service.close()
        require(not service.state()['enabled'], 'Disposable bridge did not close')
        with gateway.store.transaction() as state:
            receipt['revoked'] = grant_id is not None and state['grants'][grant_id]['revoked']
        receipt['closed'] = True
        receipt['requests'] = [dict(method=k[0], path=k[1], auth_present=k[2],
                                    correct_public_input=k[3], status=k[4], count=n)
                               for k, n in Counter(COUNTS).items()]
        write(directory, 'receipt.json', receipt)
        print('Public sample complete. Authenticated status:', receipt['authenticated_status_call'])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('dir', type=Path)
    args = p.parse_args()
    os.umask(0o077)
    args.dir.mkdir(parents=True, exist_ok=True)
    logging.disable(logging.CRITICAL)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        session(args.dir)
    except Exception as exc:
        write(args.dir, 'failed.json', {'failed': True})
        print('Public fixture failed:', type(exc).__name__, str(exc) if type(exc).__name__ == 'Failure' else '', file=sys.stderr)
        sys.exit(1)
