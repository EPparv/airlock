"""Local native-client configuration; never exports the underlying provider keys."""
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from .remote_tunnel import TUNNEL_PHASE, failure_phase, tunnel_binary, valid_tunnel_id
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


def dot_credential_path(gateway):
    path = gateway.store.path.parent / 'dot.token'
    if not path.exists() and (ROOT/'.private/dot.token').is_file():
        return ROOT/'.private/dot.token'
    return path


def dot_status(binary=None):
    binary = binary or tunnel_binary(ROOT)
    status = {'process_running':False, 'healthy':False, 'ready':False}
    if not binary:
        return status
    try:
        response = subprocess.run([binary,'runtimes','status','private-ai-dot','--json'],
                                  capture_output=True,text=True,timeout=10)
        if response.returncode:
            return status
        data = json.loads(response.stdout)
        def value(item, key):
            if isinstance(item,dict):
                if type(item.get(key)) is bool:
                    return item[key]
                for nested in item.values():
                    found = value(nested, key)
                    if found is not None:
                        return found
            return None
        return {key:value(data,key) is True for key in status}
    except (subprocess.SubprocessError,ValueError,OSError):
        return status


def configure_dot(gateway,token,tunnel_id,runtime_key):
    if gateway.authenticate(token)['agent'] != 'dot':
        raise Denied('Use a Dot connection for this tunnel.')
    if not valid_tunnel_id(tunnel_id):
        raise Denied('Enter the OpenAI tunnel ID.')
    if not isinstance(runtime_key,str) or not runtime_key.startswith('sk-') or not 8 <= len(runtime_key) <= 500:
        raise Denied('Enter the restricted OpenAI tunnel runtime key.')
    binary = tunnel_binary(ROOT)
    if not binary:
        raise Denied(TUNNEL_PHASE['missing'])
    folder = gateway.store.path.parent
    try:
        url = json.loads((folder/'launch.json').read_text())['mcp_url']
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path != '/mcp' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise Denied('Open your Airlock workspace on the Mac before connecting Dot.') from None
    env = dict(os.environ, CONTROL_PLANE_API_KEY=runtime_key, PRIVATE_AI_AGENT_AUTH='Bearer '+token,
               MCP_EXTRA_HEADERS='Authorization: env:PRIVATE_AI_AGENT_AUTH',
               MCP_DISCOVERY_EXTRA_HEADERS='Authorization: env:PRIVATE_AI_AGENT_AUTH')
    env.pop('MCP_STDIO_SEND_INITIALIZED_NOTIFICATION',None)
    args=[binary,'runtimes','connect','--alias','private-ai-dot','--tunnel-id',tunnel_id,'--mcp-server-url',url,
          '--runtime-api-key','env:CONTROL_PLANE_API_KEY','--profile-dir',str(folder/'tunnel-profiles'),'--json']
    try:
        result = subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
        if result.returncode:
            raise Denied(TUNNEL_PHASE[failure_phase(result.stdout + result.stderr)])
        status = dot_status(binary)
        if not all(status.values()):
            raise Denied('The OpenAI runtime has not reported ready. Check the tunnel association and retry.')
        private_write(folder/'dot.token',token)
        with gateway.store.transaction() as data:
            data['dot_tunnel'] = {'id':tunnel_id,'runtime_key':runtime_key}
        return {'running':True,'healthy':True,'ready':True,
                'message':'The local tunnel is ready. Install this dedicated tunnel in your Dot’s ChatGPT workspace.'}
    except Denied:
        raise
    except subprocess.TimeoutExpired:
        raise Denied(TUNNEL_PHASE['timeout']) from None
    except (ValueError,OSError,subprocess.SubprocessError):
        raise Denied('Could not run the OpenAI tunnel client on this Mac.') from None


def saved_dot_available(gateway):
    with gateway.store.transaction() as data:
        saved=data.get('dot_tunnel',{})
        return bool(saved.get('id') and saved.get('runtime_key'))


def restore_dot(gateway, token=None):
    """Reuse existing setup, never renew a grant or create account credentials."""
    replacing=token is not None
    if token is None:
        try:token=dot_credential_path(gateway).read_text().strip()
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

