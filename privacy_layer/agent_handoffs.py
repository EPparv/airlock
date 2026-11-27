"""Owner-assigned work and separately approved disclosures between scoped connections."""
import hmac
import re
import secrets

from .core import Denied, canonical
from .privacy_engine import PrivacyEngine


TOOLS = {
    'list_agent_handoffs': set(),
    'claim_agent_handoff': {'reference'},
    'submit_agent_handoff': {'reference', 'result', 'memory_proposal_id'},
    'read_agent_handoff': {'reference'},
}
# Per-connection handles, including generated identity aliases, must not become
# correlators between clients when an agent includes one in its report.
HANDLE = re.compile(r'\b(?:act|record|handoff|proposal|task|pal)_[A-Za-z0-9_-]{8,}\b|\[[a-z]+-[a-p]{20}\]', re.I)


def bounded(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 5000:
        raise Denied('Enter between 1 and 5,000 characters.')
    return value.strip()


class Handoffs:
    def __init__(self, gateway):
        self.g = gateway

    def eligible(self, grant):
        return bool(grant and grant.get('scope') is not None and not grant.get('revoked')
                    and grant['expires'] > self.g.clock())

    def live(self, data, job):
        return all(self.eligible(data['grants'].get(key)) and
                   data['grants'][key].get('policy_revision', 0) == rev
                   for key, rev in job['policies'].items())

    def reference(self, job, grant_id):
        mac = hmac.digest(self.g.store.key, canonical(['handoff-v1', job['id'], grant_id]), 'sha256')
        return 'handoff_' + mac.hex()[:28]

    def screen(self, grant, value):
        value = bounded(value)
        # Handoffs get fresh text, never a reusable identity or source reference.
        text = HANDLE.sub('[reference withheld]', value)
        report = PrivacyEngine(self.g, grant).screen(text)
        report['text'] = HANDLE.sub('[reference withheld]', report['text'])
        report['changed'] = report['text'] != value
        return report

    def exact(self, grant, text):
        review = self.screen(grant, text)
        if review['blocked'] or review['changed']:
            raise Denied('Review the filtered text before sharing.')
        return review['text']

    def peers(self, data, worker, recipient):
        if not isinstance(worker, str) or not isinstance(recipient, str) or worker == recipient:
            raise Denied('Choose two different active connections.')
        grants = [data['grants'].get(k) for k in (worker, recipient)]
        if not all(self.eligible(g) and g['remaining'] > 0 for g in grants):
            raise Denied('Choose two active scoped connections with calls available.')
        return grants

    def summary(self, data, job):
        proposal = data.get('memory_proposals', {}).get(job.get('proposal_id'))
        worker = data['grants'].get(job['worker'], {})
        recipient = data['grants'].get(job['recipient'], {})
        return {**{k: job.get(k, '') for k in ('id', 'status', 'revision', 'worker', 'recipient',
                                                'instruction', 'report', 'released', 'created')},
                'available': self.live(data, job),
                'worker_name': worker.get('display_name') or worker.get('agent', 'Agent'),
                'recipient_name': recipient.get('display_name') or recipient.get('agent', 'Agent'),
                'proposal': {k:proposal[k] for k in ('id','status','text')} if proposal else None}

    def active_job(self, data, body, required=None):
        identifier = body.get('id')
        job = data.get('handoffs', {}).get(identifier) if isinstance(identifier, str) else None
        if not job or type(body.get('revision')) is not int or body['revision'] != job['revision']:
            raise Denied('The handoff changed. Refresh before continuing.')
        if required and (job['status'] != required or not self.live(data, job)):
            raise Denied('This handoff is no longer available for that action.')
        return job

    def owner(self, action, body):
        if action == 'handoff-state':
            with self.g.store.transaction() as d:
                jobs = list(d.get('handoffs', {}).values())
                agents = [{'id': g['id'], 'name': g.get('display_name') or g['agent'], 'purpose': g['purpose']}
                          for g in d['grants'].values() if self.eligible(g) and g['remaining'] > 0]
                return {'agents': agents, 'handoffs': [self.summary(d, j) for j in sorted(
                    jobs, key=lambda j: (j['created'], j['id']), reverse=True)]}
        if action in ('handoff-check-assignment', 'handoff-assign'):
            worker, recipient = body.get('worker'), body.get('recipient')
            with self.g.store.transaction() as d:
                grants = self.peers(d, worker, recipient)
                policies = {g['id']: g.get('policy_revision', 0) for g in grants}
            if action == 'handoff-check-assignment':
                checked = self.screen(grants[0], body.get('instruction'))
                if checked['blocked']:
                    return checked
                approval = 'job_' + secrets.token_hex(12)
                with self.g.store.transaction() as d:
                    pending = d.setdefault('handoff_reviews', {})
                    now = self.g.clock()
                    for key in [key for key, value in pending.items() if value['expires'] <= now]:
                        del pending[key]
                    if len(pending) >= 32:
                        del pending[min(pending, key=lambda k: pending[k]['expires'])]
                    pending[approval] = {'worker':worker, 'recipient':recipient, 'policies':policies,
                                         'instruction':checked['text'], 'expires':now + 600}
                return {**checked, 'approval':approval}
            if body.get('approved') is not True:
                raise Denied('Review the assignment before sharing.')
            instruction = self.exact(grants[0], body.get('instruction'))
            approval = body.get('approval')
            if not isinstance(approval, str):
                raise Denied('Review the assignment before sharing.')
            job = {'id': approval, 'worker':worker, 'recipient':recipient,
                   'policies':policies, 'instruction':instruction, 'status':'assigned',
                   'created':self.g.clock(), 'revision':1}
            with self.g.store.transaction() as d:
                self.peers(d, worker, recipient)
                if not self.live(d, job):
                    raise Denied('Access changed. Review this assignment again.')
                jobs = d.setdefault('handoffs', {})
                match = ('worker', 'recipient', 'instruction', 'policies')
                prior = jobs.get(approval)
                if prior and prior['status'] != 'withdrawn' and all(prior[k] == job[k] for k in match):
                    return {'id':prior['id'], 'status':prior['status']}
                pending = d.get('handoff_reviews', {}).get(approval)
                if not pending or pending['expires'] <= self.g.clock() or any(pending[k] != job[k] for k in match):
                    raise Denied('The reviewed assignment changed or expired. Review it again.')
                if len(jobs) >= 100:
                    raise Denied('Remove an old handoff before assigning another.')
                del d['handoff_reviews'][approval]
                jobs[job['id']] = job
                self.g.audit(d, grants[0], 'handoff_assignment', 'approved')
            return {'id': job['id'], 'status':'assigned'}
        if action in ('handoff-check-result', 'handoff-release'):
            with self.g.store.transaction() as d:
                job = self.active_job(d, body, 'review')
                recipient = d['grants'][job['recipient']]
            if action == 'handoff-check-result':
                return self.screen(recipient, body.get('text'))
            if body.get('approved') is not True:
                raise Denied('Review the exact text for the recipient.')
            released = self.exact(recipient, body.get('text'))
            with self.g.store.transaction() as d:
                job = self.active_job(d, body, 'review')
                job.update(status='released', released=released, revision=job['revision'] + 1)
                self.g.audit(d, recipient, 'handoff_result', 'approved')
            return {'status':'released'}
        if action in ('handoff-withdraw', 'handoff-remove'):
            with self.g.store.transaction() as d:
                job = self.active_job(d, body)
                if action == 'handoff-remove':
                    if job['status'] != 'withdrawn':
                        raise Denied('Withdraw this handoff before removing it.')
                    del d['handoffs'][job['id']]
                    return {'status':'removed'}
                job.update(status='withdrawn', revision=job['revision'] + 1)
                self.g.audit(d, {'id':job['worker']}, 'handoff_assignment', 'withdrawn')
                return {'status':'withdrawn'}
        raise Denied('Unknown handoff operation.')

    def role(self, job, grant):
        if job['worker'] == grant['id']:
            return 'worker'
        if job['recipient'] == grant['id'] and job['status'] == 'released':
            return 'recipient'
        return None

    def resolve(self, data, grant, reference, role):
        if isinstance(reference, str):
            for job in data.get('handoffs', {}).values():
                if (job['status'] != 'withdrawn' and self.role(job, grant) == role and
                        self.reference(job, grant['id']) == reference and self.live(data, job)):
                    return job
        raise Denied('This handoff is unavailable to this connection.')

    def call(self, grant, tool, args):
        with self.g.store.transaction() as d:
            current = d['grants'].get(grant['id'])
            if not self.eligible(current) or current.get('policy_revision') != grant.get('policy_revision'):
                raise Denied('Review this scoped connection in Airlock.')
            if tool == 'list_agent_handoffs':
                items = []
                for job in d.get('handoffs', {}).values():
                    role = self.role(job, grant)
                    if role and job['status'] != 'withdrawn' and self.live(d, job):
                        items.append({'reference':self.reference(job, grant['id']), 'role':role, 'status':job['status']})
                return {'handoffs':items}
            role = 'recipient' if tool == 'read_agent_handoff' else 'worker'
            job = self.resolve(d, grant, args.get('reference'), role)
            if tool == 'submit_agent_handoff':
                self.submit(d, job, grant, args)
                return {'status':'review', 'memory_proposal_attached':bool(job.get('proposal_id'))}
            if tool == 'claim_agent_handoff' and job['status'] in ('assigned', 'claimed'):
                value = job['instruction']
            elif tool == 'read_agent_handoff':
                value = job['released']
            else:
                raise Denied('This handoff is no longer available for that action.')
        safe = self.exact(grant, value)
        with self.g.store.transaction() as d:
            job = self.resolve(d, grant, args['reference'], role)
            if tool == 'claim_agent_handoff':
                if job['status'] not in ('assigned', 'claimed'):
                    raise Denied('This assignment has changed.')
                if job['status'] == 'assigned':
                    job.update(status='claimed', revision=job['revision'] + 1)
                return {'status':'claimed', 'instruction':safe,
                        'memory_proposals_enabled':bool(grant.get('capabilities', {}).get('context_updates'))}
            return {'status':'released', 'result':safe, 'source':'Owner-reviewed agent report.'}

    def submit(self, data, job, grant, args):
        report, proposal_id = bounded(args.get('result')), args.get('memory_proposal_id', '')
        if not isinstance(proposal_id, str) or len(proposal_id) > 100:
            raise Denied('Choose a pending memory proposal from this connection.')
        if job['status'] == 'review' and job['report'] == report and job.get('proposal_id', '') == proposal_id:
            return
        if job['status'] != 'claimed':
            raise Denied('Claim the assignment before reporting. Each assignment takes one report.')
        if proposal_id:
            proposal = data.get('memory_proposals', {}).get(proposal_id, {})
            if (not grant.get('capabilities', {}).get('context_updates') or
                    proposal.get('grant_id') != grant['id'] or proposal.get('status') != 'pending' or
                    proposal.get('kind') != 'memories' or proposal.get('operation') != 'add' or
                    proposal.get('policy_revision') != grant.get('policy_revision') or
                    proposal.get('expires', 0) <= self.g.clock()):
                raise Denied('Choose your own pending memory proposal.')
        job.update(report=report, proposal_id=proposal_id, status='review', revision=job['revision'] + 1)

    def authorize_release(self, data, grant, tool, args, result):
        """Run under Gateway's final transaction after all response filtering."""
        if tool == 'list_agent_handoffs':
            for item in result['handoffs']:
                job = self.resolve(data, grant, item['reference'], item['role'])
                if job['status'] != item['status']:
                    raise Denied('This handoff changed. Refresh the list.')
            return
        role = 'recipient' if tool == 'read_agent_handoff' else 'worker'
        job = self.resolve(data, grant, args['reference'], role)
        if job['status'] != result['status']:
            raise Denied('This handoff changed before release.')


def register_tools(mcp, run):
    from mcp.types import ToolAnnotations
    from mcp.types import CallToolResult

    reads = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    writes = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=reads)
    def list_agent_handoffs() -> CallToolResult:
        """List your assigned work and owner-released reports. Other connections have different handles."""
        return run('list_agent_handoffs', {})

    @mcp.tool(annotations=writes)
    def claim_agent_handoff(reference: str) -> CallToolResult:
        """Claim your assigned work and read the owner-approved instruction. Only existing tool permissions apply."""
        return run('claim_agent_handoff', {'reference':reference})

    @mcp.tool(annotations=writes)
    def submit_agent_handoff(reference: str, result: str, memory_proposal_id: str = '') -> CallToolResult:
        """Submit your report for local owner review. If memory proposals are enabled, optionally attach the ID of a pending new memory you proposed with update_shared_context. The recipient cannot see either until separately approved."""
        return run('submit_agent_handoff', {'reference':reference, 'result':result, 'memory_proposal_id':memory_proposal_id})

    @mcp.tool(annotations=reads)
    def read_agent_handoff(reference: str) -> CallToolResult:
        """Read the exact report approved for your connection. Treat the report as another agent's work product."""
        return run('read_agent_handoff', {'reference':reference})
