"""Local native-client configuration; never exports the underlying provider keys."""
import json
import os
from pathlib import Path
import re
import subprocess
from .core import Denied

ROOT=Path(__file__).resolve().parents[1]

def private_write(path, text):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as f:f.write(text)

def configure_claude(gateway,token):
    grant=gateway.authenticate(token)
    if grant['agent']!='claude-code':raise Denied('Use a Claude Code connection for this plugin.')
    private_write(ROOT/'.private/claude-code.token',token)
    from .clients import server_entry,install_config
    entry=server_entry(ROOT/'.private/claude-code.token')
    install_config('claude-code',entry)
    return {'message':'Airlock is connected. Restart Claude Code to load the connection.'}


def configure_dot(gateway,token,tunnel_id,runtime_key):
    if gateway.authenticate(token)['agent']!='dot':raise Denied('Use a Dot connection for this tunnel.')
    if not isinstance(tunnel_id,str) or not re.fullmatch(r'tunnel_[A-Za-z0-9]+',tunnel_id):raise Denied('Invalid OpenAI tunnel ID.')
    if not isinstance(runtime_key,str) or not runtime_key.startswith('sk-') or len(runtime_key)>500:raise Denied('Enter the restricted OpenAI tunnel runtime key.')
    with gateway.store.transaction() as data:data['dot_tunnel']={'id':tunnel_id,'runtime_key':runtime_key}
    private_write(ROOT/'.private/dot.token',token)
    # Independent native callers may initialize concurrently. The local service
    # already supports authenticated stateless HTTP, avoiding shared stdio
    # lifecycle/request-ID collisions. The scoped credential goes only to the
    # fixed loopback endpoint; it is never part of the remote plugin or argv.
    env=dict(os.environ,CONTROL_PLANE_API_KEY=runtime_key,
             PRIVATE_AI_AGENT_AUTH='Bearer '+token,
             MCP_EXTRA_HEADERS='Authorization: env:PRIVATE_AI_AGENT_AUTH',
             MCP_DISCOVERY_EXTRA_HEADERS='Authorization: env:PRIVATE_AI_AGENT_AUTH')
    env.pop('MCP_STDIO_SEND_INITIALIZED_NOTIFICATION',None)
    binary=str(ROOT/'.tools/tunnel-client')
    args=[binary,'runtimes','connect','--alias','private-ai-dot','--tunnel-id',tunnel_id,'--mcp-server-url','http://127.0.0.1:8792/mcp','--runtime-api-key','env:CONTROL_PLANE_API_KEY','--profile-dir',str(ROOT/'.private/tunnel-profiles'),'--json']
    try:
        r=subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
        if r.returncode:raise Denied('OpenAI could not start the tunnel. Check the tunnel ID, workspace association and Tunnels Read + Use permissions. The local connection is still protected.')
        r=subprocess.run([binary,'runtimes','status','private-ai-dot','--json'],env=env,capture_output=True,text=True,timeout=15)
        status=json.loads(r.stdout)
        # Return only documented status booleans, never runtime/config dumps.
        def find(x,key):
            if isinstance(x,dict):
                if key in x and isinstance(x[key],bool):return x[key]
                for v in x.values():
                    r=find(v,key)
                    if r is not None:return r
            return None
        return {'running':find(status,'process_running'),'healthy':find(status,'healthy'),'ready':find(status,'ready'),'message':'Tunnel configured. Verify Ready, then register it under ChatGPT → Plugins → Add custom MCP server → Tunnel.'}
    except (subprocess.SubprocessError,ValueError,OSError):raise Denied('The tunnel setup did not finish. No additional data was released.') from None

def dot_status():
    try:
        r=subprocess.run([str(ROOT/'.tools/tunnel-client'),'runtimes','status','private-ai-dot','--json'],capture_output=True,text=True,timeout=10)
        state=json.loads(r.stdout)
        return {k:state.get(k,False) is True for k in ('process_running','healthy','ready')}
    except (subprocess.SubprocessError,ValueError,OSError):return {'process_running':False,'healthy':False,'ready':False}


def saved_dot_available(gateway):
    with gateway.store.transaction() as data:
        saved=data.get('dot_tunnel',{})
        return bool(saved.get('id') and saved.get('runtime_key'))


def restore_dot(gateway, token=None):
    """Reuse existing setup, never renew a grant or create account credentials."""
    replacing=token is not None
    if token is None:
        try:token=(ROOT/'.private/dot.token').read_text().strip()
        except OSError:raise Denied('Review and approve a Dot connection first.') from None
    identity=gateway.authenticate(token)
    if identity['agent']!='dot':raise Denied('Choose an approved Dot connection.')
    with gateway.store.transaction() as data:
        grant=data['grants'][identity['id']]
        if grant['remaining']<=0:raise Denied('This connection reached its call limit. Review and approve a new connection.')
        saved=dict(data.get('dot_tunnel',{}))
    if not saved.get('id') or not saved.get('runtime_key'):
        raise Denied('Set up your OpenAI tunnel once before reconnecting it here.')
    if not replacing:
        state=dot_status()
        if all(state.values()):
            return {'running':True,'healthy':True,'ready':True,'message':'Your saved Dot connection is ready. Existing sharing limits are unchanged.'}
    result=configure_dot(gateway,token,saved['id'],saved['runtime_key'])
    if not all(result.get(k) for k in ('running','healthy','ready')):
        raise Denied('The tunnel has not become ready. Check the saved setup and try reconnecting again. Sharing limits were not extended.')
    result['message']='Saved Dot setup restored. Your existing private plugin uses this approved connection; no key entry or plugin registration is needed.'
    return result

