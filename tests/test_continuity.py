"""Fictional multi-session recall and privacy regressions, not model-quality claims."""
import json
import pytest
from starlette.testclient import TestClient
from privacy_layer.context import ContextHub, parse_context, PROMPT
from privacy_layer.sources import LocalSources
from privacy_layer.core import Gateway, EncryptedStore, Denied, digest
from privacy_layer.agent_memory import AgentMemory
from privacy_layer.server import owner_app


@pytest.fixture
def env(tmp_path):
    now=[1800000000]
    source=LocalSources(key=b'c'*32,context_home=tmp_path/'profile')
    store=EncryptedStore(tmp_path/'continuity.enc',source.key);source.connection_store=store
    gateway=Gateway(store,source,lambda:now[0])
    return gateway,source,now


def add(env,memories=None,skills=None):
    g,s,_=env;hub=ContextHub(g.store,clock=g.clock)
    preview=hub.preview('context.json',json.dumps({'memories':memories or [],'skills':skills or []}).encode())
    return hub.commit(preview['id'],list(range(len(preview['items']))),s.library())


def connect(env,name='codex'):
    return env[0].create(agent=name,purpose='Fictional continuity test',views=[],approved=True,mode='automatic',max_calls=100)


def read(env,grant,query=''):
    return env[0].call(grant['token'],'get_private_context',{'query':query})


def test_prompt_categories_coverage_and_core_markers():
    prompt=PROMPT.format(code='fictional-code')
    assert 'SECOND PASS' in prompt and 'one-time code' in prompt and 'unresolved contradictions' in prompt
    parsed=parse_context('handoff.md',b'# Memories\n- [CORE] I lead a robotics studio.\n- Atlas launch is December 4.\n# Skills\n## [CORE] Answer style\nUse concise sentences.\n# Scope\nCurrent chat only; older sources unavailable.')
    assert [r['core'] for r in parsed['items']]==[True,False,True]
    assert '[CORE]' not in str(parsed['items'])
    assert 'older sources unavailable' in parsed['scope']
    with pytest.raises(Denied):parse_context('context.txt',('[CORE] '+'word '*1000).encode())


def test_core_survives_unrelated_queries_restart_and_second_agent(env):
    add(env,['[CORE] I lead a robotics studio.','Atlas launch is December 4.'],['[CORE] Use concise sentences and distinguish plans from completed work.'])
    first,second=connect(env),connect(env,'claude-desktop')
    for grant in (first,second):
        result=read(env,grant,'weekend cooking')
        assert result['core_included']==2 and 'robotics studio' in str(result) and 'concise sentences' in str(result)
        assert 'December 4' not in str(result['items'])
    g,s,now=env
    reopened=EncryptedStore(g.store.path,s.key);s.connection_store=reopened
    restarted=Gateway(reopened,s,lambda:now[0])
    assert 'robotics studio' in str(restarted.call(second['token'],'get_private_context',{'query':'hiking'}))
    assert b'robotics studio' not in g.store.path.read_bytes()
    assert all(grant['last_context_read']==now[0] for grant in restarted.list_grants())


def test_core_never_bypasses_scope_private_or_compute_only(env):
    add(env,['[CORE] I lead a robotics studio.',{'text':'[CORE] Restricted identity fact','device_only':True},'Atlas launch is December 4.'])
    g,s,_=env;m=AgentMemory(g);grant=connect(env)
    assert 'Restricted identity fact' not in str(read(env,grant,'identity'))
    launch=next(ref for ref,r in m.snapshot().items() if 'December' in r['text'])
    m.configure(grant['id'],[launch],disclose=True)
    assert 'robotics studio' not in str(read(env,grant,''))
    m.configure(grant['id'],[launch],compute=True)
    with pytest.raises(Denied):read(env,grant,'')


@pytest.mark.parametrize('scoped',[False,True])
def test_full_workflow_and_paginated_recall_beyond_old_cap(env,scoped):
    steps='Atlas launch checklist.\n'+'\n'.join(f'Step {i}: review the Atlas prototype carefully.' for i in range(95))+'\nFinal step: request explicit owner approval.'
    add(env,[f'Atlas checkpoint {i}: verify the prototype milestone.' for i in range(28)], [steps])
    grant=connect(env);g=env[0]
    if scoped:AgentMemory(g).configure(grant['id'],list(AgentMemory(g).snapshot()),disclose=True)
    query='Atlas';seen={};pages=0;complete_skill=False
    while query:
        result=read(env,grant,query);pages+=1
        for item in result['items']:
            seen[item['ref']]=item
            if item['kind']=='skills':
                assert item['text_complete'] and steps==item['text'];complete_skill=True
        query=result['next_query']
        assert pages<10
    assert len(seen)==29 and pages>=3 and complete_skill


def test_page_tokens_are_connection_bound_and_detect_corrections(env):
    add(env,[f'Atlas task {i} awaits approval.' for i in range(18)])
    a,b=connect(env),connect(env,'cursor');page=read(env,a,'Atlas')['next_query']
    with pytest.raises(Denied,match='another connection'):read(env,b,page)
    m=AgentMemory(env[0]);ref,row=next(iter(m.snapshot().items()))
    m.edit(ref,'Atlas task has been completed.',digest(row['text']))
    with pytest.raises(Denied,match='changed'):read(env,a,page)
    assert 'completed' in str(read(env,a,'Atlas completed')['items'])


