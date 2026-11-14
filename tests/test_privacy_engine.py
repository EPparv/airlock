"""Synthetic privacy regressions. These do not establish live NEAR verification."""
import asyncio
import copy
import json
import pytest

from privacy_layer.agent_memory import AgentMemory, PrivateTasks
from privacy_layer.clients import selected_scope
from privacy_layer.core import Denied, EncryptedStore, Gateway, digest
from privacy_layer.privacy_engine import PrivacyEngine, sensitive, minimize


def grant(bundle):
    return bundle[0].create(agent='test', purpose='Synthetic privacy tests', views=[],
                            approved=True, mode='automatic')


@pytest.mark.parametrize('value', [
    'Diagnosis: synthetic condition.', 'My salary is $90,000.',
    'Passport number: X12345678', 'password=hunter-synthetic',
    'Bearer synthetic-access-token', 'Bank statement for last month.',
    'My political affiliation is fictional.', 'Home address: 123 Maple Street.',
])
def test_sensitive_record_detection(value):
    assert sensitive(value)


def test_mixed_selection_shares_preferences_and_holds_sensitive_sources(bundle):
    g,s,*_=bundle
    s.data['memories','medical']={'text':'Diagnosis: synthetic condition. Appointment is Thursday.', 'device_only':False}
    m=AgentMemory(g);rows=m.snapshot()
    refs=['skills:s1','memories:medical']
    scope=selected_scope(g,{ref:digest(rows[ref]['text']) for ref in refs})
    assert scope['compute'] and scope['disclose_records']==['skills:s1']
    gr=grant(bundle);m.configure(gr['id'],**scope)
    result=g.call(gr['token'],'get_private_context',{'query':''})
    assert 'Be concise' in str(result) and 'synthetic condition' not in str(result)
    assert result['private_tasks_available']
    with pytest.raises(Denied):g.call(gr['token'],'read_gmail',{'reference':'anything'})
    task=g.call(gr['token'],'request_private_task',{'instruction':'Summarize the appointment.', 'records':[], 'route':'local'})
    assert 'Appointment' not in json.dumps(task) and 'payload' not in task
    staged=PrivateTasks(g).read(task['task_id'])
    assert 'Appointment is Thursday' in staged['payload']


def test_all_sensitive_default_is_compute_only_and_never_share_still_denied(bundle):
    g,s,*_=bundle;m=AgentMemory(g)
    scope=selected_scope(g,{'memories:m1':digest(s.data['memories','m1']['text'])})
    assert scope['compute'] and not scope['disclose'] and scope['disclose_records']==[]
    gr=grant(bundle);m.configure(gr['id'],**scope)
    with pytest.raises(Denied,match='compute-only'):g.call(gr['token'],'get_private_context',{'query':''})
    with pytest.raises(Denied):selected_scope(g,{'memories:m2':digest(s.data['memories','m2']['text'])})


def test_old_disclosure_permission_does_not_bypass_new_sensitivity(bundle):
    g,s,*_=bundle;s.data['memories','m1']['text']='A regular project is due Thursday.'
    gr=grant(bundle);m=AgentMemory(g);m.configure(gr['id'],['memories:m1'],disclose=True)
    assert g.call(gr['token'],'get_private_context',{'query':''})['items']
    s.data['memories','m1']['text']='Diagnosis: newly sensitive condition.'
    assert not g.call(gr['token'],'get_private_context',{'query':''})['items']
    assert m.grant(gr['id'])['scope']['compute'] is False  # no silent permission expansion


def test_stable_connection_private_aliases_survive_restart(bundle):
    g,s,*_=bundle;a=grant(bundle);b=grant(bundle)
    one=PrivacyEngine(g,a);two=PrivacyEngine(g,b)
    source='Name: Alice Example. Employer: Acme Labs. Alice Example prefers concise replies.'
    first=one.filter(source);second=two.filter(source)
    assert 'Alice Example' not in first and 'Acme Labs' not in first
    assert '[person-' in first and '[organization-' in first and first!=second
    restarted=Gateway(EncryptedStore(g.store.path,b'x'*32),s,g.clock)
    assert PrivacyEngine(restarted,a).filter(source)==first
    assert b'Alice Example' not in g.store.path.read_bytes()
    assert one.pseudonymize('Alice Example') in first


def test_minimization_keeps_qualifications_and_complete_skills(bundle):
    value='Atlas launch is Thursday. I vacationed on a rare island. Do not announce until approved.'
    text,changed=minimize(value,'Atlas launch')
    assert changed and 'rare island' not in text and 'Do not announce' in text
    g,s,*_=bundle;s.data['memories','m1']['text']=value
    gr=grant(bundle);m=AgentMemory(g);m.configure(gr['id'],['memories:m1','skills:s1'],disclose=True)
    result=g.call(gr['token'],'get_private_context',{'query':'Atlas launch'})
    assert 'rare island' not in str(result) and 'Do not announce' in str(result)
    assert any(x.get('context_minimized') and not x['text_complete'] for x in result['items'])


