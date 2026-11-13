"""Exercise the actual allowlisted payload, without an adjacent companion repo."""
import json
import os
from pathlib import Path
import subprocess
import sys

from macos.package import entries, VERSION


def test_packaged_payload_runs_in_isolation(tmp_path):
    files=entries()
    assert json.loads(files['release.json'])['version']==VERSION
    assert 'vendor/private_ai/google_client.json' not in files
    assert not any('.private' in Path(p).parts or p.endswith(('.enc','.token','.key')) for p in files)
    for name,data in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    # New process: no cached imports or repository paths can hide missing files.
    code='''
from pathlib import Path
from privacy_layer.sources import LocalSources
from privacy_layer.core import Gateway, EncryptedStore
from privacy_layer.server import owner_app
from starlette.testclient import TestClient
s=LocalSources(key=b'x'*32,context_home=Path('empty-profile'))
g=Gateway(EncryptedStore(Path('test-state.enc'),s.key),s)
s.connection_store=g.store
with TestClient(owner_app(g,'test-owner'),base_url='http://127.0.0.1:8791') as c:
    headers={'Authorization':'Bearer test-owner'}
    r=c.post('/api/dashboard',json={},headers=headers)
    assert r.status_code==200,r.text
    assert r.json()['counts']=={'memories':0,'skills':0}
    assert r.json()['gmail']['configured'] is False
    for asset in ('/','/memory','/memory.js','/memory.css','/near.js','/near.css','/onboarding.js'):
        assert c.get(asset).status_code==200,asset
    assert c.post('/api/memory-state',json={},headers=headers).status_code==200
    assert c.post('/api/state',json={}).status_code==401
'''
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')}
    result=subprocess.run([sys.executable,'-c',code],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
