"""Browser fixture: disposable profile, fixed test key, no personal source access."""
import sys
import json
import os
from types import SimpleNamespace
from pathlib import Path
import uvicorn
from privacy_layer import agent_launch, clients, quick_connect, remote_clients, sources
from privacy_layer.safe_test import SafeTest

root=Path(__file__).resolve().parents[1]
state=Path(sys.argv[1]);profile=state/'profile';profile.mkdir(parents=True,exist_ok=True)
for variable in ('CODEX_HOME', 'XDG_CONFIG_HOME', 'COPILOT_HOME', 'OPENCLAW_PROFILE',
                 'OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH'):
    os.environ.pop(variable, None)
clients.ROOT=state/'app'
# Only the final OS launch is replaced. The browser still uses actual owner
# authentication, grant creation, configuration writes, and connection status.
quick_connect.launch_options=lambda:[*sorted(agent_launch.LOCAL_AGENTS), 'dot','mcp']
def record_open(agent):
    with (state/'launched.jsonl').open('a') as log:
        log.write(json.dumps({'agent':agent})+'\n')
    return {'opened':True,'drafted':True,'method':'draft','message':'Status request prepared in the agent.'}
agent_launch.open_agent=record_open
# Use the real remote receipt and safe browser-link path without opening an
# external provider or Terminal on the machine running this synthetic suite.
remote_clients.sys=SimpleNamespace(platform='linux')
# Simulate macOS accepting the first launch; signup and manual retries take
# the normal non-Mac fallback so Chromium never navigates to a real account.
open_provider = remote_clients.open_provider
def fixture_provider(vendor, setup=False, **options):
    result = open_provider(vendor, setup, **options)
    if vendor in ('muse', 'manus') and options.get('prepare_request', True):
        result.update(opened=True, prepared='request' in result)
    return result
remote_clients.open_provider = fixture_provider
original=sources.LocalSources
sources.LocalSources=lambda **kw:original(key=b'b'*32,context_home=profile)
# Reproduce a valid Codex config that still points to an earlier Airlock copy.
old=state/'old-source';old_entry={'command':str(old/'.venv/bin/python'),'args':[str(old/'privacy_layer/stdio.py'),'--token-file',str(old/'.private/clients/old.token')]}
config=profile/'.codex/config.toml';config.parent.mkdir(parents=True,exist_ok=True)
if not config.exists():
    config.write_text('# Keep this preference\nmodel = "fixture"\n# Airlock managed connection — begin\n[mcp_servers.airlock]\ncommand = '+json.dumps(old_entry['command'])+'\nargs = '+json.dumps(old_entry['args'])+'\n# Airlock managed connection — end\n')
from privacy_layer.core import EncryptedStore
from privacy_layer.context import ContextHub
if not (state/'state/connections.enc').exists():
    store=EncryptedStore(state/'state/connections.enc',b'b'*32)
    hub=ContextHub(store,home=profile)
    p=hub.preview('fictional.json',json.dumps({'memories':['Cypress launch is November 20.','Medical appointment is Thursday.',{'text':'FICTIONAL_PRIVATE_PERSONAL','device_only':True}],'skills':['Use two concise bullets.']}).encode())
    hub.commit(p['id'],list(range(len(p['items']))),[])
c=SafeTest(root,state/'state',profile_home=profile)
test_owner=sys.argv[3] if len(sys.argv)>3 else 'fictional-browser-owner'
uvicorn.run(c.app(test_owner,int(sys.argv[2])),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
