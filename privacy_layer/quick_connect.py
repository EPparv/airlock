"""Owner-initiated app handoff. Discovery and calls are recorded separately by MCP."""
from concurrent.futures import Future
import fcntl
import os
import sys
import threading

from . import clients, setup
from .core import Denied
from .device_apps import NativeApps


def launch_options():
    if sys.platform != 'darwin':
        return []
    from .agent_launch import LOCAL_AGENTS
    return [*sorted(LOCAL_AGENTS), 'dot', 'mcp']


class QuickConnections:
    def __init__(self, gateway):
        self.gateway = gateway
        self.pending = {}
        self.lock = threading.Lock()

    def owner(self, action, body):
        personal = isinstance(getattr(self.gateway, 'device_apps', None), NativeApps)
        if action == 'workspace-launch-options' and not body:
            return {'agents': launch_options() if personal else []}
        explicit = action == 'workspace-open-client'
        fields = {'agent', 'approved', 'id'} if explicit else {'agent', 'approved'}
        if (not personal or action not in ('workspace-open-client', 'workspace-quick-connect', 'workspace-agent-help')
                or set(body) != fields or body['approved'] is not True
                or not isinstance(body['agent'], str) or body['agent'] not in launch_options()
                or (explicit and (not isinstance(body['id'], str) or not body['id']))):
            raise Denied('Choose an agent in your Airlock workspace on this Mac.')

        if action == 'workspace-agent-help':
            from .agent_launch import LOCAL_AGENTS, open_setup_help
            if body['agent'] not in LOCAL_AGENTS:
                raise Denied('Choose a named local agent.')
            result = open_setup_help(body['agent'])
            return {k:result[k] for k in ('opened','message')}

        # Two tabs clicking the same button while the app is starting share the outcome.
        key = (body['agent'], body.get('id'))
        with self.lock:
            if key in self.pending:
                started = False
                future = self.pending[key]
            else:
                started = True
                future = self.pending[key] = Future()
        if not started:
            return future.result()
        try:
            result = self._connect(*key)
            future.set_result(result)
            return result
        except Exception as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def _connect(self, agent, identifier):
        # Serialize grant selection and installation across owner processes sharing this
        # vault. Use a separate lock so clients can authenticate while opening.
        store = self.gateway.store.path
        path = store.with_name(f'{store.name}.{agent}.launch-lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return self._handoff(agent, identifier)
        finally:
            os.close(fd)

    def _handoff(self, agent, identifier):
        grants = self.gateway.list_grants()
        current = [g for g in grants if g['agent'] == agent and not g.get('cloud_client') and not g['revoked']
                   and g['remaining'] > 0 and g['expires'] > self.gateway.clock()]
        if identifier is not None:
            current = [g for g in current if g['id'] == identifier]
            if not current:
                raise Denied('Choose an active connection for this agent.')
        grant = current[0] if len(current) == 1 else None
        result = {'agent':agent, 'id':grant['id'] if grant else '', 'installed':False, 'needsReview':True,
                  'opened':False, 'drafted':False, 'method':'review',
                  'previousStatus':{k:grant.get(k) if grant else None
                                    for k in ('last_initialized','last_call','last_discovery','last_context_read')}}
        expected_install = agent != 'mcp'
        if current and (grant is None or grant['scope'] is None or grant['configured'] is not expected_install):
            return dict(result, message='Review the existing connection to continue.')
        if agent == 'dot' and not setup.saved_dot_available(self.gateway):
            return dict(result, method='setup', message='Connect your private Dot tunnel first.')

        home = getattr(self.gateway.sources, 'context_home', None)
        if grant is None:
            scope = {'records':[], 'disclose_records':[], 'disclose':False, 'compute':False, 'proposals':False,
                     'device_permissions':{'mail':False, 'calendar':False}}
            saved = clients.connect(self.gateway, agent=agent, approved=True, install=True, scope=scope, home=home)
            result['id'] = saved['id']
        elif agent == 'mcp':
            saved = {'installed':False}
        elif agent == 'dot':
            # The saved tunnel can point at a different grant after an older setup.
            try:
                token = setup.dot_credential_path(self.gateway).read_text().strip()
                if self.gateway.authenticate(token)['id'] != grant['id']:
                    raise Denied('Unexpected Dot connection.')
            except (OSError, Denied):
                return dict(result, message='Review the grant used by your saved Dot tunnel.')
            setup.restore_dot(self.gateway)
            saved = {'installed':True}
        else:
            # One vendor profile can point at only one named Airlock server.
            # A different grant, a reset profile or a previous release may have
            # replaced this registration since the owner last used it.
            saved = clients.manual_connection_details(self.gateway, grant['id'], reinstall=True, home=home)

        if agent == 'mcp':
            return dict(result, needsReview=False, method='manual', message='Add Airlock to the MCP settings in your app.')
        if not saved['installed']:
            return dict(result, message=saved['message'])
        result.update(installed=True, needsReview=False)
        try:
            if agent == 'dot':
                from .remote_clients import open_provider
                launch = open_provider('dot')
            else:
                from .agent_launch import open_agent
                launch = open_agent(agent)
        except (OSError, RuntimeError, ValueError, Denied):
            return dict(result, method='unavailable', message='Your access was saved. Try opening the agent again.')
        return {**result, **{k:launch[k] for k in ('opened','drafted','method','message')}}
