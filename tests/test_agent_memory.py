"""Fictional boundary tests. Mock provider tests do not prove live AI inference."""
import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from privacy_layer.agent_memory import AgentMemory, PrivateTasks
from privacy_layer.core import Denied, digest
from privacy_layer.memory_demo import make_gateway, demo_call, RECORDS, DemoBoundary
from privacy_layer.local_provider import LocalProvider
from privacy_layer.server import owner_app


@pytest.fixture
def env(tmp_path):
    g=make_gateway(tmp_path);m=AgentMemory(g)
    with g.store.transaction() as d:agents=copy.deepcopy(d['memory_demo_agents'])
    return g,m,agents


def call(env, agent, tool, **args):
    g,_,agents=env
    return g.call(agents[agent]['token'],tool,args)


def grant(env, agent='ironclaw'):
    g,m,agents=env
    return m.grant(agents[agent]['id'])


def proposal(env, text='Northstar follow-up is Friday.', kind='memories'):
    return call(env,'ironclaw','update_shared_context',operation='add',kind=kind,text=text,reference='',expected_revision=0)['proposal_id']


def scope(env, agent='ironclaw', **changes):
    g,m,agents=env;gr=grant(env,agent)
    settings={**gr['scope'],'proposals':gr['capabilities']['context_updates'],**changes}
    return m.configure(gr['id'],**settings)


def test_two_agents_have_distinct_live_context(env):
    a=call(env,'codex','get_private_context',query='');b=call(env,'ironclaw','get_private_context',query='')
    assert 'calendar integration' in json.dumps(a) and 'Maya' not in json.dumps(a)
    assert 'Maya' in json.dumps(b) and 'calendar integration' not in json.dumps(b)
    for value in (a,b):
        assert 'under 120 words' in json.dumps(value)
        assert 'FINANCE-ORCHID-9247' not in json.dumps(value)


@pytest.mark.parametrize('kind',['memories','skills'])
def test_proposal_is_inactive_until_owner_accepts_then_reusable(env,kind):
    g,m,agents=env;p=proposal(env,kind=kind)
    assert not any('Friday' in r['text'] for r in g.sources.library())
    accepted=m.decide(p,True);ref=kind+':shared:'+accepted['reference']
    scope(env,'codex',records=['memories:demo-meeting','skills:demo-style',ref])
    result=call(env,'codex','get_private_context',query='Northstar')
    assert any('Friday' in r['text'] for r in result['items'])
    # Restart from encrypted bytes, retaining identities and pending status.
    restarted=make_gateway(g.store.path.parent)
    again=restarted.call(agents['codex']['token'],'get_private_context',{'query':'Northstar'})
    assert 'Friday' in str(again)
    assert b'Friday' not in g.store.path.read_bytes()


def test_reject_replay_and_owner_agent_api_separation(env):
    g,m,agents=env;p=proposal(env)
    assert m.decide(p,False)['status']=='rejected'
    with pytest.raises(Denied):m.decide(p,True)
    with TestClient(owner_app(g,'owner'),base_url='http://127.0.0.1:8791') as c:
        r=c.post('/api/memory-decide',json={'proposal_id':p,'accept':True},headers={'Authorization':'Bearer '+agents['ironclaw']['token']})
        assert r.status_code==401
    with pytest.raises(Denied):call(env,'ironclaw','memory-decide',proposal_id=p,accept=True)


def test_derived_memory_requires_sources_and_inherits_never_share(env):
    g,m,_=env;p=proposal(env);a=m.decide(p,True);ref='memories:shared:'+a['reference']
    scope(env,'codex',records=[ref])
    assert call(env,'codex','get_private_context',query='Friday')['items']==[]
    scope(env,'codex',records=[ref,'memories:demo-meeting','skills:demo-style'])
    assert 'Friday' in str(call(env,'codex','get_private_context',query='Friday'))
    m.keep_local('memories:demo-meeting',True)
    assert 'Friday' not in str(call(env,'codex','get_private_context',query='Friday'))


def test_pending_proposal_rechecks_changed_source(env):
    g,m,_=env;p=proposal(env)
    base=g.sources.library
    def changed():
        rows=base();rows[0]['text']='Changed meeting.';return rows
    g.sources.library=changed
    with pytest.raises(Denied,match='source changed'):m.decide(p,True)


@pytest.mark.parametrize('change',['revoke','expire','scope'])
def test_pending_proposal_rechecks_permissions(env,change):
    g,m,agents=env;p=proposal(env)
    if change=='revoke':g.revoke(agents['ironclaw']['id'])
    elif change=='expire':
        now=g.clock();g.clock=lambda:now+90000
    else:scope(env,disclose=False)
    with pytest.raises(Denied):m.decide(p,True)


