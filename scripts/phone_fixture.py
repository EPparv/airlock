"""Disposable iOS WebKit test fixture. Only loopback and synthetic records."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from urllib.parse import urlsplit

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy_layer.core import Gateway, EncryptedStore, digest
from privacy_layer.phone_companion import PhoneCompanion
from privacy_layer.device_apps import ExampleApps
from privacy_layer.remote_clients import BridgeApp
from privacy_layer.workspace import Workspace


class FictionalSources:
    def library(self):
        return [
            {'kind':'memories','source_id':'schedule',
             'text':'The fictional Cypress rehearsal begins on Thursday. Email: robin@example.test.'},
            {'kind':'memories','source_id':'unselected','text':'The unshared archive phrase is Vermilion Finch.'},
            {'kind':'memories','source_id':'local','text':'Never show the device-only stone.','device_only':True}]
    def protected(self):
        return []
    def read(self, kind, identifier):
        return next(row for row in self.library() if (row['kind'],row['source_id']) == (kind,identifier))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--pair-output', type=Path, required=True)
    p.add_argument('--public-origin', required=True)
    args = p.parse_args()
    origin = args.public_origin
    target = urlsplit(origin)
    if target.hostname not in ('localhost','127.0.0.1') or target.scheme != 'https' or not target.port:
        raise ValueError('The test frontend must be HTTPS loopback.')
    args.state.mkdir(mode=0o700,parents=True,exist_ok=True)
    source = FictionalSources()
    g = Gateway(EncryptedStore(args.state/'fictional.enc',secrets.token_bytes(32)),source)
    g.device_apps = ExampleApps()
    with g.store.transaction() as d:
        d['remote_bridge'] = {'enabled':True,'port':args.port,'origin':origin}
    ref = source.library()[0]
    pairing = PhoneCompanion(g).owner('phone-create', {'approved':True,'selection':{'memories:schedule':digest(ref['text'])}})
    Workspace(g).create('email','Review fictional follow-up',[pairing['id']],
                        {'recipients':'review@example.test','subject':'Fictional rehearsal','body':'Fixture only.'})
    # Bind before publishing the one-time link so the iOS launcher sees a ready upstream.
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        sock.bind(('127.0.0.1',args.port));sock.listen(32)
        out = args.pair_output.with_suffix('.tmp')
        with os.fdopen(os.open(out, os.O_EXCL|os.O_CREAT|os.O_WRONLY, 0o600),'w') as dst:
            json.dump({'path':pairing['url'][len(origin):]},dst)
        os.replace(out,args.pair_output)
        server = uvicorn.Server(uvicorn.Config(BridgeApp(lambda:g,args.port),host='127.0.0.1',
                                log_level='error',access_log=False,proxy_headers=False))
        server.run(sockets=[sock])


if __name__ == '__main__':
    main()
