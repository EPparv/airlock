"""Private cloud-agent connections. Management stays on the owner listener."""
import asyncio
import json
import re
import socket
import threading
from urllib.parse import urlsplit

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .agent_memory import AgentMemory
from .core import Denied
from .setup import private_write
from .quick_tunnel import QuickTunnel, probe_schema, verify_route

VENDORS = {'muse': 'Meta Muse', 'manus': 'Manus', 'chatgpt': 'ChatGPT', 'ironclaw': 'IronClaw', 'custom': 'Custom remote MCP'}
MCP_VENDORS = {'manus', 'ironclaw', 'custom'}
DEFAULT_PORT = 8794
_get_active = lambda: None

# Public discovery publishes only the API contract, never owner settings or records.
REST_TOOLS = {
    'privacy_status': (),
    'context_status': (),
    'get_private_context': ('query',),
    'list_agent_handoffs': (),
    'claim_agent_handoff': ('reference',),
    'submit_agent_handoff': ('reference', 'result', 'memory_proposal_id'),
    'read_agent_handoff': ('reference',),
    'prepare_private_followup': ('source', 'subject', 'body', 'request_key'),
    'list_private_actions': (),
    'read_private_fields': ('reference',),
    'request_private_action': ('reference',),
    'private_action_status': ('reference',),
    'get_private_task_result': ('task_id',),
    'request_private_task': ('instruction', 'records', 'route'),
    'update_shared_context': ('operation', 'kind', 'text', 'reference', 'expected_revision'),
}
DESCRIPTIONS = {
    'privacy_status': 'Read connection limits and permissions',
    'context_status': 'Read the current shared library revision',
    'get_private_context': 'Read permitted filtered context for a topic',
    'list_agent_handoffs': 'List assignments and reviewed results available to this agent',
    'claim_agent_handoff': 'Accept an owner-assigned task',
    'submit_agent_handoff': 'Submit a report for owner review, optionally linking an existing memory proposal',
    'read_agent_handoff': 'Read the exact result released to this connection',
    'prepare_private_followup': 'Queue a follow-up to the selected message or recent meeting for owner review',
    'list_private_actions': 'List tasks the owner assigned to this connection',
    'read_private_fields': 'Read approved fields of an assigned data view',
    'request_private_action': 'Request owner approval to perform a prepared action',
    'private_action_status': 'Check the status of an assigned action',
    'request_private_task': 'Request owner approval to compute on selected private records',
    'get_private_task_result': 'Retrieve a result explicitly released by the owner',
    'update_shared_context': 'Propose a change to shared memory for local review',
}


def set_active_gateway(getter):
    global _get_active
    _get_active = getter


