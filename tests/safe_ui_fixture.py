"""Browser fixture: disposable profile, fixed test key, no personal source access."""
import sys
import json
from pathlib import Path
import uvicorn
from privacy_layer import clients, sources
from privacy_layer.safe_test import SafeTest

root=Path(__file__).resolve().parents[1]
state=Path(sys.argv[1]);profile=state/'profile';profile.mkdir(parents=True)
clients.ROOT=state/'app'
original=sources.LocalSources
sources.LocalSources=lambda **kw:original(key=b'b'*32,context_home=profile)
# Reproduce a valid Codex config that still points to an earlier Airlock copy.
old=state/'old-source';old_entry={'command':str(old/'.venv/bin/python'),'args':[str(old/'privacy_layer/stdio.py'),'--token-file',str(old/'.private/clients/old.token')]}
config=profile/'.codex/config.toml';config.parent.mkdir(parents=True)
config.write_text('# Keep this preference\nmodel = "fixture"\n# Airlock managed connection — begin\n[mcp_servers.airlock]\ncommand = '+json.dumps(old_entry['command'])+'\nargs = '+json.dumps(old_entry['args'])+'\n# Airlock managed connection — end\n')
from privacy_layer.core import EncryptedStore
from privacy_layer.context import ContextHub
store=EncryptedStore(state/'state/connections.enc',b'b'*32)
hub=ContextHub(store,home=profile)
p=hub.preview('fictional.json',json.dumps({'memories':['Cypress launch is November 20.',{'text':'FICTIONAL_PRIVATE_PERSONAL','device_only':True}],'skills':['Use two concise bullets.']}).encode())
hub.commit(p['id'],list(range(len(p['items']))),[])
c=SafeTest(root,state/'state',profile_home=profile)
uvicorn.run(c.app('fictional-browser-owner',int(sys.argv[2])),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
