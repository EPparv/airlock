"""Native local-client adapters. Each connection gets a separate scoped token.

Config exports contain local paths, never tokens or the owner credential. Only
the fixed privacy-layer server entry is installed; unrelated settings survive.
"""
import copy
import fcntl
import json
import os
from pathlib import Path
import secrets
import time
import tomllib

from .core import Denied, digest, suggest_redaction
from .setup import ROOT, private_write, restore_dot

SERVER = 'airlock'
LEGACY_SERVER = 'private-ai-privacy-layer'
CLIENTS = {
    'dot': {'name':'Dot', 'hint':'Your existing private OpenAI connection', 'mark':'D'},
    'codex': {'name':'Codex', 'hint':'Desktop app and command line on this Mac', 'mark':'⌘'},
    'claude-desktop': {'name':'Claude Desktop', 'hint':'Local tools in the Claude Mac app', 'mark':'✳'},
    'claude-code': {'name':'Claude Code', 'hint':'Your Claude coding workspace', 'mark':'C'},
    'cursor': {'name':'Cursor', 'hint':'Personal context in your editor', 'mark':'↗'},
    'mcp': {'name':'Other agents', 'hint':'Standard MCP connection on this Mac', 'mark':'+'},
    'ironclaw': {'name':'IronClaw', 'hint':'HTTPS MCP extension; secure endpoint setup required', 'mark':'I'},
}
RELATIVE_CONFIGS = {
    'codex':'.codex/config.toml',
    'claude-desktop':'Library/Application Support/Claude/claude_desktop_config.json',
    'claude-code':'.claude.json',
    'cursor':'.cursor/mcp.json',
}

def catalog(home=None):
    home=Path(home or Path.home())
    apps={'codex':('ChatGPT.app','ChatGPT 2.app','Codex.app'), 'claude-desktop':('Claude.app',), 'cursor':('Cursor.app',)}
    result=[]
    for agent,details in CLIENTS.items():
        installed=any((p/name).exists() for name in apps.get(agent,()) for p in (Path('/Applications'),home/'Applications'))
        if agent=='claude-code':installed=(ROOT/'.tools/node_modules/.bin/claude').exists()
        result.append(dict(id=agent,**details,app_present=installed,can_install=agent in RELATIVE_CONFIGS))
    return result

def server_entry(token_path):
    args=[str(ROOT/'privacy_layer/stdio.py'),'--token-file',str(token_path)]
    if (ROOT/'release.json').exists():args+=['--session-file',str(ROOT/'.private/launch.json')]
    return {'command':str(ROOT/'.venv/bin/python'), 'args':args}

def owned(entry):
    """Recognize our exact bridge layout, including an earlier installation.

    Never execute or read the old credential. Only this entry is replaced; the
    full settings file is backed up before writing. Custom entries stay intact.
    """
    if not isinstance(entry,dict) or set(entry)!={'command','args'}:return False
    command,args=entry.get('command'),entry.get('args')
    if not isinstance(command,str) or not isinstance(args,list) or len(args) not in (3,5) or any(not isinstance(a,str) for a in args):return False
    exe=Path(command)
    if not exe.is_absolute() or exe.parts[-3:]!=('.venv','bin','python') or '..' in exe.parts:return False
    root=exe.parents[2]
    if args[:2]!=[str(root/'privacy_layer/stdio.py'),'--token-file']:return False
    try:token=Path(args[2]).relative_to(root/'.private')
    except ValueError:return False
    if '..' in token.parts or token.suffix!='.token':return False
    return len(args)==3 or args[3:]==['--session-file',str(root/'.private/launch.json')]

def json_config(original, entry, server_name=SERVER):
    if server_name not in (SERVER,'airlock-test'):raise Denied('Invalid connection name.')
    value=json.loads(original or '{}')
    if not isinstance(value,dict) or not isinstance(value.get('mcpServers',{}),dict):raise Denied('The existing agent settings are not valid. They were left unchanged.')
    servers=value.setdefault('mcpServers',{})
    if server_name in servers and not owned(servers[server_name]):raise Denied('An unrelated connection already uses this name. Its settings were left unchanged.')
    if server_name==SERVER and LEGACY_SERVER in servers and owned(servers[LEGACY_SERVER]):servers.pop(LEGACY_SERVER)
    servers[server_name]=entry
    return json.dumps(value,ensure_ascii=False,indent=2)+'\n'

