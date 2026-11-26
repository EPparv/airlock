"""Native local-client adapters. Each connection gets a separate scoped token.

Config exports contain local paths, never tokens or the owner credential. Only
the fixed privacy-layer server entry is installed; unrelated settings survive.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import select
import shutil
import stat
import subprocess
import time
import tomllib

from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, Ping, Pong, Request, TextMessage
from wsproto.utilities import ProtocolError

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
    'muse-code': {'name':'Muse Code', 'hint':'Meta’s local command-line agent', 'mark':'M'},
    'gemini-cli': {'name':'Gemini CLI', 'hint':'Google’s local command-line agent', 'mark':'G'},
    'vscode': {'name':'VS Code · GitHub Copilot', 'hint':'Copilot sessions running on this Mac', 'mark':'V'},
    'openclaw': {'name':'OpenClaw', 'hint':'An OpenClaw gateway running on this Mac', 'mark':'O'},
    'mcp': {'name':'Other agents', 'hint':'Standard MCP connection on this Mac', 'mark':'+'},
    'ironclaw': {'name':'IronClaw', 'hint':'HTTPS MCP extension; secure endpoint setup required', 'mark':'I'},
}
RELATIVE_CONFIGS = {
    'codex':'.codex/config.toml',
    'claude-desktop':'Library/Application Support/Claude/claude_desktop_config.json',
    'claude-code':'.claude.json',
    'cursor':'.cursor/mcp.json',
    'muse-code':'.config/muse/settings.json',
    'gemini-cli':'.gemini/settings.json',
    'vscode':'.copilot/mcp-config.json',
    'openclaw':'.openclaw/openclaw.json',
}

# Some clients read the same MCP stdio command from different configuration schemas.
PROFILES = {
    'muse-code': (('mcp_servers',), {'transport':'stdio','mode':'optional'}),
    'gemini-cli': (('mcpServers',), {}),
    'vscode': (('mcpServers',), {'type':'stdio'}),
    'openclaw': (('mcp','servers'), {'transport':'stdio'}),
}
SETUP_HINTS = {
    'codex':'Open the active Codex config.toml in Settings, add the exported TOML entry, and restart Codex.',
    'muse-code':'Merge the entry into your Muse Code user settings, then restart Muse Code and check /mcp.',
    'gemini-cli':'Merge the entry into your Gemini CLI user settings, then start a new session and check /mcp list.',
    'vscode':'Merge the entry into Copilot Global on this Mac, then start a local Copilot session in VS Code.',
    'openclaw':'On the Mac running your gateway, open OpenClaw Settings → MCP and add Airlock using the stdio command and arguments shown. Verify with openclaw mcp doctor airlock --probe.',
}


class ManualSetup(Denied):
    """The client has custom settings that should be edited in its own UI."""


def catalog(home=None):
    home=Path(home or Path.home())
    apps={'codex':('ChatGPT.app','ChatGPT 2.app','Codex.app'), 'claude-desktop':('Claude.app',), 'cursor':('Cursor.app',), 'vscode':('Visual Studio Code.app',)}
    commands = {'muse-code':'muse','gemini-cli':'gemini','openclaw':'openclaw','codex':'codex','claude-code':'claude'}
    # Apps launched from Finder do not inherit the user's interactive shell PATH.
    cli_path=os.pathsep.join([os.environ.get('PATH',os.defpath),'/opt/homebrew/bin','/usr/local/bin',
                              str(home/'.local/bin'),str(home/'.bun/bin'),str(home/'.npm-global/bin')])
    result=[]
    for agent,details in CLIENTS.items():
        installed=any((p/name).exists() for name in apps.get(agent,()) for p in (Path('/Applications'),home/'Applications'))
        if agent in commands: installed = installed or shutil.which(commands[agent],path=cli_path) is not None
        if agent=='claude-code':installed=installed or (ROOT/'.tools/node_modules/.bin/claude').exists()
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

def unique_keys(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise Denied('The settings contain duplicate keys. Choose manual setup to review them.')
        values[key] = value
    return values


def json_config(original, entry, server_name=SERVER, agent='mcp'):
    if server_name not in (SERVER,'airlock-test'):
        raise Denied('Invalid connection name.')
    path, options = PROFILES.get(agent, (('mcpServers',), {}))
    try:
        value = json.loads(original or '{}', object_pairs_hook=unique_keys)
    except json.JSONDecodeError:
        if agent in PROFILES:
            raise ManualSetup('Airlock can merge plain JSON. Use manual setup for this settings format.') from None
        raise
    if agent == 'muse-code' and isinstance(value, dict):
        if 'mcpServers' in value and 'mcp_servers' in value:
            raise ManualSetup('Muse Code settings contain both MCP server keys. Keep one in the Muse settings editor.')
        if type(value.setdefault('schema_version', 1)) is not int or value['schema_version'] != 1:
            raise ManualSetup('This Muse settings version needs manual setup.')
        if 'mcpServers' in value:
            path, options = ('mcpServers',), {'type':'stdio','required':False}
    servers = value
    for key in path:
        if not isinstance(servers, dict):
            raise Denied('The agent settings have an unexpected structure. Review them in manual setup.')
        if agent == 'openclaw' and '$include' in servers:
            raise ManualSetup('These OpenClaw settings use an included file. Use OpenClaw’s settings editor.')
        servers = servers.setdefault(key, {})
    if not isinstance(servers, dict):
        raise Denied('The server list has an unexpected structure. Review it in manual setup.')
    if agent == 'openclaw' and '$include' in servers:
        raise ManualSetup('These OpenClaw settings use an included file. Use OpenClaw’s settings editor.')

    if server_name in servers:
        previous = servers[server_name]
        matches_options = isinstance(previous, dict) and all(previous.get(k) == v for k,v in options.items())
        previous_bridge = {k:v for k,v in previous.items() if k not in options} if matches_options else None
        if not owned(previous_bridge):
            raise Denied('An unrelated connection already uses this name. Its settings were left unchanged.')
    if server_name == SERVER and LEGACY_SERVER in servers and owned(servers[LEGACY_SERVER]):
        servers.pop(LEGACY_SERVER)
    servers[server_name] = {**options, **entry}
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
            if left not in original and right not in original:
                # Codex and its settings editor can rewrite TOML without our markers.
                # Only remove a complete table that parses to the already verified entry.
                header=re.search(r'^\[mcp_servers\.'+re.escape(name)+r'\][ \t]*(?:#[^\n]*)?$', original, re.MULTILINE)
                if not header:
                    raise ManualSetup('The existing Codex entry uses custom TOML. Review it in Codex settings.')
                a=header.start();b=header.end()
                for line in original[b:].splitlines(keepends=True):
                    b+=len(line)
                    try: table=tomllib.loads(original[a:b])
                    except tomllib.TOMLDecodeError: continue
                    if table=={'mcp_servers':{name:servers[name]}}: break
                else: raise ManualSetup('The existing Codex entry uses custom TOML. Review it in Codex settings.')
            elif original.count(left)==1 and original.count(right)==1:
                a=original.index(left);b=original.index(right)+len(right)
            else:
                raise Denied('The existing managed connection needs review. No settings were changed.')
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

def config_path(agent, home=None):
    """Use the same active user profile as the client without writing outside its home."""
    if agent not in RELATIVE_CONFIGS:raise Denied('Choose a local agent to install.')
    home=Path(home or Path.home());path=home/RELATIVE_CONFIGS[agent]
    if agent=='codex' and os.environ.get('CODEX_HOME'):
        profile=Path(os.environ['CODEX_HOME']).expanduser()
        # A disposable profile must never write settings in the actual user's home.
        if home.resolve()==Path.home().resolve() or (profile.is_absolute() and profile.is_relative_to(home)):
            if not profile.is_absolute() or not profile.resolve().is_relative_to(home.resolve()):
                raise ManualSetup('The active Codex profile is outside this home folder. Add Airlock in that profile.')
            path=profile/'config.toml'
    profiles = {
        'vscode': ('COPILOT_HOME', 'mcp-config.json'),
        'muse-code': ('XDG_CONFIG_HOME', 'muse/settings.json'),
        'openclaw': ('OPENCLAW_STATE_DIR', 'openclaw.json'),
    }
    env_name, filename = profiles.get(agent, ('', ''))
    if agent == 'openclaw' and os.environ.get('OPENCLAW_CONFIG_PATH'):
        env_name, filename = 'OPENCLAW_CONFIG_PATH', ''
    elif agent == 'openclaw' and os.environ.get('OPENCLAW_PROFILE'):
        raise ManualSetup('A named OpenClaw profile is active. Add Airlock in that profile’s settings.')
    if env_name and os.environ.get(env_name):
        selected = Path(os.environ[env_name]).expanduser()
        if not selected.is_absolute() or not selected.resolve().is_relative_to(home.resolve()):
            raise ManualSetup('A custom client profile is outside this home folder. Add Airlock in that profile.')
        path = selected / filename if filename else selected
    if path.is_symlink() or not path.resolve().is_relative_to(home.resolve()):
        raise ManualSetup('These settings are linked elsewhere. Use the exported setup.')
    return path


def install_config(agent,entry,home=None,server_name=SERVER):
    path = config_path(agent, home)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Serialize our writers and also verify that another app did not change the
    # file during preparation. Backups retain all pre-existing settings.
    lock_path=ROOT/'.private/clients/install.lock';lock_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(lock_path,'a') as lock:
        os.chmod(lock_path,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        existed=path.exists();original=path.read_text() if existed else ''
        try:candidate=codex_config(original,entry,server_name) if agent=='codex' else json_config(original,entry,server_name,agent)
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
                    text_hash=digest(r['text']),parents=r['parents'],
                    sensitive=memory.requires_compute(ref,rows),access='private task only' if memory.requires_compute(ref,rows) else 'filtered excerpts')
               for ref,r in rows.items() if memory.allowed(ref,rows)]
    return {'records':available,'withheld':len(rows)-len(available)}


def selected_scope(gateway, selection, proposals=False):
    from .agent_memory import AgentMemory
    if not isinstance(selection,dict) or len(selection)>100 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in selection.items()) or type(proposals) is not bool:
        raise Denied('Choose up to 100 records to share.')
    memory=AgentMemory(gateway);rows=memory.snapshot() if selection else {}
    for ref,expected_hash in selection.items():
        if not memory.allowed(ref,rows):raise Denied('A selected record is no longer shareable. Refresh the selection.')
        if digest(rows[ref]['text'])!=expected_hash:raise Denied('A selected record changed. Refresh and review it before connecting.')
        if any(parent not in selection for parent in rows[ref]['parents']):raise Denied('Select the linked source records too, or leave out the derived note.')
    excerpts = [ref for ref in selection if not memory.requires_compute(ref,rows)]
    return {'records':list(selection),'disclose':bool(excerpts),'disclose_records':excerpts,
            'compute':len(excerpts)<len(selection),'proposals':proposals}


def connection_status(gateway, identifier):
    grant=next((g for g in gateway.list_grants() if g['id']==identifier),None)
    if not grant:raise Denied('This connection no longer exists. Connect your AI again.')
    status=('revoked' if grant['revoked'] else 'expired' if grant['expires']<=gateway.clock() or grant['remaining']<=0
            else 'verified' if grant.get('last_context_read') else 'waiting')
    return {'status':status,'last_call':grant['last_call'],'last_discovery':grant['last_discovery'],'last_context_read':grant.get('last_context_read'),
            'shared_records':len((grant.get('scope') or {}).get('records',[]))}


class _CodexSocketRPC:
    """Codex's Unix proxy relays a WebSocket byte stream over its standard pipes."""
    def __init__(self, proxy, timeout=1.5, max_bytes=65536):
        self.proxy = proxy
        self.deadline = time.monotonic() + timeout
        self.max_bytes = max_bytes
        self.ws = WSConnection(ConnectionType.CLIENT)
        self._write(Request(host='localhost', target='/'))
        self.events = self._read()
        if not isinstance(next(self.events), AcceptConnection):
            raise ValueError('Codex declined the WebSocket upgrade.')

    def _write(self, event):
        self.proxy.stdin.write(self.ws.send(event))
        self.proxy.stdin.flush()

    def _read(self):
        received = 0
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.proxy.stdout], [], [], remaining)[0]:
                raise TimeoutError('Codex control socket timed out.')
            data = os.read(self.proxy.stdout.fileno(), 8192)
            received += len(data)
            if not data or received > self.max_bytes:
                raise ValueError('Codex control stream ended or exceeded its response limit.')
            self.ws.receive_data(data)
            for event in self.ws.events():
                if isinstance(event, Ping):
                    self._write(event.response())
                elif not isinstance(event, Pong):
                    yield event

    def send(self, message):
        self._write(TextMessage(data=json.dumps(message)))

    def call(self, number, method, params):
        self.send({'id':number, 'method':method, 'params':params})
        fragments = []
        for event in self.events:
            if not isinstance(event, TextMessage):
                raise ValueError('Unexpected Codex control frame.')
            fragments.append(event.data)
            if event.message_finished:
                reply = json.loads(''.join(fragments))
                fragments.clear()
                if not isinstance(reply, dict):
                    raise ValueError('Unexpected Codex control message.')
                if reply.get('id') == number:
                    return reply