def test_concurrent_proposals_use_revision_checks(env):
    g,m,_=env;a=m.decide(proposal(env),True);ref='memories:shared:'+a['reference']
    scope(env,records=['memories:demo-meeting','skills:demo-style',ref])
    args=dict(operation='update',kind='memories',reference=a['reference'],expected_revision=1)
    p=call(env,'ironclaw','update_shared_context',text='Northstar next step is Monday.',**args)['proposal_id']
    q=call(env,'ironclaw','update_shared_context',text='Northstar next step is Tuesday.',**args)['proposal_id']
    m.decide(p,True)
    with pytest.raises(Denied,match='changed'):m.decide(q,True)


@pytest.mark.parametrize('tool,args',[
    ('search_gmail',{'query':''}),('read_gmail',{'reference':'e1'}),
    ('list_local_skills',{'query':''}),('read_local_skill',{'skill_id':'x','resource':'','offset':0}),
    ('run_local_skill',{'skill_id':'x','script':'x','topic':'','gmail_query':''}),
    ('prepare_private_brief',{'topic':'','gmail_query':'','max_messages':0}),
    ('stage_context_import',{'transfer_code':'x','memories':[],'skills':[],'scope':''})])
def test_scoped_connection_cannot_bypass_through_legacy_tools(env,tool,args):
    with pytest.raises(Denied):call(env,'ironclaw',tool,**args)


def test_compute_only_cannot_read_raw_context_or_enable_itself(env):
    scope(env,disclose=False)
    with pytest.raises(Denied,match='compute-only'):call(env,'ironclaw','get_private_context',query='')
    with pytest.raises(Denied):call(env,'ironclaw','memory-scope',identifier=grant(env)['id'],records=[],disclose=True)
    task=call(env,'ironclaw','request_private_task',instruction='Draft follow-up.',records=[],route='local')
    assert 'Maya' not in str(task) and 'payload' not in task


def mock_local(env, hook=None, fail=False):
    sent=[]
    def handle(req):
        if req.url.path=='/api/show':
            if hook:hook()
            return httpx.Response(200,json={'details':{'format':'gguf'},'capabilities':['completion'],
                'model_info':{'general.architecture':'qwen','qwen.context_length':8192}})
        sent.append(req)
        if fail:raise httpx.ConnectError('sensitive provider failure',request=req)
        body=json.loads(req.content)
        return httpx.Response(200,json={'model':body['model'],'done':True,'done_reason':'stop',
            'message':{'content':'Hi Maya, thanks for discussing Northstar. Could we walk through the product Thursday?'}})
    return PrivateTasks(env[0],local=LocalProvider(httpx.MockTransport(handle))),sent


def prepared(env,tasks):
    task=call(env,'ironclaw','request_private_task',instruction='Draft investor follow-up.',records=[],route='local')
    return tasks.read(task['task_id'])


def send(tasks,t):return asyncio.run(tasks.send(t['id'],True,t['sha256']))


def test_exact_outbound_payload_and_two_approvals(env):
    tasks,sent=mock_local(env);t=prepared(env,tasks)
    assert call(env,'ironclaw','get_private_task_result',task_id=t['id'])['text'] is None
    with pytest.raises(Denied):asyncio.run(tasks.send(t['id'],False,t['sha256']))
    done=send(tasks,t)
    assert len(sent)==1 and sent[0].content==t['payload'].encode()
    assert b'Maya' in sent[0].content and b'FINANCE-ORCHID-9247' not in sent[0].content
    assert call(env,'ironclaw','get_private_task_result',task_id=t['id'])['text'] is None
    with pytest.raises(Denied):tasks.release(t['id'],False,'Ready for review.',digest(done['result']))
    tasks.release(t['id'],True,'Ready for your review.',digest(done['result']))
    assert call(env,'ironclaw','get_private_task_result',task_id=t['id'])['text']=='Ready for your review.'
    with pytest.raises(Denied):call(env,'codex','get_private_task_result',task_id=t['id'])
    with pytest.raises(Denied):send(tasks,t)
    assert len(sent)==1


@pytest.mark.parametrize('route',['local','near'])
def test_restricted_note_blocks_before_any_provider(env,route):
    with pytest.raises(Denied):call(env,'ironclaw','request_private_task',instruction='Summarize.',records=['memories:demo-finance'],route=route)
    assert AgentMemory(env[0]).state()['tasks']==[]
    with pytest.raises(Denied):scope(env,records=['memories:demo-finance'])


@pytest.mark.parametrize('change',['revoke','expire','policy','scope','source'])
def test_permissions_rechecked_after_provider_preflight(env,change):
    g,m,agents=env
    def hook():
        if change=='revoke':g.revoke(agents['ironclaw']['id'])
        elif change=='expire':
            now=g.clock();g.clock=lambda:now+90000
        elif change=='policy':m.keep_local('memories:demo-meeting',True)
        elif change=='scope':scope(env,compute=False)
        else:
            base=g.sources.library
            def changed():
                rows=base();rows[0]['text']='New text.';return rows
            g.sources.library=changed
    tasks,sent=mock_local(env,hook);t=prepared(env,tasks)
    with pytest.raises(Denied):send(tasks,t)
    assert sent==[]


