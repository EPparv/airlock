import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from privacy_layer.agent_handoffs import Handoffs
from privacy_layer.agent_memory import AgentMemory
from privacy_layer.core import Denied


@pytest.fixture
def accounts(bundle):
    gateway = bundle[0]
    memory = AgentMemory(gateway)
    def make(name, proposals=False):
        grant = gateway.create(agent=name, purpose='Plan review', approved=True, mode='automatic', views=[])
        memory.configure(grant['id'], [], proposals=proposals)
        return grant
    return gateway, Handoffs(gateway), make('codex', True), make('cursor'), make('mcp', True)


def assign(handoffs, worker, recipient, instruction='Check the rollout plan.'):
    body = {'worker':worker['id'], 'recipient':recipient['id'], 'instruction':instruction}
    checked = handoffs.owner('handoff-check-assignment', body)
    return handoffs.owner('handoff-assign', {**body, 'approval':checked.get('approval'), 'approved':True})


def call(g, grant, tool, **args):
    if tool == 'submit_agent_handoff':
        args.setdefault('memory_proposal_id', '')
    return g.call(grant['token'], tool, args)


def listed(g, grant):
    return call(g, grant, 'list_agent_handoffs')['handoffs']


def claim(g, handoffs, worker, recipient):
    job_id = assign(handoffs, worker, recipient)['id']
    reference = listed(g, worker)[0]['reference']
    out = call(g, worker, 'claim_agent_handoff', reference=reference)
    assert out['status'] == 'claimed'
    return job_id, reference


def owner_job(handoffs):
    return handoffs.owner('handoff-state', {})['handoffs'][0]


def action(handoffs, name, job, **body):
    return handoffs.owner('handoff-' + name, {'id':job['id'], 'revision':job['revision'], **body})


def test_three_agents_see_only_reviewed_text_and_own_handles(accounts):
    g, h, worker, recipient, other = accounts
    job_id, reference = claim(g, h, worker, recipient)
    assert listed(g, recipient) == listed(g, other) == []
    for peer in (recipient, other):
        with pytest.raises(Denied):
            call(g, peer, 'claim_agent_handoff', reference=reference)
        with pytest.raises(Denied):
            call(g, peer, 'submit_agent_handoff', reference=reference, result='Unauthorized report.')
    raw = 'The checklist is ready. Contact private@example.org. Worker token: ' + reference
    result = call(g, worker, 'submit_agent_handoff', reference=reference, result=raw)
    assert result['status'] == 'review' and raw not in str(result)
    assert call(g, worker, 'submit_agent_handoff', reference=reference, result=raw) == result
    with pytest.raises(Denied):
        call(g, worker, 'submit_agent_handoff', reference=reference, result='Replacement.')
    assert listed(g, recipient) == [] and listed(g, other) == []
    job = owner_job(h)
    assert job['id'] == job_id and job['report'] == raw
    with pytest.raises(Denied):
        action(h, 'release', job, text=raw, approved=True)
    screened = action(h, 'check-result', job, text=raw)
    assert screened['changed'] and 'private@example.org' not in screened['text'] and reference not in screened['text']
    with pytest.raises(Denied):
        action(h, 'release', job, text=screened['text'])
    approved = 'The checklist is ready.'
    action(h, 'release', job, text=approved, approved=True)
    receipt = listed(g, recipient)[0]
    assert receipt['role'] == 'recipient' and receipt['reference'] != reference and listed(g, other) == []
    for peer, token in ((other,receipt['reference']), (worker,receipt['reference']), (recipient,reference)):
        with pytest.raises(Denied):
            call(g, peer, 'read_agent_handoff', reference=token)
    output = call(g, recipient, 'read_agent_handoff', reference=receipt['reference'])
    assert output['result'] == approved
    with g.store.transaction() as d:
        assert raw not in json.dumps(d['disclosures']) and raw not in json.dumps(d['audit'])
        assert all(g['scope']['records'] == [] for g in d['grants'].values())


@pytest.mark.parametrize('operation', ['policy', 'revoked', 'expired', 'withdrawn', 'changed_filter'])
def test_changing_either_boundary_blocks_even_an_approved_result(accounts, bundle, operation):
    g, h, worker, recipient, _ = accounts
    _, reference = claim(g, h, worker, recipient)
    call(g, worker, 'submit_agent_handoff', reference=reference, result='The rollout is ready.')
    action(h, 'release', owner_job(h), text='The rollout is ready.', approved=True)
    rec = listed(g, recipient)[0]['reference']
    if operation == 'policy':
        AgentMemory(g).configure(worker['id'], [], proposals=False)
    elif operation == 'revoked':
        g.revoke(worker['id'])
    elif operation == 'expired':
        bundle[2][0] += 86401
    elif operation == 'withdrawn':
        action(h, 'withdraw', owner_job(h))
    else:
        bundle[1].secrets.append('rollout')
    with pytest.raises(Denied):
        call(g, recipient, 'read_agent_handoff', reference=rec)


