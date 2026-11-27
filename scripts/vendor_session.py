"""Disposable CI session; expose one real Airlock tool with an empty vault."""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import signal
import socket
import sys
import tempfile
import time
from pathlib import Path
from privacy_layer import remote_clients, server
from privacy_layer.core import Denied, EncryptedStore, Gateway
from privacy_layer.provider_checks import ProviderChecks
from smoke_quick_link import EmptySources, checked_offer, require, wait_for_file, write
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

class StatusOnly(Gateway):
    def call(self, token, tool, args, **kw):
        if tool != 'privacy_status' or args != {}:
            raise Denied('The empty test connection allows only privacy_status.')
        return super().call(token, tool, args, **kw)

def allow_operator_card():
    """QA-only static GET. The operator private key and grant never enter this route."""
    import re
    from urllib.parse import urlsplit
    from starlette.responses import Response
    page=(Path(__file__).resolve().parents[1]/'qa'/'clipboard-operator.html').read_text()
    scripts=re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>',page,flags=re.S|re.I)
    if not scripts:
        raise ValueError('Operator page needs its local script')
    hashes=' '.join("'sha256-"+base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()+"'" for s in scripts)
    headers={'Content-Security-Policy': "default-src 'none'; script-src "+hashes+"; style-src 'unsafe-inline'; connect-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'",
             'X-Content-Type-Options':'nosniff','Cache-Control':'no-store',
             'Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
             'Permissions-Policy':'clipboard-read=(), clipboard-write=(self), camera=(), microphone=(), geolocation=()',
             'X-Robots-Tag':'noindex, nofollow'}
    original=remote_clients.BridgeApp
    class FixtureBridge(original):
        async def response(self, req):
            if req.url.path != '/qa/operator':
                return await super().response(req)
            if req.method!='GET' or req.scope.get('query_string') or req.headers.get('origin') or req.headers.get('authorization'):
                return Response(status_code=404)
            gateway=self.gateway.active()
            if not gateway:
                return Response(status_code=404)
            with gateway.store.transaction() as data:
                state=data.get('remote_bridge',{})
                valid=(state.get('enabled') and state.get('verified') and
                       req.headers.get('host','')==urlsplit(state.get('origin','')).netloc)
            if not valid:
                return Response(status_code=404)
            return Response(page, media_type='text/html', headers=headers)
    remote_clients.BridgeApp=FixtureBridge

def restrict_catalogs():
    # The normal Airlock HTTP auth, calls, scopes and receipts remain in force.
    remote_clients.REST_TOOLS={'privacy_status':()}
    factory=server.mcp_app
    def status_server(*a, **kw):
        app, mcp=factory(*a, **kw)
        from mcp.server.fastmcp import FastMCP
        for tool in asyncio.run(FastMCP.list_tools(mcp)):
            if tool.name!='privacy_status':
                mcp.remove_tool(tool.name)
        return app,mcp
    server.mcp_app=status_server

def seal(directory, recipient, body):
    key=serialization.load_pem_public_key(recipient.read_bytes())
    require(isinstance(key,rsa.RSAPublicKey) and key.key_size==3072,'Invalid operator public key')
    # Envelope payload includes origin, capability and grant expiry. AES handles
    # URL and metadata size. RSA wraps only the disposable AES key.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    keybytes=AESGCM.generate_key(bit_length=256)
    iv=secrets.token_bytes(12)
    encrypted=AESGCM(keybytes).encrypt(iv,json.dumps(body).encode(),b'airlock-integration-v1')
    wrapped=key.encrypt(keybytes,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    write(directory,'sealed.json',{k:base64.b64encode(v).decode() for k,v in [('wrapped',wrapped),('iv',iv),('data',encrypted)]})

def session(directory, recipient, vendor):
    allow_operator_card()
    restrict_catalogs()
    with tempfile.TemporaryDirectory() as tmp, socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0)); port=reserved.getsockname()[1];reserved.close()
        g=StatusOnly(EncryptedStore(Path(tmp)/'empty.enc',secrets.token_bytes(32)),EmptySources())
        with g.store.transaction() as state: state['remote_bridge']={'port':port,'enabled':False}
        remote_clients.set_active_gateway(lambda:g)
        service=remote_clients.RemoteClients(g); check=ProviderChecks(g,service)
        grant=None;receipt={}
        try:
            state=service.owner('remote-quick-start',{'approved':True,'verification_method':'device'})
            nonce=secrets.token_hex(16)
            write(directory,'offer.json',{'url':state['verification']['url'],'nonce':nonce})
            _,origin=checked_offer(directory)
            proof=wait_for_file(directory,'proof.json',220)
            require(proof.get('nonce')==nonce,'Challenge mismatch')
            service.owner('remote-quick-confirm',{'code':proof['code']})
            # Expiry follows independent HTTPS verification; probes cannot extend it.
            grant=service.create(vendor,1200,3)
            check.owner('provider-check-start',{'id':grant['id']})
            with g.store.transaction() as data:
                deadline=data['grants'][grant['id']]['expires']
            seal(directory,recipient,{'url':grant['url'],'token':grant['credential'],'origin':origin,
                                      'expires':deadline,'vendor':vendor,'nonce':nonce})
            until=time.monotonic()+1200
            while time.monotonic()<until and g.clock()<deadline:
                with g.store.transaction() as state:
                    live=state['grants'][grant['id']]
                    tracking=live.get('provider_check',{})
                    if tracking.get('received') and tracking.get('code'):
                        digest=hashlib.sha256((nonce+tracking['code']).encode()).hexdigest()
                        receipt.update(returned_code_hash=digest,received=tracking['received'])
                        until=min(until,time.monotonic()+max(0,60-(g.clock()-tracking['received'])))
                if not receipt and tracking.get('expires', 0) <= g.clock() and g.clock()<deadline:
                    check.owner('provider-check-start',{'id':grant['id']})
                time.sleep(.5)
            receipt['authenticated_status_call']=bool(receipt)
        finally:
            if grant: g.revoke(grant['id'])
            remote_clients.set_active_gateway(lambda:None)
            service.close()
        require(not service.state()['enabled'],'Fixture bridge did not close')
        write(directory,'receipt.json',{**receipt,'revoked':bool(grant),'closed':True})
        print('Synthetic session closed. Status call observed:', receipt.get('authenticated_status_call',False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('dir',type=Path);p.add_argument('recipient',type=Path)
    p.add_argument('vendor',choices=['muse','manus','ironclaw','custom']);args=p.parse_args()
    os.umask(0o077);args.dir.mkdir(parents=True,exist_ok=True)
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(143))
    logging.disable(logging.CRITICAL)
    try:session(args.dir,args.recipient,args.vendor)
    except Exception as error:
        write(args.dir,'failed.json',{'failed':True})
        print('Synthetic host failed:',type(error).__name__,file=sys.stderr)
        sys.exit(1)