def test_no_unauthorized_fallback_and_exception_text_not_saved(env):
    tasks,sent=mock_local(env,fail=True);t=prepared(env,tasks)
    class Forbidden:
        async def complete(self,*a):pytest.fail('No fallback')
    tasks.near=Forbidden()
    with pytest.raises(Denied):send(tasks,t)
    assert len(sent)==1 and tasks.read(t['id'])['status']=='blocked'
    assert 'sensitive provider failure' not in str(tasks.read(t['id']))


def test_result_release_invalidated_by_revocation(env):
    tasks,_=mock_local(env);t=prepared(env,tasks);done=send(tasks,t)
    env[0].revoke(env[2]['ironclaw']['id'])
    with pytest.raises(Denied):tasks.release(t['id'],True,'Approved result.',digest(done['result']))
    with pytest.raises(Denied):call(env,'ironclaw','get_private_task_result',task_id=t['id'])


def test_owner_routes_auth_origin_and_demo_isolation(env):
    app=DemoBoundary(owner_app(env[0],'owner'))
    with TestClient(app,base_url='http://127.0.0.1:8791') as c:
        assert c.post('/api/memory-state').status_code==401
        assert c.post('/api/memory-state',headers={'Authorization':'Bearer owner','Origin':'https://evil.invalid'}).status_code==403
        assert c.post('/api/context-preview',headers={'Authorization':'Bearer owner'},json={}).status_code==403
        assert c.get('/memory').status_code==200
        r=c.post('/api/memory-state',headers={'Authorization':'Bearer owner'}).json()
        assert len(r['records'])==4 and 'memory_demo_agents' not in r


def test_near_missing_configuration_blocks_without_fallback(env,monkeypatch):
    monkeypatch.delenv('NEARAI_API_KEY',raising=False)
    tasks=PrivateTasks(env[0]);r=call(env,'ironclaw','request_private_task',instruction='Draft follow-up.',records=[],route='near');t=tasks.read(r['task_id'])
    with pytest.raises(Denied,match='key'):send(tasks,t)
    assert tasks.read(t['id'])['status']=='blocked'


def test_audit_excludes_context_and_state_is_encrypted(env):
    call(env,'ironclaw','get_private_context',query='Maya')
    proposal(env)
    with env[0].store.transaction() as d:audit=json.dumps(d['audit'])
    assert 'Maya' not in audit and 'Friday' not in audit
    assert b'Friday' not in env[0].store.path.read_bytes()


def test_scope_change_during_disclosure_blocks(env,monkeypatch):
    import privacy_layer.automatic as a
    original=a.sanitize;changed=[]
    def sanitize(*args,**kwargs):
        if not changed:changed.append(True);scope(env,disclose=False)
        return original(*args,**kwargs)
    monkeypatch.setattr(a,'sanitize',sanitize)
    with pytest.raises(Denied,match='Sharing rules changed'):call(env,'ironclaw','get_private_context',query='')


def test_never_share_also_applies_to_existing_reviewed_connections(env):
    g,m,_=env
    a=g.create(agent='test',purpose='Review fixture',approved=True,views=[
        {'kind':'memories','source_id':'demo-meeting','text':'Maya asked for a walkthrough.'}])
    assert g.call(a['token'],'get_private_context',{'query':''})['items']
    m.keep_local('memories:demo-meeting',True)
    assert g.call(a['token'],'get_private_context',{'query':''})['items']==[]


def test_ironclaw_manifest_is_https_only_and_never_contains_token(env,tmp_path,monkeypatch):
    import tomllib
    from privacy_layer import clients
    from privacy_layer.ironclaw_adapter import manifest
    monkeypatch.setattr(clients,'ROOT',tmp_path)
    r=clients.connect(env[0],agent='ironclaw',approved=True,install=False,
        scope={'records':[],'disclose':False,'compute':False,'proposals':False})
    parsed=tomllib.loads(r['config'])
    assert parsed['mcp']['server']=='https://airlock.invalid/mcp'
    assert not r['installed'] and 'pal_' not in r['config']
    assert 'args' not in r and 'stdio' in r['message']
    for url in ('http://127.0.0.1:8792/mcp','https://x/mcp?key=secret','https://user:secret@x/mcp','https://x/owner'):
        with pytest.raises(Denied):manifest(url)


def test_reset_updates_tokens_and_revokes_previous_credentials(env):
    from privacy_layer.memory_demo import reset_demo
    g,_,agents=env;old=agents['codex']['token']
    reset_demo(g)
    with pytest.raises(Denied):g.authenticate(old)
    new=(g.store.path.parent/'codex.token').read_text()
    assert new!=old and g.authenticate(new)['agent']=='codex'
