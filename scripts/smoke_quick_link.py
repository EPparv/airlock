"""Opt-in public transport check. Uses a new empty fixture and no user data."""
import argparse
import json
import logging
from pathlib import Path
import secrets
import socket
import sys
import tempfile

import httpx

from privacy_layer.core import Gateway, EncryptedStore
from privacy_layer.remote_clients import RemoteClients, set_active_gateway
from privacy_layer.sources import LocalSources


def run():
    # Network and MCP libraries can otherwise log full request URLs.
    logging.disable(logging.CRITICAL)
    stage = 'initialize'
    with tempfile.TemporaryDirectory(prefix='airlock-cloud-check-') as folder:
        root = Path(folder)
        key = secrets.token_bytes(32)
        source = LocalSources(key=key, context_home=root)
        gateway = Gateway(EncryptedStore(root/'state.enc', key), source)
        source.connection_store = gateway.store
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        with gateway.store.transaction() as data:
            data['remote_bridge'] = {'port':port, 'enabled':False}
        set_active_gateway(lambda: gateway)
        remote = RemoteClients(gateway)
        try:
            stage = 'download helper and verify HTTPS'
            state = remote.start_temporary(True)
            assert state['verified']
            stage = 'check public routes with empty fixture'
            with httpx.Client(base_url=state['origin'], timeout=10, trust_env=False, follow_redirects=False) as client:
                assert client.get('/api/workspace-state').status_code == 404
                assert client.post('/v1/privacy_status', json={}).status_code == 401
                rest = remote.create('muse', 60, 2)
                auth = {'Authorization':'Bearer '+rest['credential']}
                status = client.post('/v1/privacy_status', headers=auth, json={})
                assert status.status_code == 200 and status.json()['execution']['status'] == 'success'
                assert not status.json()['scope_selection']['records']
                stage = 'verify JSON MCP tool result'
                mcp = remote.create('manus', 60, 2)
                response = client.post('/mcp', headers={'Authorization':'Bearer '+mcp['credential'],
                    'Accept':'application/json, text/event-stream'}, json={
                    'jsonrpc':'2.0', 'id':1, 'method':'tools/call', 'params':{'name':'privacy_status', 'arguments':{}}})
                assert response.status_code == 200 and response.headers['content-type'].startswith('application/json')
                result = response.json()['result']
                assert not result.get('isError') and json.loads(result['content'][0]['text'])['execution']['status']=='success'
                stage = 'check revocation'
                gateway.revoke(rest['id'])
                assert client.post('/v1/privacy_status', headers=auth, json={}).status_code == 401
        except Exception:
            # Keep assigned hostnames, credentials and any remote error bodies out of CI logs.
            print('Temporary HTTPS verification failed at '+stage+'.', file=sys.stderr)
            return 1
        finally:
            set_active_gateway(lambda: None)
            remote.close()
        assert not remote.state()['enabled']
        print('Public HTTPS verified with empty fixture: scoped REST and JSON MCP, private owner routes, revocation and shutdown.')
        return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--temporary-public-test', action='store_true', required=True,
                        help='Allow a temporary Cloudflare connection for this disposable fixture.')
    parser.parse_args()
    sys.exit(run())