def public_origin(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        valid_host = re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?', host)
        if (not isinstance(value, str) or len(value) > 300 or not value.isascii() or
                re.search(r'[\s\\?#@]', value) or parsed.scheme != 'https' or not valid_host or
                parsed.path not in ('', '/') or host.endswith(('.localhost', '.local', '.internal', '.invalid'))):
            raise ValueError()
        port = parsed.port
        if port == 0:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise Denied('Enter the HTTPS origin of a domain you control, without a path or credentials.') from None
    return 'https://' + host + (f':{port}' if port and port != 443 else '')


def openapi(origin):
    paths = {}
    for name, keys in REST_TOOLS.items():
        properties = {key: {'type': 'string'} for key in keys}
        if 'records' in properties:
            properties['records'] = {'type': 'array', 'items': {'type': 'string'}}
            properties['route'] = {'type': 'string', 'enum': ['local', 'near']}
        if 'expected_revision' in properties:
            properties.update(expected_revision={'type': 'integer'}, operation={'type': 'string', 'enum': ['add', 'update', 'delete']},
                              kind={'type': 'string', 'enum': ['memories', 'skills']})
        schema = {'type': 'object', 'properties': properties, 'additionalProperties': False}
        if keys:
            schema['required'] = [key for key in keys if key != 'memory_proposal_id']
        paths['/v1/' + name] = {'post': {'operationId': name, 'summary': DESCRIPTIONS[name],
            'requestBody': {'required': True, 'content': {'application/json': {'schema': schema}}},
            'responses': {'200': {'description': 'Scoped tool result'}, '403': {'description': 'Access denied'}}}}
    return {'openapi': '3.1.0', 'info': {'title': 'Airlock', 'version': '1'}, 'servers': [{'url': origin}],
            'paths': paths, 'components': {'securitySchemes': {'agent': {'type': 'http', 'scheme': 'bearer'}}},
            'security': [{'agent': []}]}


class CloudGateway:
    def __init__(self, active):
        self.active = active

    def authorize(self, token, transport):
        gateway = self.active()
        if gateway is None:
            raise Denied('Access is closed.')
        with gateway.store.transaction() as state:
            grant = gateway._grant(state, token)
            config = state.get('remote_bridge', {})
            if (not config.get('enabled') or grant.get('cloud_origin') != config.get('origin') or
                    grant.get('cloud_client') not in (MCP_VENDORS if transport == 'mcp' else {'muse'}) or grant.get('scope') is None or grant['remaining'] <= 0):
                raise Denied('Access is closed.')
        return gateway

    def authenticate(self, token):
        return self.authorize(token, 'mcp').authenticate(token)

    def dispatch(self, token, tool, args, vendor):
        gateway = self.authorize(token, vendor)
        result = gateway.call(token, tool, args, connection_route='https-bridge')
        if self.active() is not gateway:
            raise Denied('The workspace was locked.')
        with gateway.store.transaction() as state:
            grant = gateway._grant(state, token)
            config = state.get('remote_bridge', {})
            if not config.get('enabled') or config.get('origin') != grant.get('cloud_origin'):
                raise Denied('The HTTPS bridge was paused or changed.')
        return result

    def call(self, token, tool, args):
        return self.dispatch(token, tool, args, 'mcp')


class BridgeApp:
    """The sole ASGI application on the forwarding port. It has no owner routes."""
    def __init__(self, active, port):
        from .server import mcp_app
        self.gateway = CloudGateway(active)
        self.port = port
        self.mcp, _ = mcp_app(self.gateway, port)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.mcp(scope, receive, send)
        if scope['type'] != 'http':
            return
        req = Request(scope, receive)
        reply = await self.response(req)
        if reply is None:
            headers = [(k, v) for k, v in scope['headers'] if k not in (b'host', b'forwarded') and not k.startswith(b'x-forwarded-')]
            headers.append((b'host', f'127.0.0.1:{self.port}'.encode()))
            return await self.mcp({**scope, 'headers': headers}, receive, send)
        reply.headers['Cache-Control'] = 'no-store'
        return await reply(scope, receive, send)

    async def response(self, req):
        path = req.url.path
        if path == '/phone' or path.startswith('/phone/'):
            from .phone_companion import phone_response
            return await phone_response(self.gateway.active, req)
        if path not in ('/openapi.json', '/mcp') and path not in {'/v1/' + tool for tool in REST_TOOLS}:
            return Response(status_code=404)
        if req.headers.get('origin') is not None or req.scope.get('query_string'):
            return Response(status_code=403)
        gateway = self.gateway.active()
        if gateway is None:
            return Response(status_code=503)
        with gateway.store.transaction() as data:
            config = data.get('remote_bridge', {})
        if not config.get('enabled'):
            return Response(status_code=503)
        host = req.headers.get('host', '')
        if host not in (urlsplit(config['origin']).netloc, f'127.0.0.1:{self.port}', f'localhost:{self.port}'):
            return Response(status_code=403)
        if path == '/openapi.json':
            return JSONResponse(openapi(config['origin'])) if req.method == 'GET' else Response(status_code=405)
        if req.method != 'POST':
            return Response(status_code=405)
        auth = req.headers.get('authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''
        try:
            await asyncio.to_thread(self.gateway.authorize, token, 'mcp' if path == '/mcp' else 'muse')
        except Denied:
            return JSONResponse({'error': 'Agent credential required.'}, 401, headers={'WWW-Authenticate': 'Bearer'})
        if path == '/mcp':
            return None
        if req.headers.get('content-type', '').split(';')[0] != 'application/json':
            return Response(status_code=415)
        raw = bytearray()
        async for chunk in req.stream():
            if len(raw) + len(chunk) > 65536:
                return Response(status_code=413)
            raw.extend(chunk)
        tool = path.removeprefix('/v1/')
        try:
            args = json.loads(raw)
            if tool == 'submit_agent_handoff' and isinstance(args, dict):
                args.setdefault('memory_proposal_id', '')
            if not isinstance(args, dict) or set(args) != set(REST_TOOLS[tool]):
                return Response(status_code=400)
            result = await asyncio.to_thread(self.gateway.dispatch, token, tool, args, 'muse')
            return JSONResponse(result)
        except Denied as error:
            return JSONResponse({'error': str(error)}, 403)
        except (ValueError, RecursionError):
            return Response(status_code=400)
        except Exception:
            return JSONResponse({'error': 'Tool could not complete.'}, 503)


class LoopbackListener:
    def __init__(self):
        self.lock = threading.Lock()
        self.server = self.thread = self.port = None

    def verify_local(self, origin, cancel):
        reason = probe_schema(f'http://127.0.0.1:{self.port}', origin, cancel, seconds=4)
        if reason:
            raise Denied('The local agent bridge failed its discovery check (' + reason + '). Reopen Airlock.')

    def stop(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.server.should_exit = True
                self.thread.join(timeout=3)

    def ensure(self, port):
        with self.lock:
            if self.thread and self.thread.is_alive():
                if self.port != port:
                    raise Denied('Restart Airlock before choosing a different bridge port.')
                return
            sock = socket.socket()
            try:
                sock.bind(('127.0.0.1', port))
                sock.listen(64)
                server = uvicorn.Server(uvicorn.Config(BridgeApp(lambda: _get_active(), port), access_log=False,
                    log_level='error', proxy_headers=False, timeout_keep_alive=5, limit_concurrency=32))
                thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
                thread.start()
                self.server, self.thread, self.port = server, thread, port
            except OSError:
                sock.close()
                raise Denied('This bridge port is unavailable. Choose another local port.') from None
            except Exception:
                sock.close()
                raise


_listener = LoopbackListener()


class RemoteClients:
    def __init__(self, gateway, listener=None, *, tunnel_factory=QuickTunnel, verify=verify_route):
        self.lock = threading.RLock()
        self.tunnel_factory, self.verify = tunnel_factory, verify
        self.tunnel = None
        self.closed = False
        self.g = gateway
        self.listener = listener or _listener
        with self.g.store.transaction() as data:
            config = data.get('remote_bridge', {})
        if config.get('mode') == 'temporary':
            # A previous process may have stopped without receiving a close event.
            self.clear_temporary()
        elif config.get('enabled'):
            try:
                self.listener.ensure(config['port'])
            except Denied:
                pass  # The owner can resolve a port conflict in the bridge settings.

    def state(self):
        with self.g.store.transaction() as data:
            config = data.get('remote_bridge', {})
            calls = {event['agent']: event['at'] for event in data['audit'] if event['status'] == 'released'}
            grants = [{'id': g['id'], 'vendor': g['cloud_client'], 'expires': g['expires'],
                       'remaining': g['remaining'], 'last_call': calls.get(g['id']), 'revoked': g['revoked'], 'last_read': g.get('last_context_read'),
                       'active': not g['revoked'] and g['expires'] > self.g.clock() and g['remaining'] > 0}
                      for g in data['grants'].values() if g.get('cloud_client') in VENDORS]
        port = config.get('port', DEFAULT_PORT)
        return {'mode':config.get('mode', 'manual'), 'verified':bool(config.get('verified')), 'starting':bool(self.tunnel and not config.get('verified')),
                'enabled': config.get('enabled', False), 'origin': config.get('origin', ''), 'port': port,
                'upstream': f'http://127.0.0.1:{port}', 'connections': grants,
                'listening': bool(self.listener.thread and self.listener.thread.is_alive() and self.listener.port == port)}

    def clear_temporary(self):
        with self.g.store.transaction() as data:
            config = data.get('remote_bridge', {})
            if config.get('mode') != 'temporary':
                return
            for grant in data['grants'].values():
                if grant.get('cloud_origin') == config.get('origin') and grant.get('cloud_client') and not grant['revoked']:
                    grant['revoked'] = True
                    self.g.audit(data, grant, 'connection', 'revoked')
            data['remote_bridge'] = {'enabled':False, 'origin':'', 'port':config['port']}

    def stop_temporary(self, tunnel=None):
        with self.lock:
            if self.tunnel is None or (tunnel is not None and self.tunnel is not tunnel):
                return
            current, self.tunnel = self.tunnel, None
            self.clear_temporary()
            current.stop()
            self.listener.stop()

    def close(self):
        with self.lock:
            self.closed = True
            self.stop_temporary()

    def start_temporary(self, approved):
        if approved is not True:
            raise Denied('Approve the temporary HTTPS link before connecting.')
        with self.lock:
            if self.closed:
                raise Denied('Unlock Airlock before starting a link.')
            state = self.state()
            if self.tunnel and state['verified']:
                return state
            if self.tunnel:
                raise Denied('The temporary link is starting.')
            with self.g.store.transaction() as data:
                live_https = any(g.get('cloud_origin') and not g['revoked'] and g['expires'] > self.g.clock()
                                 and g['remaining'] > 0 for g in data['grants'].values())
            if state['enabled'] or live_https:
                raise Denied('Pause the current bridge and revoke its active HTTPS grants before changing the link.')
            self.listener.ensure(state['port'])
            tunnel = self.tunnel = self.tunnel_factory(self.g.store.path.parent / 'cloudflare-helper')
        try:
            origin = tunnel.start(state['port'], self.stop_temporary)
            with self.lock:
                if self.closed or self.tunnel is not tunnel or tunnel.cancel.is_set():
                    raise Denied('The link was stopped.')
                with self.g.store.transaction() as data:
                    data['remote_bridge'] = {'origin':origin, 'enabled':True, 'port':state['port'],
                                             'mode':'temporary', 'verified':False}
            self.listener.verify_local(origin, tunnel.cancel)
            self.verify(origin, tunnel.cancel)
            with self.lock:
                if self.closed or self.tunnel is not tunnel or tunnel.cancel.is_set():
                    raise Denied('The link was stopped.')
                with self.g.store.transaction() as data:
                    data['remote_bridge']['verified'] = True
                return self.state()
        except Denied:
            self.stop_temporary(tunnel)
            raise
        except Exception:
            self.stop_temporary(tunnel)
            raise Denied('Airlock could not prepare the Cloudflare helper. Check your network and try again.') from None

    def configure(self, origin, port, enabled):
        with self.lock:
            if self.closed:
                raise Denied('Unlock the workspace before configuring a bridge.')
            if self.tunnel:
                if enabled is False:
                    self.stop_temporary()
                    return self.state()
                raise Denied('Stop the temporary link before switching domains.')
            return self._configure(origin, port, enabled)

    def _configure(self, origin, port, enabled):
        if type(enabled) is not bool or type(port) is not int or not 1024 <= port <= 65535:
            raise Denied('Choose an unprivileged bridge port from 1024 to 65535.')
        if enabled:
            origin = public_origin(origin)
            self.listener.ensure(port)
        with self.g.store.transaction() as data:
            old = data.get('remote_bridge', {})
            if enabled and old.get('origin') not in (None, '', origin):
                if any(g.get('cloud_client') and g['cloud_client'] != 'chatgpt' and not g['revoked'] and
                       g['expires'] > self.g.clock() and g['remaining'] > 0 for g in data['grants'].values()):
                    raise Denied('Revoke active HTTPS connections before changing their domain.')
            data['remote_bridge'] = {'origin': origin if enabled else old.get('origin', ''), 'port': port, 'enabled': enabled}
        if not enabled:
            self.listener.stop()
        return self.state()

    def create(self, vendor, lifetime, max_calls):
        with self.lock:
            if self.closed:
                raise Denied('Unlock the workspace before creating a connection.')
            return self._create(vendor, lifetime, max_calls)

    def _create(self, vendor, lifetime, max_calls):
        if vendor not in VENDORS:
            raise Denied('Choose a supported cloud client.')
        state = self.state()
        if vendor != 'chatgpt' and not (state['enabled'] and state['listening'] and (state['mode'] != 'temporary' or state['verified'])):
            raise Denied('Set up the HTTPS bridge first.')
        result = self.g.create(agent='mcp', purpose='Private connection for ' + VENDORS[vendor],
                               views=[], mode='automatic', approved=True, lifetime=lifetime, max_calls=max_calls)
        identifier = result['id']
        try:
            AgentMemory(self.g).configure(identifier, [], disclose=False, compute=False, proposals=False)
            with self.g.store.transaction() as data:
                data['grants'][identifier].update(cloud_client=vendor, display_name=VENDORS[vendor])
                if vendor != 'chatgpt':
                    if data.get('remote_bridge', {}).get('origin') != state['origin'] or not data['remote_bridge']['enabled']:
                        raise Denied('The HTTPS bridge changed. Reload and retry.')
                    data['grants'][identifier]['cloud_origin'] = state['origin']
            if vendor == 'chatgpt':
                folder = self.g.store.path.parent
                credential = folder / 'clients' / f'chatgpt-{identifier}.token'
                private_write(credential, result['token'])
                from .remote_tunnel import launch_command
                return {'id': identifier, 'command': launch_command(credential, folder / 'launch.json')}
            url = state['origin'] + ('/openapi.json' if vendor == 'muse' else '/mcp')
            setup = {'id': identifier, 'credential': result['token'], 'url': url}
            if vendor == 'ironclaw':
                from .ironclaw_adapter import manifest
                setup['manifest'] = manifest(url)
            return setup
        except Exception:
            self.g.revoke(identifier)
            raise

    def owner(self, action, body):
        schema = {'remote-state': (), 'remote-quick-start': ('approved',), 'remote-quick-stop': (), 'remote-configure': ('origin', 'port', 'enabled'),
                  'remote-create': ('vendor', 'lifetime', 'max_calls')}
        if action not in schema or not isinstance(body, dict) or set(body) != set(schema[action]):
            raise Denied('Invalid cloud connection request.')
        if action == 'remote-state':
            return self.state()
        if action == 'remote-quick-start':
            return self.start_temporary(body['approved'])
        if action == 'remote-quick-stop':
            self.stop_temporary()
            return self.state()
        return (self.configure if action == 'remote-configure' else self.create)(**body)
