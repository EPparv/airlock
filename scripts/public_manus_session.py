"""Empty, status-only public demonstration on a disposable CI runner."""
import argparse
import asyncio
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

from privacy_layer import remote_clients, server
from privacy_layer.core import Denied, EncryptedStore, Gateway
from privacy_layer.provider_checks import ProviderChecks
from smoke_quick_link import (
    EmptySources, checked_offer, poll_public, public_fetch, require,
    wait_for_file, write,
)

# This deliberately public example is useless outside the fresh, empty fixture.
DEMO_INPUT = 'pal_Airlock_Public_Manus_Status_Demo_Only_00001'
WINDOW = 18 * 60
GRACE = 90
ENDPOINT = '/mcp'
COUNTS = Counter()


class StatusOnly(Gateway):
    def call(self, token, tool, args, **kwargs):
        if (tool, args) != ('privacy_status', {}):
            raise Denied('The public demo has only a status operation.')
        return super().call(token, tool, args, **kwargs)


class DemoBridge(remote_clients.BridgeApp):
    async def response(self, request):
        if not (re.fullmatch(r'/link-check/[a-f0-9]{32}', request.url.path) or
                request.url.path == ENDPOINT):
            return Response(status_code=404)
        return await super().response(request)

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or scope.get('path') != ENDPOINT:
            return await super().__call__(scope, receive, send)
        auth = dict(scope.get('headers', [])).get(b'authorization', b'')
        correct = hmac.compare_digest(auth, ('Bearer ' + DEMO_INPUT).encode())
        method = scope.get('method')
        method = method if method in ('GET','POST','OPTIONS','DELETE') else 'OTHER'

        async def record(message):
            if message['type'] == 'http.response.start':
                COUNTS[(method, bool(auth), correct, int(message['status']))] += 1
            await send(message)
        return await super().__call__(scope, receive, record)


def restrict_catalog():
    from mcp.server.fastmcp import FastMCP
    factory = server.mcp_app

    def only_status(*args, **kwargs):
        application, mcp = factory(*args, **kwargs)
        for tool in asyncio.run(FastMCP.list_tools(mcp)):
            if tool.name != 'privacy_status':
                mcp.remove_tool(tool.name)
        names = [tool.name for tool in asyncio.run(FastMCP.list_tools(mcp))]
        require(names == ['privacy_status'], 'Unexpected catalog')
        return application, mcp
    server.mcp_app = only_status


def public_input(grant, gateway):
    require(type(gateway.sources) is EmptySources, 'This setup requires isolated empty data sources')
    with gateway.store.transaction() as state:
        require(set(state['grants']) == {grant['id']}, 'The disposable workspace must have exactly one grant')
        record = state['grants'][grant['id']]
        require(record['cloud_client'] == 'manus' and not record['views'] and
                not record['scope']['records'] and not record['revoked'], 'The demo must have no records')
        record['token_hash'] = hashlib.sha256(DEMO_INPUT.encode()).hexdigest()


def verify_baseline(origin):
    for path in ('/api/workspace-state', '/openapi.json', '/phone', '/v1/privacy_status'):
        require(public_fetch(origin + path)[0] == 404, 'Unexpected public route')
    require(public_fetch(origin + ENDPOINT, b'{}')[0] == 401, 'Missing input unexpectedly accepted')


def session(directory):
    remote_clients.BridgeApp = DemoBridge
    restrict_catalog()
    remote_clients.REST_TOOLS = {}
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
            grant = service.create('manus', WINDOW, 4)
            grant_id = grant['id']
            public_input(grant, gateway)
            checks.owner('provider-check-start', {'id': grant_id})
            with gateway.store.transaction() as state:
                deadline = state['grants'][grant_id]['expires']
            write(directory, 'ready.json', {'origin': origin, 'url': origin + ENDPOINT, 'nonce': nonce,
                                           'expires': deadline, 'unauthenticated_status': 401, 'source_count': 0})
            end = time.monotonic() + WINDOW
            while time.monotonic() < end and gateway.clock() < deadline and not (directory / 'stop').exists():
                with gateway.store.transaction() as state:
                    grant_state = state['grants'][grant_id]
                    tracking = dict(grant_state.get('provider_check', {}))
                    receipt.update(initialized=bool(grant_state.get('last_initialized')), discovered=bool(grant_state.get('last_discovery')))
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
        receipt['requests'] = [dict(method=k[0], path='mcp', auth_present=k[1],
                                    correct_public_input=k[2], status=k[3], count=n)
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
