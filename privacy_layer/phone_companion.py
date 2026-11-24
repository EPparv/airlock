"""Narrow, session-only iPhone access to a user's unlocked Mac over its agent bridge."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

from starlette.responses import FileResponse, JSONResponse, Response

from .agent_memory import AgentMemory
from .clients import selected_scope
from .core import Denied


UI = Path(__file__).resolve().parents[1] / 'ui'
ASSETS = {'/phone': 'phone.html', '/phone/phone.js': 'phone.js', '/phone/phone.css': 'phone.css'}
TOOLS = {'/phone/context': ('get_private_context', {'query'}),
         '/phone/actions': ('list_private_actions', set()),
         '/phone/request': ('request_private_action', {'reference'})}
HEADERS = {'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer', 'X-Content-Type-Options':'nosniff',
           'X-Frame-Options':'DENY', 'Permissions-Policy':'camera=(), microphone=(), geolocation=()',
           'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}
PAIR_TTL, SESSION_TTL, CALL_BUDGET = 300, 3600, 100
_init_lock = threading.Lock()


def fingerprint(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', value):
        raise Denied('This connection has closed.')
    return hashlib.sha256(value.encode('ascii')).hexdigest()


class PhoneCompanion:
    """The gateway holds exchange/session secrets in RAM for the current unlock only."""
    def __init__(self, gateway):
        self.g = gateway
        with _init_lock:
            if not hasattr(gateway, '_phone_sessions'):
                with gateway.store.transaction() as data:
                    for grant in data['grants'].values():
                        if grant.get('cloud_client') == 'iphone' and not grant['revoked']:
                            grant['revoked'] = True
                            gateway.audit(data, grant, 'iphone', 'session ended')
                gateway._phone_sessions = (threading.RLock(), {})
            self.lock, self.sessions = gateway._phone_sessions

    def _prune(self, data):
        now = self.g.clock()
        for key, entry in list(self.sessions.items()):
            grant = data['grants'].get(entry['id'])
            if (not grant or grant['revoked'] or grant['expires'] <= now or
                    not entry['session'] and entry['deadline'] <= now):
                if grant and not grant['revoked']:
                    grant['revoked'] = True
                    self.g.audit(data, grant, 'iphone', 'expired')
                del self.sessions[key]

    def owner(self, action, body):
        if action == 'phone-state' and body == {}:
            with self.lock, self.g.store.transaction() as data:
                self._prune(data)
                return {'devices': [
                    {'id':e['id'], 'state':'paired' if e['session'] else 'waiting',
                     'expires':data['grants'][e['id']]['expires'] if e['session'] else e['deadline'],
                     'last_read':data['grants'][e['id']].get('last_context_read')}
                    for e in self.sessions.values()]}
        if action == 'phone-revoke' and set(body) == {'id'}:
            with self.lock, self.g.store.transaction() as data:
                g = data['grants'].get(body['id']) if isinstance(body['id'], str) else None
                if not g or g.get('cloud_client') != 'iphone':
                    raise Denied('Choose an iPhone connection.')
                g['revoked'] = True
                self.g.audit(data, g, 'iphone', 'revoked')
                self._prune(data)
            return {'revoked':True}
        if action != 'phone-create' or set(body) != {'selection','approved'} or body['approved'] is not True:
            raise Denied('Review the iPhone connection first.')
        scope = selected_scope(self.g, body['selection'])
        if scope['compute']:
            raise Denied('Choose only shareable excerpts for the phone.')
        with self.lock:
            with self.g.store.transaction() as d:
                self._prune(d)
                config = dict(d.get('remote_bridge', {}))
                if not config.get('enabled'):
                    raise Denied('Enable the HTTPS bridge first.')
                if len(self.sessions) >= 8:
                    raise Denied('Revoke an existing phone connection before pairing another.')
            grant = self.g.create(agent='mcp', purpose='iPhone companion', views=[], mode='automatic',
                                  approved=True, lifetime=SESSION_TTL, max_calls=CALL_BUDGET)
            try:
                AgentMemory(self.g).configure(grant['id'], **scope)
                code = secrets.token_urlsafe(32)
                deadline = self.g.clock() + PAIR_TTL
                with self.g.store.transaction() as d:
                    if d.get('remote_bridge') != config:
                        raise Denied('The HTTPS bridge changed. Pair again.')
                    d['grants'][grant['id']].update(cloud_client='iphone', display_name='iPhone',
                                                    cloud_origin=config['origin'])
                # Only the internal server knows the gateway token. The phone receives a narrow session.
                self.sessions[fingerprint(code)] = {'id':grant['id'], 'token':grant['token'],
                                                    'deadline':deadline, 'session':False}
            except Exception:
                self.g.revoke(grant['id'])
                raise
            return {'id':grant['id'], 'url':config['origin'] + '/phone#pair=' + code, 'expires':deadline}

    def access(self, secret, origin, pair=False):
        key = fingerprint(secret)
        with self.lock, self.g.store.transaction() as d:
            self._prune(d)
            entry = self.sessions.get(key)
            cfg = d.get('remote_bridge', {})
            if not entry or entry['session'] == pair or not cfg.get('enabled') or cfg.get('origin') != origin:
                raise Denied('This phone connection has closed.')
            g = self.g._grant(d, entry['token'])
            if g.get('cloud_origin') != origin or g.get('cloud_client') != 'iphone' or g.get('scope') is None:
                raise Denied('This phone connection has closed.')
            if pair:
                session = secrets.token_urlsafe(32)
                del self.sessions[key]
                self.sessions[fingerprint(session)] = {**entry, 'session':True}
                self.g.audit(d, g, 'iphone', 'paired')
                return {'session':session, 'expires':g['expires']}
            return {**entry, 'expires':g['expires'], 'remaining':g['remaining'],
                    'count':len(g['scope'].get('disclose_records', g['scope']['records'])) if g['scope'].get('disclose') else 0}

    def operate(self, path, body, secret, origin):
        entry = self.access(secret, origin)
        if path == '/phone/disconnect':
            self.owner('phone-revoke', {'id':entry['id']})
            return {'closed':True}
        if path == '/phone/status':
            return {k:entry[k] for k in ('expires','remaining','count')}
        tool, _ = TOOLS[path]
        result = self.g.call(entry['token'], tool, body)
        self.access(secret, origin)
        if path == '/phone/context':
            return {'items':[{k:item[k] for k in ('kind','text') if k in item} for item in result['items']],
                    'next_query':result.get('next_query') or ''}
        if path == '/phone/actions':
            return {'actions':result['actions']}
        return {k:result[k] for k in ('status','kind','label') if k in result}


async def phone_response(active, req):
    path = req.url.path
    if path not in ASSETS and path not in TOOLS and path not in ('/phone/pair','/phone/status','/phone/disconnect'):
        return Response(status_code=404, headers=HEADERS)
    if req.scope.get('query_string'):
        return Response(status_code=400, headers=HEADERS)
    gateway = active()
    if gateway is None:
        return Response(status_code=503, headers=HEADERS)
    with gateway.store.transaction() as d:
        config = dict(d.get('remote_bridge', {}))
    origin = config.get('origin','')
    if not config.get('enabled'):
        return Response(status_code=503, headers=HEADERS)
    if req.headers.get('host') != urlsplit(origin).netloc or req.headers.get('origin') not in (None,origin):
        return Response(status_code=403, headers=HEADERS)
    if path in ASSETS:
        if req.method not in ('GET','HEAD'):
            return Response(status_code=405, headers=HEADERS)
        return FileResponse(UI / ASSETS[path], headers=HEADERS)
    if req.method != 'POST':
        return Response(status_code=405, headers=HEADERS)
    if req.headers.get('origin') != origin or req.headers.get('sec-fetch-site') not in (None,'same-origin'):
        return Response(status_code=403, headers=HEADERS)
    if req.headers.get('content-type','').split(';')[0].lower() != 'application/json':
        return Response(status_code=415, headers=HEADERS)
    raw = bytearray()
    async for chunk in req.stream():
        if len(raw) + len(chunk) > 16384:
            return Response(status_code=413, headers=HEADERS)
        raw.extend(chunk)
    try:
        args = json.loads(raw)
        fields = {'code'} if path == '/phone/pair' else TOOLS[path][1] if path in TOOLS else set()
        if not isinstance(args,dict) or set(args) != fields or any(not isinstance(v,str) for v in args.values()):
            return Response(status_code=400, headers=HEADERS)
        phone = PhoneCompanion(gateway)
        if path == '/phone/pair':
            result = await asyncio.to_thread(phone.access, args['code'], origin, True)
        else:
            token = req.headers.get('authorization', '')
            if not token.startswith('Bearer '):
                return Response(status_code=401, headers=HEADERS)
            secret = token[7:]
            # Distinguish a closed session from a valid device without the requested permission.
            try:
                await asyncio.to_thread(phone.access, secret, origin)
            except Denied:
                return JSONResponse({'error':'This connection has closed. Pair again on your Mac.'}, 401, headers=HEADERS)
            result = await asyncio.to_thread(phone.operate, path, args, secret, origin)
        if active() is not gateway:
            return Response(status_code=403, headers=HEADERS)
        return JSONResponse(result, headers=HEADERS)
    except Denied as error:
        return JSONResponse({'error':str(error)}, 403, headers=HEADERS)
    except (ValueError, RecursionError):
        return Response(status_code=400, headers=HEADERS)