def _refresh_codex_proxy(command):
    """Reload only a running service. Discard the relay after its acknowledgment."""
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proxy:
        try:
            rpc = _CodexSocketRPC(proxy)
            init = rpc.call(1, 'initialize', {'clientInfo':{'name':'airlock','version':'1'}})
            if 'result' not in init or 'error' in init:
                return False
            rpc.send({'method':'initialized'})
            reply = rpc.call(2, 'config/mcpServer/reload', {})
            return 'result' in reply and 'error' not in reply
        except (OSError, ValueError, ProtocolError):
            return False
        finally:
            if proxy.poll() is None:
                proxy.kill()


def codex_bundle_binary(bundle):
    """Find the vendor runtime in a Codex desktop bundle, including the renamed ChatGPT.app."""
    try:
        root = Path(bundle).resolve(strict=True)
        with (root/'Contents/Info.plist').open('rb') as info:
            if plistlib.load(info).get('CFBundleIdentifier') != 'com.openai.codex':
                return None
        for relative in ('codex-cli/CodexCLI.app/Contents/MacOS/codex', 'codex', 'codex-cli/bin/codex'):
            candidate = (root/'Contents/Resources'/relative).resolve()
            if candidate.is_relative_to(root) and candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    except (OSError, ValueError, RuntimeError, plistlib.InvalidFileException, AttributeError):
        pass
    return None