def codex_config(original,entry,server_name=SERVER):
    if server_name not in (SERVER,'airlock-test'):raise Denied('Invalid connection name.')
    before=tomllib.loads(original)
    servers=before.get('mcp_servers',{})
    if not isinstance(servers,dict):raise Denied('Codex settings are not valid. They were left unchanged.')
    label='Airlock' if server_name==SERVER else 'Airlock Test'
    start=f'# {label} managed connection — begin'
    end=f'# {label} managed connection — end'
    removed=[];ranges=[]
    # Migrate only verified entries belonging to this installation. Preserve
    # unrelated settings, and keep the same token/limits during a brand migration.
    entries=[(server_name,start,end)]
    if server_name==SERVER:entries.append((LEGACY_SERVER,'# Private AI managed connection — begin','# Private AI managed connection — end'))
    for name,left,right in entries:
        if name in servers:
            if not owned(servers[name]):
                if name==LEGACY_SERVER:continue
                raise Denied('Codex already has an unrelated Airlock connection. Its settings were left unchanged.')
            if original.count(left)!=1 or original.count(right)!=1:raise Denied('The existing managed connection needs review. No settings were changed.')
            a=original.index(left);b=original.index(right)+len(right)
            if b<a:raise Denied('The existing managed connection needs review. No settings were changed.')
            ranges.append((a,b));removed.append(name)
        elif left in original or right in original:raise Denied('The previous connection settings need review. No settings were changed.')
    for a,b in sorted(ranges,reverse=True):original=original[:a]+original[b:]
    block=f'{start}\n[mcp_servers.{server_name}]\ncommand = {json.dumps(entry["command"])}\nargs = {json.dumps(entry["args"])}\n{end}\n'
    candidate=original.rstrip()+'\n\n'+block
    after=tomllib.loads(candidate)
    expected=copy.deepcopy(before);expected.setdefault('mcp_servers',{})
    for name in removed:expected['mcp_servers'].pop(name)
    expected['mcp_servers'][server_name]=entry
    if after!=expected:raise Denied('Could not preserve the existing Codex settings. Nothing was changed.')
    return candidate

def install_config(agent,entry,home=None,server_name=SERVER):
    if agent not in RELATIVE_CONFIGS:raise Denied('Choose a local agent to install.')
    home=Path(home or Path.home());path=home/RELATIVE_CONFIGS[agent]
    if path.is_symlink():raise Denied('This settings file is linked elsewhere. Use the exported setup instead.')
    path.parent.mkdir(parents=True,exist_ok=True)
    # Serialize our writers and also verify that another app did not change the
    # file during preparation. Backups retain all pre-existing settings.
    lock_path=ROOT/'.private/clients/install.lock';lock_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(lock_path,'a') as lock:
        os.chmod(lock_path,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        existed=path.exists();original=path.read_text() if existed else ''
        try:candidate=codex_config(original,entry,server_name) if agent=='codex' else json_config(original,entry,server_name)
        except Denied:raise
        except (ValueError,TypeError):
            format_name='TOML' if agent=='codex' else 'JSON'
            raise Denied(f'{CLIENTS[agent]["name"]} settings contain invalid {format_name}. Airlock left the file unchanged. Repair that settings file before reconnecting.') from None
        if (path.read_text() if path.exists() else '')!=original:raise Denied('Settings changed during setup. Try again.')
        if existed:private_write(ROOT/f'.private/clients/backups/{agent}-{time.time_ns()}.txt',original)
        tmp=path.with_name(path.name+'.private-ai-'+secrets.token_hex(6))
        try:
            private_write(tmp,candidate)
            os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
    return str(path)


def connection_context(gateway):
    """Owner-only preview for the connection flow; no credentials or task data."""
    from .agent_memory import AgentMemory
    memory=AgentMemory(gateway);rows=memory.snapshot();protected=gateway.sources.protected()
    available=[dict(ref=ref,kind=r['kind'],text=suggest_redaction(r['text'],protected),
                    title=r.get('title') or r.get('origin') or r['kind'],
                    text_hash=digest(r['text']),parents=r['parents'])
               for ref,r in rows.items() if memory.allowed(ref,rows)]
    return {'records':available,'withheld':len(rows)-len(available)}


def selected_scope(gateway, selection, proposals=False):
    from .agent_memory import AgentMemory
    if not isinstance(selection,dict) or len(selection)>100 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in selection.items()) or type(proposals) is not bool:
        raise Denied('Choose up to 100 records to share.')
    memory=AgentMemory(gateway);rows=memory.snapshot()
    for ref,expected_hash in selection.items():
        if not memory.allowed(ref,rows):raise Denied('A selected record is no longer shareable. Refresh the selection.')
        if digest(rows[ref]['text'])!=expected_hash:raise Denied('A selected record changed. Refresh and review it before connecting.')
        if any(parent not in selection for parent in rows[ref]['parents']):raise Denied('Select the linked source records too, or leave out the derived note.')
    return {'records':list(selection),'disclose':bool(selection),'compute':False,'proposals':proposals}