def test_edit_retire_refresh_and_stale_edit_conflict(env):
    add(env,['[CORE] I prefer afternoon meetings.'])
    g,s,_=env;m=AgentMemory(g);a,b=connect(env),connect(env,'cursor')
    ref,row=next(iter(m.snapshot().items()));old=read(env,a,'scheduling')['context_fingerprint']
    m.edit(ref,'I prefer morning meetings.',digest(row['text']))
    new=read(env,b,'scheduling')
    assert old!=new['context_fingerprint'] and 'morning' in str(new) and 'afternoon' not in str(new)
    with pytest.raises(Denied,match='changed'):m.edit(ref,'Evenings.',digest(row['text']))
    m.retire(ref,True)
    assert not read(env,a,'scheduling')['items']
    m.retire(ref,False)
    assert 'morning' in str(read(env,a,'scheduling'))
    m.keep_local(ref,True)
    assert not read(env,b,'scheduling')['items']


def test_approved_note_withheld_after_source_correction(env):
    add(env,['Atlas launch is December 4.'])
    g,s,_=env;m=AgentMemory(g);grant=connect(env);g.set_capabilities(grant['id'],context_updates=True)
    ref,row=next(iter(m.snapshot().items()))
    proposal=g.call(grant['token'],'update_shared_context',{'operation':'add','kind':'memories','text':'Atlas launch reminder: prepare before December 4.','reference':'','expected_revision':0})
    assert 'reminder' not in str(read(env,grant,'Atlas')['items'])
    saved=m.decide(proposal['proposal_id'],True)
    assert 'reminder' in str(read(env,grant,'Atlas')['items'])
    m.edit(ref,'Atlas launch moved to December 9.',digest(row['text']))
    result=read(env,grant,'Atlas')
    assert 'December 9' in str(result['items']) and 'December 4' not in str(result['items'])
    state=next(r for r in m.state()['records'] if saved['reference'] in r['ref'])
    assert state['stale'] is True


def test_owner_controls_not_callable_with_agent_token(env):
    add(env,['Atlas launch is December 4.']);g=env[0];grant=connect(env)
    m=AgentMemory(g);ref,row=next(iter(m.snapshot().items()))
    actions={'memory-priority':{'ref':ref,'core':True},'memory-retire':{'ref':ref,'retired':True},'memory-edit':{'ref':ref,'text':'Changed','expected_hash':digest(row['text'])}}
    with TestClient(owner_app(g,'owner'),base_url='http://127.0.0.1:8791') as client:
        for action,body in actions.items():
            assert client.post('/api/'+action,json=body,headers={'Authorization':'Bearer '+grant['token']}).status_code==401
        assert client.post('/api/memory-priority',json=actions['memory-priority'],headers={'Authorization':'Bearer owner'}).status_code==200
    assert 'December 4' in str(read(env,grant,'unrelated cooking'))


def test_reimport_promotes_existing_core_without_duplicates_and_limits_pins(env):
    add(env,['I lead a robotics studio.'])
    result=add(env,['[CORE] I lead a robotics studio.'])
    assert result['added']==0 and result['core_updated']==1
    assert len(AgentMemory(env[0]).snapshot())==1
    grant=connect(env)
    assert 'robotics studio' in str(read(env,grant,'unrelated question'))
    add(env,[f'[CORE] Stable preference {i}.' for i in range(5)])
    with pytest.raises(Denied,match='six core'):add(env,['[CORE] Extra preference.'])
    assert len(AgentMemory(env[0]).snapshot())==6
    assert read(env,grant,'')['core_included']==6
    result=add(env,[{'text':'[CORE] I lead a robotics studio.','device_only':True}])
    assert result['privacy_updated']==1
    assert 'robotics studio' not in str(read(env,grant,'unrelated question'))


@pytest.mark.parametrize('scoped',[False,True])
def test_status_changes_on_pin_retirement_and_correction(env,scoped):
    add(env,['Atlas launch is December 4.'])
    g=env[0];m=AgentMemory(g);grant=connect(env);ref,row=next(iter(m.snapshot().items()))
    if scoped:m.configure(grant['id'],[ref],disclose=True)
    def revision():return g.call(grant['token'],'context_status',{})['revision']
    versions=[revision()]
    m.priority(ref,True);versions.append(revision())
    m.edit(ref,'Atlas launch is December 9.',digest(row['text']));versions.append(revision())
    m.retire(ref,True);versions.append(revision())
    assert len(set(versions))==4
    assert revision()==versions[-1]


def test_cursor_expiry_and_permission_revocation(env):
    add(env,[f'Atlas checkpoint {i}.' for i in range(15)])
    grant=connect(env);query=read(env,grant,'Atlas')['next_query']
    env[2][0]+=1801
    with pytest.raises(Denied,match='expired'):read(env,grant,query)
    query=read(env,grant,'Atlas')['next_query']
    env[0].revoke(grant['id'])
    with pytest.raises(Denied):read(env,grant,query)
