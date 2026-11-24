"""A local action belongs to its owner. Agents receive only a scoped handle and a receipt."""
import base64
import copy
from datetime import datetime, timezone
from email.utils import getaddresses
import hashlib
import hmac
from pathlib import Path
import re
import secrets

from .agent_memory import AgentMemory
from .clients import RELATIVE_CONFIGS, connect, connection_context, selected_scope
from .context import ContextHub
from .core import Denied, digest, EMAIL
from .data_view import api_settings, fetch_api, field_names, inspect_file, project, screened_view, select_fields
from .device_apps import ExampleApps
from .privacy_engine import PrivacyEngine

TOOLS = {'list_private_actions': set(), 'request_private_action': {'reference'},
         'private_action_status': {'reference'}, 'read_private_fields': {'reference'},
         'prepare_private_followup': {'source','subject','body','request_key'}}
MAX_ATTACHMENT = 4 * 1024 * 1024
LABELS = {'email': 'Send email', 'event': 'Create calendar event', 'data': 'Read selected fields', 'api': 'Read API fields'}


def short(value, maximum, title):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise Denied('Check ' + title + '.')
    return value.strip()


def addresses(value):
    if not isinstance(value, str) or len(value) > 2000 or any(c in value for c in '\r\n'):
        raise Denied('Check the recipient addresses.')
    result = list(dict.fromkeys(address for _, address in getaddresses([value]) if address))
    if not 1 <= len(result) <= 20 or any(not EMAIL.fullmatch(address) for address in result):
        raise Denied('Enter one to twenty valid email addresses.')
    return result