def _codex_socket(advertised):
    """Match the vendor's protected local endpoint for this exact Codex profile."""
    uid = os.geteuid()
    parent = advertised.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid or parent.st_mode & 0o022:
        return None
    alias = advertised.lstat()
    if not stat.S_ISLNK(alias.st_mode) or alias.st_uid != uid:
        return None
    directory = Path('/tmp').resolve()/f'codex-daemon-{uid}'
    digest = hashlib.sha256(os.fsencode(advertised.parent.resolve()/advertised.name)).hexdigest()
    physical = directory/digest
    if advertised.readlink() != physical:
        return None
    protected, endpoint = directory.lstat(), physical.lstat()
    if (not stat.S_ISDIR(protected.st_mode) or stat.S_IMODE(protected.st_mode) != 0o700 or protected.st_uid != uid
            or not stat.S_ISSOCK(endpoint.st_mode) or stat.S_IMODE(endpoint.st_mode) != 0o600 or endpoint.st_uid != uid):
        return None
    return physical


def refresh_codex(config, home):
    """Never start or restart a host, or select a socket from another profile."""
    profile = Path(config).parent
    try:
        sock = _codex_socket(profile/'app-server-control/app-server-control.sock')
        if sock is None:
            return False
        bundles = (apps/name for apps in (Path('/Applications'),Path(home or Path.home())/'Applications')
                   for name in ('ChatGPT.app','ChatGPT 2.app','Codex.app'))
        binary = next(filter(None, map(codex_bundle_binary, bundles)), None)
        if binary is None:
            candidates = (Path('/opt/homebrew/bin/codex'), Path('/usr/local/bin/codex'))
            binary = next((p for p in candidates if p.is_file() and os.access(p,os.X_OK)), None)
        return bool(binary and _refresh_codex_proxy([str(binary),'app-server','proxy','--sock',str(sock)]))
    except (OSError, ValueError):
        return False


