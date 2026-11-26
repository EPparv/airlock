"""Owner-initiated, scoped proof that an agent can return a fresh status reply."""
import hmac
import secrets

from .core import Denied

TTL = 600
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def status_reply(grant, now, route):
    """Runs inside the ordinary authenticated call transaction, before any source access."""
    check = grant.get('provider_check')
    if not check or check['expires'] <= now:
        return None
    expected_route = 'local' if grant['cloud_client'] == 'chatgpt' else 'https-bridge'
    if route != expected_route:
        raise Denied('Use the connection being tested to request its status.')
    if 'code' not in check:
        check['code'] = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        check['received'] = now
    return {'connection_check': check['code'], 'execution': {'tool': 'privacy_status', 'status': 'success'}}


class ProviderChecks:
    def __init__(self, gateway, remote):
        self.g = gateway
        self.remote = remote

    def owner(self, action, body):
        from .remote_clients import VENDORS
        schema = {'provider-check-state': {'id'}, 'provider-check-start': {'id'},
                  'provider-check-confirm': {'id', 'code'}, 'provider-check-cancel': {'id'}}
        if action not in schema or not isinstance(body, dict) or set(body) != schema[action] or not isinstance(body['id'], str):
            raise Denied('Choose a cloud connection.')
        now = self.g.clock()
        with self.g.store.transaction() as data:
            grant = data['grants'].get(body['id'])
            if not grant or grant.get('cloud_client') not in VENDORS:
                raise Denied('Choose a cloud connection.')
            vendor = grant['cloud_client']
            bridge = data.get('remote_bridge', {})
            live = not grant['revoked'] and grant['expires'] > now
            if not live or grant.get('provider_check', {}).get('expires', now + 1) <= now:
                grant.pop('provider_check', None)
            setup = {}
            if vendor == 'chatgpt':
                path = self.g.store.path.parent / 'clients' / ('chatgpt-' + grant['id'] + '.token')
                ready = path.is_file()
                if ready and live:
                    from .remote_tunnel import launch_command
                    setup['tunnel_command'] = launch_command(path, self.g.store.path.parent / 'launch.json')
                local = 'Dedicated credential available' if ready else 'Dedicated credential file missing'
            else:
                listener = self.remote.listener
                ready = (bridge.get('enabled') and (bridge.get('mode') != 'temporary' or bridge.get('verified'))
                         and bridge.get('origin') == grant.get('cloud_origin')
                         and listener.thread and listener.thread.is_alive() and listener.port == bridge.get('port'))
                local = 'Agent bridge listening' if ready else 'HTTPS bridge paused or unavailable'
                if ready and live:
                    setup['url'] = grant['cloud_origin'] + ('/openapi.json' if vendor == 'muse' else '/mcp')
            if action == 'provider-check-start':
                if not live or grant['remaining'] <= 0:
                    raise Denied('Create or renew a connection with calls available.')
                if not ready:
                    raise Denied('Restore the local connection setup before starting.')
                if 'provider_check' not in grant:
                    grant['provider_check'] = {'expires': min(now + TTL, grant['expires'])}
            elif action == 'provider-check-confirm':
                check = grant.get('provider_check', {})
                code = body['code']
                supplied = code.strip().upper() if isinstance(code, str) and len(code) < 32 else ''
                if not (supplied.isascii() and check.get('code') and hmac.compare_digest(check['code'], supplied)):
                    raise Denied('Enter the current code received from this connection.')
                grant['provider_confirmed'] = now
                del grant['provider_check']
            elif action == 'provider-check-cancel':
                grant.pop('provider_check', None)
            check = grant.get('provider_check', {})
            return {**setup, 'vendor':vendor, 'local':local, 'can_start':bool(live and ready and grant['remaining'] > 0),
                    'active':live, 'remaining':grant['remaining'], 'expires':check.get('expires'),
                    'received':check.get('received'), 'confirmed':grant.get('provider_confirmed')}