@pytest.mark.parametrize('secret',[
    'alice@example.com','+1 (212) 555-0123','123 Maple Street',
    'github_pat_'+'a'*30,'xoxb-'+'a'*20,'Bearer '+'a'*25,
    'eyJabcdefghijk.abcdefghijklmnop.abcdefghijklmnop',
    'PRIVATE_CREDENTIAL_CANARY',
])
def test_output_screening_prevents_raw_release(bundle,secret):
    engine=PrivacyEngine(bundle[0],grant(bundle))
    raw='The next step is ready. '+secret
    report=engine.screen(raw)
    assert report['changed'] and secret not in report['text']
    with pytest.raises(Denied):engine.require_safe_release(raw)
    if report['text']:assert engine.require_safe_release(report['text'])==report['text']


def test_compute_keeps_useful_sensitive_facts_but_redacts_identity_and_secrets(bundle):
    engine=PrivacyEngine(bundle[0],grant(bundle))
    value='Name: Alice Example. Salary: $90,000. Contact: alice@example.com.\napi_key=synthetic-secret'
    safe=engine.filter(value,compute=True)
    assert '$90,000' in safe and 'Alice Example' not in safe and 'alice@example.com' not in safe
    assert 'synthetic-secret' not in safe
    assert engine.filter('Never share. Salary: $90,000.',compute=True) is None
    assert engine.filter('Password reset code is 123456.',compute=True) is None


def test_edited_result_requires_new_screen_and_release_is_rechecked(bundle):
    g,s,*_=bundle;s.data['memories','m1']['text']='Atlas launch is Thursday.'
    gr=grant(bundle);memory=AgentMemory(g);memory.configure(gr['id'],['memories:m1'],compute=True)
    class Provider:
        async def complete(self,body,authorize):
            authorize()
            return {'draft':'Ready for Thursday. Contact alice@example.com.', 'checks':{}, 'inference_calls':1}
    tasks=PrivateTasks(g,local=Provider());active=memory.grant(gr['id'])
    staged=tasks.prepare(active,'Summarize the launch.',['memories:m1'])
    task=tasks.read(staged['task_id']);done=asyncio.run(tasks.send(task['id'],True,task['sha256']))
    fingerprint=digest(done['result'])
    assert done['result']['screening']['changed']
    with pytest.raises(Denied):tasks.release(task['id'],True,'Ready. Contact alice@example.com.',fingerprint)
    assert tasks.result(active,task['id'])['text'] is None
    screened=tasks.screen(task['id'],'Ready. Contact alice@example.com.',fingerprint)
    tasks.release(task['id'],True,screened['text'],fingerprint)
    assert 'alice@example.com' not in tasks.result(active,task['id'])['text']
    s.secrets.append('Ready')
    with pytest.raises(Denied):tasks.result(active,task['id'])


def test_final_boundary_filters_reviewed_title_and_text(bundle):
    g,s,_,views,make=bundle
    views[1]['text']='Be concise. Email alice@example.com.'
    views[1]['title']='Alice alice@example.com'
    gr=make()
    result=g.call(gr['token'],'get_private_context',{'query':''})
    assert 'alice@example.com' not in json.dumps(result)


def test_opaque_references_hide_source_ids_and_are_usable_only_in_scope(bundle):
    g,s,*_=bundle
    raw='memories:alice@example.com'
    s.data['memories','alice@example.com']={'text':'Atlas launches Thursday.', 'device_only':False}
    a,b=grant(bundle),grant(bundle);m=AgentMemory(g)
    for gr in (a,b):m.configure(gr['id'],[raw],disclose=True,compute=True)
    result=g.call(a['token'],'get_private_context',{'query':''})
    alias=result['items'][0]['ref']
    assert 'alice@example.com' not in json.dumps(result)
    assert 'alice@example.com' not in json.dumps(g.call(a['token'],'privacy_status',{}))
    assert 'alice@example.com' not in json.dumps(g.call(a['token'],'context_status',{}))
    assert m.resolve(m.grant(a['id']),[alias],capability='compute')[0]['ref']==raw
    with pytest.raises(Denied):m.resolve(m.grant(b['id']),[alias],capability='compute')


def test_sensitive_lineage_cannot_be_laundered_as_a_safe_summary(bundle):
    g,s,*_=bundle;m=AgentMemory(g)
    rows={'parent':{'text':'Salary: $90,000.','parents':[]},
          'summary':{'text':'The plan is ready.','parents':['parent']}}
    assert m.requires_compute('summary',rows)
    rows['parent']['text']='A regular preference.'
    assert not m.requires_compute('summary',rows)


def test_near_diagnostic_never_echoes_credentials_or_response_body():
    from nearai_inference_sdk.utils.errors import ApiError, ApiFailure
    from privacy_layer.near_provider import failure_detail
    error=ApiError(ApiFailure(code='api.http_status',details={'status':401,'body':'FICTIONAL_CREDENTIAL'}))
    assert failure_detail(error)==' NEAR returned HTTP 401.'