def finish_client_install(result, home):
    agent = result['agent']
    result['installed'] = True
    if agent == 'codex':
        result['reload_requested'] = refresh_codex(result['path'], home)
        if result['reload_requested']:
            result['message'] = 'Settings saved. Your running Codex service accepted a request to reload Airlock.'
            return
    result['message'] = f'Settings saved. Open {CLIENTS[agent]["name"]} and enable Airlock if prompted.'


def manual_connection_details(gateway, identifier, *, reinstall=False, home=None):
    """Export or reinstall the same active local credential without renewing its grant."""
    grant = next((g for g in gateway.list_grants() if g['id'] == identifier), None)
    if (not grant or grant['agent'] not in (*RELATIVE_CONFIGS, 'mcp') or grant['configured'] is None
            or grant['revoked'] or grant['expires'] <= gateway.clock() or grant['remaining'] <= 0):
        raise Denied('Manual setup is unavailable for this connection.')
    agent = grant['agent']
    if reinstall and agent not in RELATIVE_CONFIGS:
        raise Denied('Add this connection in your MCP client using its settings.')
    if not reinstall and grant['configured'] is not False:
        raise Denied('Manual setup is unavailable for this connection.')
    path = ROOT / '.private' / 'clients' / f'{agent}-{identifier}.token'
    if not path.is_file() or path.is_symlink():
        raise Denied('The local credential is missing. Revoke this connection and connect again.')
    if gateway.authenticate(path.read_text().strip())['id'] != identifier:
        raise Denied('The local credential no longer matches. Revoke this connection and connect again.')
    entry = server_entry(path)
    config = codex_config('', entry).lstrip() if agent == 'codex' else json_config('', entry, agent=agent)
    result = {'id':identifier, 'agent':agent, 'installed':False, 'config':config,
              'message':SETUP_HINTS.get(agent, 'Add this entry to your agent’s local MCP settings.')}
    if reinstall:
        try:
            result['path'] = install_config(agent, entry, home)
        except ManualSetup as error:
            result['message'] = f'{error} {result["message"]}'
        else:
            finish_client_install(result, home)
        with gateway.store.transaction() as data:
            data['grants'][identifier]['client_setup'] = {'installed':result['installed'], 'at':gateway.clock()}
    return result

