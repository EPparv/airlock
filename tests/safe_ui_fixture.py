"""Browser fixture: disposable profile, fixed test key, no personal source access."""
import sys
import json
import os
from pathlib import Path
import uvicorn
from privacy_layer import agent_launch, clients, quick_connect, remote_clients, sources
from privacy_layer.safe_test import SafeTest

root=Path(__file__).resolve().parents[1]
state=Path(sys.argv[1]);profile=state/'profile';profile.mkdir(parents=True)
for variable in ('CODEX_HOME', 'XDG_CONFIG_HOME', 'COPILOT_HOME', 'OPENCLAW_PROFILE',
                 'OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH'):
    os.environ.pop(variable, None)
clients.ROOT=state/'app'
# Only the final OS launch is replaced. The browser still uses actual owner
# authentication, grant creation, configuration writes, and connection status.
quick_connect.launch_options=lambda:[*sorted(agent_launch.LOCAL_AGENTS), 'dot']
def record_open(agent):
    with (state/'launched.jsonl').open('a') as log:
        log.write(json.dumps({'agent':agent})+'\n')
    return {'opened':True,'drafted':True,'method':'draft','message':'Status request prepared in the agent.'}
agent_launch.open_agent=record_open
def provider_surface(vendor, setup):
    assert vendor == 'chatgpt' and setup
    return {'opened':False, 'url':'https://chatgpt.com/plugins', 'message':'Open ChatGPT to continue.'}
remote_clients.open_provider=provider_surface
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
p=hub.preview('fictional.json',json.dumps({'memories':['Cypress launch is November 20.','Medical appointment is Thursday.',{'text':'FICTIONAL_PRIVATE_PERSONAL','device_only':True}],'skills':['Use two concise bullets.']}).encode())
hub.commit(p['id'],list(range(len(p['items']))),[])
c=SafeTest(root,state/'state',profile_home=profile)
uvicorn.run(c.app('fictional-browser-owner',int(sys.argv[2])),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