def connection_status(gateway, identifier):
    grant=next((g for g in gateway.list_grants() if g['id']==identifier),None)
    if not grant:raise Denied('This connection no longer exists. Connect your AI again.')
    status=('revoked' if grant['revoked'] else 'expired' if grant['expires']<=gateway.clock() or grant['remaining']<=0
            else 'verified' if grant.get('last_context_read') else 'waiting')
    return {'status':status,'last_context_read':grant.get('last_context_read'),
            'shared_records':len((grant.get('scope') or {}).get('records',[]))}

def connect(gateway, *, agent, approved=False, lifetime=86400, max_calls=100, install=True, home=None, scope=None):
    if agent not in CLIENTS or approved is not True or not isinstance(install,bool):raise Denied('Choose an agent and approve its connection.')
    if agent=='dot':
        from .setup import saved_dot_available
        if not saved_dot_available(gateway):raise Denied('Set up the private Dot tunnel in Advanced setup first.')
    grant=gateway.create(agent=agent,purpose='Personalized assistance through automatic local context selection',views=[],mode='automatic',approved=True,lifetime=lifetime,max_calls=max_calls)
    token_path=ROOT/f'.private/clients/{agent}-{grant["id"]}.token'
    result={'id':grant['id'],'agent':agent,'name':CLIENTS[agent]['name'],'expires':grant['expires'],'installed':False}
    try:
        if scope is not None:
            from .agent_memory import AgentMemory
            AgentMemory(gateway).configure(grant['id'], **scope)
        if agent=='dot':
            restore_dot(gateway,grant['token'])
            result.update(installed=True,message='Connected to your existing Dot plugin. Ask Dot to use Airlock.')
        else:
            private_write(token_path,grant['token'])
            if agent=='ironclaw':
                from .ironclaw_adapter import manifest
                result.update(config=manifest(), credential_path=str(token_path),
                    message='Review the HTTPS extension template. Replace airlock.invalid with a secured MCP endpoint and configure this scoped token through IronClaw’s secret settings. Current IronClaw does not accept stdio. No endpoint was published or host connection tested.')
                with gateway.store.transaction() as data:
                    data['grants'][grant['id']]['client_setup']={'installed':False,'at':gateway.clock()}
                return result
            entry=server_entry(token_path)
            exported={'mcpServers':{SERVER:entry}}
            result['config']=json.dumps(exported,indent=2)
            result['command']=entry['command'];result['args']=entry['args']
            if install and agent in RELATIVE_CONFIGS:
                result['path']=install_config(agent,entry,home)
                result['installed']=True
                result['message']=f'Settings saved. Restart {CLIENTS[agent]["name"]} or reload its MCP connections, then enable Airlock if prompted.'
            else:
                result['message']='Copy this setup into a local MCP-compatible agent on this Mac. It contains local paths, not your private access key.'
        with gateway.store.transaction() as data:
            data['grants'][grant['id']]['client_setup']={'installed':result['installed'],'at':gateway.clock()}
        return result
    except Exception as error:
        gateway.revoke(grant['id']);token_path.unlink(missing_ok=True)
        if isinstance(error,Denied):raise
        raise Denied('Setup could not finish. The new connection was revoked. Check app permissions and try again.') from None