def connect(gateway, *, agent, approved=False, lifetime=86400, max_calls=100, install=True, home=None, scope=None):
    if agent not in CLIENTS or approved is not True or not isinstance(install,bool):raise Denied('Choose an agent and approve its connection.')
    if agent=='dot':
        from .setup import saved_dot_available
        if not saved_dot_available(gateway):raise Denied('Set up the private Dot tunnel in Advanced setup first.')
    if agent in PROFILES and scope is None:
        scope = {'records':[], 'disclose':False, 'compute':False, 'proposals':False}
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
            result['config'] = json_config('',entry,agent=agent)
            if agent == 'codex':
                result['client_config'] = codex_config('',entry).lstrip()
            result['command']=entry['command'];result['args']=entry['args']
            result['message'] = SETUP_HINTS.get(agent,'Merge this entry into your local MCP client settings on this Mac.')
            if install and agent in RELATIVE_CONFIGS:
                try:
                    result['path'] = install_config(agent,entry,home)
                except ManualSetup as error:
                    if agent not in PROFILES and agent!='codex':
                        raise
                    result['message'] = f'{error} {SETUP_HINTS[agent]}'
                else:
                    if agent == 'muse-code':
                        installed = json.loads(Path(result['path']).read_text())
                        # Export only generated values, even if a client edits its file after install.
                        if 'mcpServers' in installed:
                            result['config'] = json_config('{"mcpServers":{}}',entry,agent=agent)
                    finish_client_install(result, home)
        with gateway.store.transaction() as data:
            data['grants'][grant['id']]['client_setup']={'installed':result['installed'],'at':gateway.clock()}
        return result
    except Exception as error:
        gateway.revoke(grant['id']);token_path.unlink(missing_ok=True)
        if isinstance(error,Denied):raise
        raise Denied('Setup could not finish. The new connection was revoked. Check app permissions and try again.') from None