def email_payload(values):
    if not isinstance(values, dict) or set(values) - {'recipients', 'subject', 'body', 'attachment'}:
        raise Denied('Invalid email details.')
    payload = dict(recipients=addresses(values.get('recipients')), subject=short(values.get('subject'), 240, 'the subject'),
                   body=short(values.get('body'), 16000, 'the message'))
    if any(c in payload['subject'] for c in '\r\n'):
        raise Denied('Use one line for the subject.')
    attachment = values.get('attachment')
    if attachment:
        if not isinstance(attachment, dict) or set(attachment) != {'name', 'data'}:
            raise Denied('Choose a file for the attachment.')
        name = short(attachment['name'], 150, 'the attachment name')
        if name in ('.', '..') or Path(name).name != name or any(ord(c) < 32 or c in '/\\:' for c in name):
            raise Denied('Choose a file with a plain filename.')
        encoded = attachment['data']
        if not isinstance(encoded, str) or len(encoded) > (MAX_ATTACHMENT + 2) // 3 * 4:
            raise Denied('Choose an attachment up to 4 MB.')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise Denied('The attachment could not be read.') from None
        if not raw or len(raw) > MAX_ATTACHMENT:
            raise Denied('Choose a nonempty attachment up to 4 MB.')
        payload['attachment'] = dict(name=name, data=encoded, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return payload


def event_payload(values):
    if not isinstance(values, dict) or set(values) != {'title', 'start', 'end', 'calendar'}:
        raise Denied('Check the calendar event.')
    result = {k: short(values[k], 240, k) for k in values}
    try:
        times = [datetime.fromisoformat(result[k]) for k in ('start', 'end')]
        if any(t.tzinfo is None for t in times) or times[1] <= times[0]:
            raise ValueError()
        result.update(start=times[0].astimezone(timezone.utc).isoformat(), end=times[1].astimezone(timezone.utc).isoformat())
    except ValueError:
        raise Denied('Choose an end time after the start time.') from None
    return result


def data_payload(values):
    if not isinstance(values, dict) or set(values) != {'name', 'data', 'table', 'fields'}:
        raise Denied('Choose a file and its visible fields.')
    _, fields, rows, truncated = inspect_file(values['name'], values['data'], values['table'])
    selected = select_fields(fields, values['fields'])
    return {'name': short(values['name'], 180, 'the filename'), 'fields': selected, 'rows': project(rows,selected), 'truncated': truncated}


def api_payload(values):
    if not isinstance(values, dict) or set(values) != {'url', 'credential', 'array_key', 'fields'}:
        raise Denied('Choose an API endpoint and visible fields.')
    settings = api_settings(values['url'], values['credential'], values['array_key'])
    rows, _ = fetch_api(settings)
    selected = select_fields(field_names(rows), values['fields'])
    project(rows, selected)
    return {**settings,'fields':selected}


class Workspace:
    def __init__(self, gateway):
        self.g = gateway
        self.apps = getattr(gateway, 'device_apps', None)
        if self.apps is None:
            raise Denied('Device actions are unavailable in this workspace.')
        self.example = isinstance(self.apps, ExampleApps)

    def alias(self, key, grant):
        return 'act_' + hmac.digest(self.g.store.key, f'action:{grant}:{key}'.encode(), 'sha256').hex()[:28]

    def active(self, data, grant):
        item = data['grants'].get(grant, {})
        return bool(item and not item.get('revoked') and item.get('scope') is not None and item['expires'] > self.g.clock())

    def owner_row(self, item):
        payload = dict(item['payload'])
        if 'attachment' in payload:
            payload['attachment'] = {k:v for k,v in payload['attachment'].items() if k != 'data'}
        payload.pop('credential', None)
        if 'rows' in payload:
            payload['count'] = len(payload.pop('rows'))
        return {**item, 'payload': payload, 'handles':{gid:self.alias(item['id'], gid) for gid in item['audience']}}

    def create(self, kind, label, audience, values, *, source=None, grant=None, operation_id=None, intent=None):
        if kind not in LABELS or not isinstance(audience, list) or not 1 <= len(audience) <= 12 or any(not isinstance(x,str) for x in audience):
            raise Denied('Choose an action and at least one connected agent.')
        label = short(label, 80, 'the label visible to the agent')
        if self.example and kind == 'api':
            raise Denied('Live API access requires a personal workspace.')
        payload = {'email': email_payload, 'event': event_payload, 'data': data_payload, 'api': api_payload}[kind](values)
        item = dict(id=operation_id or secrets.token_hex(16), kind=kind, label=label, audience=sorted(set(audience)),
                    payload=payload, state='ready', created=self.g.clock(), applicant='', asked=0, completed=0)
        if grant:
            item.update(source=source, applicant=grant['id'], asked=self.g.clock(), state='pending', intent=intent, policy_at_request=grant.get('policy_revision',0))
        item['fingerprint'] = digest([item['id'], kind, label, item['audience'], payload])
        with self.g.store.transaction() as d:
            if not all(self.active(d, identifier) for identifier in audience):
                raise Denied('Choose active agents with scoped access.')
            items = d.setdefault('device_actions', {})
            if grant:
                current = d['grants'][grant['id']]
                if not current.get('device_permissions', {}).get(source) or current.get('policy_revision',0) != grant.get('policy_revision',0):
                    raise Denied('Access changed. Ask the owner to review this connection.')
                if item['id'] in d.get('withdrawn_followups', {}):
                    raise Denied('This request was removed by its owner.')
                if item['id'] in items:
                    if items[item['id']].get('intent') != intent:
                        raise Denied('Use a new request key for a different message.')
                    return {'id': item['id']}
            if len(items) >= 200 or sum(len(str(i['payload'])) for i in items.values()) + len(str(payload)) > 32 * 1024 * 1024:
                raise Denied('Remove an old action to make room.')
            items[item['id']] = item
        return {'id': item['id']}

    def visible(self, item, grant):
        result = dict(reference=self.alias(item['id'], grant['id']), kind=item['kind'], label=item['label'], status=item['state'])
        if item['state'] in ('sent','created') and self.example:
            result['simulated'] = True
        return result

    def followup(self, grant, source, subject, body, request_key):
        if source not in ('mail','calendar') or not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_key):
            raise Denied('Choose a permitted source and a stable request key of 8 to 80 letters, digits, hyphens or underscores.')
        subject = short(subject,240,'the subject')
        body = short(body,16000,'the message')
        key = hmac.digest(self.g.store.key, ('followup:'+grant['id']+':'+request_key).encode(),'sha256').hex()[:32]
        intent = digest([source, subject, body])
        with self.g.store.transaction() as d:
            current = d['grants'].get(grant['id'], {})
            if not self.active(d,grant['id']) or not current.get('device_permissions',{}).get(source):
                raise Denied('The owner must enable this follow-up source for this agent.')
            if key in d.get('withdrawn_followups', {}):
                raise Denied('This request was removed by its owner.')
            prior = d.get('device_actions',{}).get(key)
            if prior:
                if prior.get('intent') != intent:
                    raise Denied('Use a new request key for a different message.')
                return self.visible(prior,grant)
            if sum(i.get('applicant') == grant['id'] and i['state']=='pending' for i in d.get('device_actions',{}).values()) >= 10:
                raise Denied('Review the queued requests before adding another.')
        options = self.apps.sources(source)
        if not options:
            raise Denied('No eligible selection. Select a message in Mail or choose a recent meeting with attendees.')
        # Only the local connector resolves an address. The cloud client supplies prose and a source type.
        first = options[0]
        recipients = first['recipient'] if source=='mail' else ', '.join(first['recipients'])
        self.create('email', 'Email follow-up', [grant['id']], dict(recipients=recipients, subject=subject, body=body),
                    source=source, grant=grant, operation_id=key, intent=intent)
        with self.g.store.transaction() as d:
            return self.visible(d['device_actions'][key],grant)

    def configure(self, agent, identifier, selection, proposals, mail, calendar):
        if self.example or agent not in RELATIVE_CONFIGS or type(mail) is not bool or type(calendar) is not bool or not isinstance(identifier,str):
            raise Denied('Choose a supported agent and its permissions.')
        scope = selected_scope(self.g, selection, proposals)
        result = {'message':'Access saved.'}
        if identifier:
            existing = AgentMemory(self.g).grant(identifier)
            if existing.get('agent') != agent or existing.get('scope') is None:
                raise Denied('Choose an active scoped connection.')
            AgentMemory(self.g).configure(identifier, **scope)
        else:
            result = connect(self.g, agent=agent, approved=True, install=True, scope=scope, home=getattr(self.g.sources,'context_home',None))
            identifier = result['id']
        with self.g.store.transaction() as d:
            if not self.active(d,identifier):
                raise Denied('Connection is no longer active.')
            g=d['grants'][identifier]
            g['device_permissions']={'mail':mail,'calendar':calendar}
            g['policy_revision']=g.get('policy_revision',0)+1
            self.g.audit(d,g,'device_permissions','updated')
        return result

    def call(self, grant, tool, args):
        if tool == 'prepare_private_followup':
            return self.followup(grant, **args)
        with self.g.store.transaction() as d:
            if not self.active(d, grant['id']):
                raise Denied('An active scoped connection is required.')
            allowed = [i for i in d.get('device_actions', {}).values() if grant['id'] in i['audience']]
            if tool == 'list_private_actions':
                return {'actions':[self.visible(i, grant) for i in allowed if i['state'] != 'withdrawn']}
            ref = args['reference']
            if not isinstance(ref,str) or not re.fullmatch(r'act_[a-f0-9]{28}', ref):
                raise Denied('This action is unavailable.')
            item = next((i for i in allowed if hmac.compare_digest(self.alias(i['id'], grant['id']), ref)), None)
            if not item or item['state'] == 'withdrawn':
                raise Denied('This action is unavailable.')
            if tool == 'private_action_status':
                return self.visible(item, grant)
            if tool == 'request_private_action':
                if item['kind'] in ('api','data'):
                    raise Denied('Use read_private_fields for this view.')
                if item['state'] == 'ready':
                    item.update(state='pending', applicant=grant['id'], asked=self.g.clock(), policy_at_request=grant.get('policy_revision',0))
                return self.visible(item, grant)
            if item['kind'] not in ('api','data') or item['state'] != 'ready':
                raise Denied('This connection has no such data view.')
            data = copy.deepcopy(item['payload'])
        if item['kind'] == 'api':
            rows, truncated = fetch_api(data)
            return screened_view(PrivacyEngine(self.g,grant),data['fields'],project(rows,data['fields']),truncated)
        return screened_view(PrivacyEngine(self.g,grant),data['fields'],data['rows'],data['truncated'])

    def decide(self, identifier, fingerprint, approve):
        if type(approve) is not bool:
            raise Denied('Choose an approval decision.')
        with self.g.store.transaction() as d:
            item = d.get('device_actions', {}).get(identifier)
            if not item or item['fingerprint'] != fingerprint or item['state'] != 'pending':
                raise Denied('This request changed or was already handled. Refresh the workspace.')
            if not approve:
                item['state'] = 'declined'
                return {'status':'declined'}
            current = d['grants'].get(item['applicant'], {})
            if (not self.active(d, item['applicant']) or current.get('policy_revision',0) != item.get('policy_at_request')
                    or (item.get('source') and not current.get('device_permissions',{}).get(item['source']))
                    or self.g.clock() - item['asked'] >= 3600):
                raise Denied('This request expired or the agent lost access. Withdraw it and prepare a new action.')
            # Commit before touching the OS. A repeated approval or process restart must never resend.
            item['state'] = 'submitting'
            payload = copy.deepcopy(item['payload'])
            kind = item['kind']
        attachment = payload.pop('attachment', None)
        if attachment:
            attachment = dict(name=attachment['name'], bytes=base64.b64decode(attachment['data'], validate=True))
        try:
            if self.apps.perform(kind, payload, attachment) is not True:
                raise RuntimeError()
            status = 'sent' if kind == 'email' else 'created'
        except Exception:
            status = 'unconfirmed'
        with self.g.store.transaction() as d:
            item = d['device_actions'][identifier]
            item.update(state=status, completed=self.g.clock())
            self.g.audit(d, d['grants'][item['applicant']], 'device_'+kind, status)
        return {'status':status}

    def remove(self, identifier):
        with self.g.store.transaction() as d:
            item = d.get('device_actions', {}).get(identifier)
            if not item or item['state'] == 'submitting':
                raise Denied('This action is unavailable or being submitted.')
            if item.get('intent'):
                # Keep only request identifiers until the grant expires, to prevent duplicate sends after removal.
                previous = d.get('withdrawn_followups', {})
                d['withdrawn_followups'] = {k:g for k,g in previous.items() if self.active(d,g)}
                if self.active(d,item['applicant']):
                    d['withdrawn_followups'][identifier] = item['applicant']
            del d['device_actions'][identifier]
            for grant in item['audience']:
                g = d['grants'].get(grant)
                if g:
                    g['policy_revision'] = g.get('policy_revision', 0) + 1
        return {'removed':True}

    def state(self):
        memory = AgentMemory(self.g)
        with self.g.store.transaction() as d:
            actions = [self.owner_row(i) for i in d.get('device_actions', {}).values()]
            receipts = copy.deepcopy(d.get('disclosures', [])[-30:])
            demo = d.get('workspace_examples', {})
            examples = {g['id']:name for name, g in demo.items()}
            device = {g['id']:g.get('device_permissions',{}) for g in d['grants'].values()}
        grants = self.g.list_grants()
        if self.example:
            grants = [g for g in grants if g['id'] in examples]
        else:
            grants = [g for g in grants if g['agent'] != 'test']
        memory_state = memory.state()
        return {'example':self.example, 'actions':actions[::-1], 'receipts':receipts[::-1],
                'agents':[{'id':g['id'],'name':g['agent'],'scope':g['scope'], 'remaining':g['remaining'], 'device':device[g['id']], 'proposals':bool(g['capabilities'].get('context_updates')),
                           'status':'revoked' if g['revoked'] else 'expired' if g['expires']<=self.g.clock() or not g['remaining'] else 'used' if g['last_context_read'] else 'configured'}
                          for g in grants],
                'records':memory_state['records'], 'proposals':[p for p in memory_state['proposals'] if p['status']=='pending']}

    def seed(self):
        if not self.example:
            raise Denied('The example uses an isolated workspace.')
        with self.g.store.transaction() as d:
            if 'workspace_examples' in d:
                return
        examples = {}
        for name in ('claude-desktop','codex'):
            result = self.g.create(agent=name, purpose='Fictional workspace example', views=[], approved=True, mode='automatic', lifetime=30*86400, max_calls=1000)
            records = connection_context(self.g)['records']
            scope = selected_scope(self.g, {r['ref']:r['text_hash'] for r in records})
            AgentMemory(self.g).configure(result['id'], **scope)
            examples[name] = result
        with self.g.store.transaction() as d:
            d['workspace_examples'] = examples
        data = b'account,stage,internal_note\nclient@example.com,Pilot,restricted commercial terms'
        self.create('data', 'Pipeline stage', [examples['codex']['id']], {'name':'pipeline.csv', 'data':base64.b64encode(data).decode(),
                    'table':'', 'fields':['account','stage']})
        result = self.create('email', 'Investor follow-up', [x['id'] for x in examples.values()],
                             {'recipients':'mara@example.com, jon@example.com', 'subject':'Cypress follow-up',
                              'body':'Hi Mara and Jon,\n\nThanks for the conversation yesterday. I enjoyed hearing what you look for in an early pilot. Can we find a time next week to compare notes?\n\nAlex'})
        self.try_example(result['id'], examples['claude-desktop']['id'], 'request_private_action')

    def try_example(self, identifier, agent, tool):
        if not self.example or tool not in ('list_private_actions','request_private_action','private_action_status','read_private_fields'):
            raise Denied('Only example connections can be simulated.')
        with self.g.store.transaction() as d:
            grant = next((v for v in d.get('workspace_examples', {}).values() if v['id'] == agent), None)
        if not grant:
            raise Denied('Choose an example agent.')
        args = {} if tool == 'list_private_actions' else {'reference':self.alias(identifier, agent)}
        return self.g.call(grant['token'], tool, args)

    def owner(self, action, body):
        if action == 'workspace-state' and not body:
            return self.state()
        if action == 'workspace-connect':
            return self.configure(**body)
        if action == 'workspace-create' and set(body)=={'kind','label','audience','values'}:
            return self.create(**body)
        if action == 'workspace-decide':
            return self.decide(**body)
        if action == 'workspace-remove':
            return self.remove(**body)
        if action == 'workspace-sources' and set(body) == {'source'}:
            return {'items':self.apps.sources(body['source'])}
        if action == 'workspace-api-fields' and not self.example and set(body) == {'url','credential','array_key'}:
            rows, truncated = fetch_api(api_settings(**body))
            return {'fields':field_names(rows),'count':len(rows),'truncated':truncated}
        if action == 'workspace-fields' and set(body) == {'name','data','table'}:
            tables, fields, rows, truncated = inspect_file(body['name'], body['data'], body['table'])
            return {'tables':tables,'fields':fields,'count':len(rows),'truncated':truncated}
        if action == 'workspace-try':
            return self.try_example(**body)
        if action == 'workspace-note' and set(body) == {'kind','text','private'}:
            import json
            if body['kind'] not in ('memories','skills') or type(body['private']) is not bool:
                raise Denied('Choose a memory or skill.')
            value = short(body['text'], 12000, 'the record')
            hub = ContextHub(self.g.store, home=getattr(self.g.sources, 'context_home', None), clock=self.g.clock)
            draft = hub.preview('Workspace.json', json.dumps({body['kind']:[{'text':value,'device_only':body['private']}]}).encode())
            return hub.commit(draft['id'], list(range(len(draft['items']))), self.g.sources.library())
        raise Denied('Unknown workspace action.')