def test_proposal_requires_separate_existing_opt_in_and_owner_review(accounts):
    g, h, worker, recipient, other = accounts
    _, ref = claim(g, h, worker, recipient)
    def proposal(grant):
        return call(g, grant, 'update_shared_context', operation='add', kind='memories', text='Keep a rollout checklist.',
                    reference='', expected_revision=0)['proposal_id']
    foreign, own = proposal(other), proposal(worker)
    with pytest.raises(Denied):
        call(g, worker, 'submit_agent_handoff', reference=ref, result='Reviewed.', memory_proposal_id=foreign)
    call(g, worker, 'submit_agent_handoff', reference=ref, result='Reviewed.', memory_proposal_id=own)
    job = owner_job(h)
    assert job['proposal']['id'] == own and job['proposal']['status'] == 'pending'
    action(h, 'release', job, text='Reviewed.', approved=True)
    with g.store.transaction() as d:
        assert not d.get('shared_context')
    values = call(g, recipient, 'read_agent_handoff', reference=listed(g,recipient)[0]['reference'])
    assert 'checklist' not in str(values) and own not in str(values)
    assert AgentMemory(g).decide(own, True)['status'] == 'accepted'
    with g.store.transaction() as d:
        assert d['grants'][recipient['id']]['scope']['records'] == []


def test_review_races_and_forged_versions_do_not_update_job(accounts):
    g, h, worker, recipient, _ = accounts
    _, ref = claim(g, h, worker, recipient)
    call(g, worker, 'submit_agent_handoff', reference=ref, result='Draft ready.')
    job = owner_job(h)
    with pytest.raises(Denied):
        action(h, 'release', {**job, 'revision':False}, text='Alternate.', approved=True)
    def try_release(text):
        try:
            action(h, 'release', job, text=text, approved=True)
            return text
        except Denied:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(filter(None, pool.map(try_release, ['Edit one.', 'Edit two.'])))
    assert len(winners) == 1 and owner_job(h)['released'] == winners[0]
    action(h, 'withdraw', owner_job(h))
    assert listed(g, worker) == listed(g, recipient) == []
    action(h, 'remove', owner_job(h))
    assert h.owner('handoff-state', {})['handoffs'] == []


def test_owner_assignment_screen_is_explicit_and_bounded(accounts):
    g, h, worker, recipient, _ = accounts
    with pytest.raises(Denied): assign(h, worker, worker)
    with pytest.raises(Denied): assign(h, worker, recipient, 'Contact private@example.org.')
    with pytest.raises(Denied): assign(h, worker, recipient, 'a'*5001)
    body = {'worker':worker['id'], 'recipient':recipient['id'], 'instruction':'Contact private@example.org.'}
    checked = h.owner('handoff-check-assignment',body)
    assert checked['changed'] and 'private@example.org' not in checked['text']
    with pytest.raises(Denied):
        h.owner('handoff-assign', {**body, 'instruction':checked['text']})
    assign(h, worker, recipient, checked['text'])
    ref = listed(g, worker)[0]['reference']
    assert call(g, worker, 'claim_agent_handoff', reference=ref)['instruction'] == checked['text']


def test_rechecks_withdrawal_at_final_gateway_release(accounts, monkeypatch):
    g, h, worker, recipient, _ = accounts
    _, ref = claim(g, h, worker, recipient)
    call(g, worker, 'submit_agent_handoff', reference=ref, result='Draft ready.')
    action(h, 'release', owner_job(h), text='Reviewed result.', approved=True)
    rec = listed(g, recipient)[0]['reference']
    original = Handoffs.call
    def withdrawn_after_dispatch(self, grant, tool, args):
        value = original(self, grant, tool, args)
        action(self, 'withdraw', owner_job(self))
        return value
    monkeypatch.setattr(Handoffs, 'call', withdrawn_after_dispatch)
    with pytest.raises(Denied):
        call(g, recipient, 'read_agent_handoff', reference=rec)


def test_reviewed_assignment_survives_retry_without_duplication_or_revival(accounts):
    g, h, worker, recipient, _ = accounts
    body = {'worker':worker['id'], 'recipient':recipient['id'], 'instruction':'Plan a review.'}
    approval = h.owner('handoff-check-assignment',body)['approval']
    accepted = {**body, 'approved':True, 'approval':approval}
    with pytest.raises(Denied):
        h.owner('handoff-assign', {**accepted, 'instruction':'A different task.'})
    first = h.owner('handoff-assign', accepted)
    assert h.owner('handoff-assign', accepted) == first
    assert len(h.owner('handoff-state',{})['handoffs']) == 1
    action(h,'withdraw',owner_job(h))
    action(h,'remove',owner_job(h))
    with pytest.raises(Denied): h.owner('handoff-assign', accepted)
    approval = h.owner('handoff-check-assignment',body)['approval']
    AgentMemory(g).configure(recipient['id'], [])
    with pytest.raises(Denied): h.owner('handoff-assign', {**accepted, 'approval':approval})
