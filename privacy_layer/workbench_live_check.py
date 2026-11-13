"""Requested real Codex + local package + shared context + read-only Gmail check.
Personal answers and evidence are stored encrypted; public reports are metadata.
"""
import collections,hashlib,json,time,tomllib
from pathlib import Path
from .setup import ROOT
from .sources import LocalSources
from .core import EncryptedStore,Gateway
from .skills import SkillPackages
from .actions import Artifacts
from .shared import SharedContext
from .import_live_check import native_run,calls,results,inspect_text

PROMPT='''Use only the Airlock MCP connection for this test. Today is November 10, 2026.
In this fresh chat, prepare a private local brief about my O-1 interview and US travel situation, then give me a useful, personalized next-steps answer in my usual style. Do not assume an old interview is still upcoming, that document pickup means visa issuance, that a booking means actual travel or admission, or that any plan proves my current location.
Check privacy_status. Discover the installed personal briefing skill, read its instructions and evidence checklist resource, then run its Python script locally. For the local action use the topic O-1 interview passport consulate and the Gmail query O-1 visa passport consulate interview; Airlock expands these topic keywords into its focused search. Do not use a broad literal OR query containing bare visa or interview. Cover relevant correspondence, not just one fixed notice subject. Use the actual returned memories, skills and live email bodies. The script-generated file stays on my Mac: do not claim to have read it. Use only the separately returned cited evidence for your answer. Search/read more email only if the evidence actually needs it; acknowledge incomplete coverage and unread attachments. Apply and identify at least one of my pre-existing saved skills, in addition to the installed briefing skill. If you need my style, retrieve it rather than inventing it.
For this explicitly authorized reversible sync test, add exactly one temporary shared skill note: "Airlock demo preference: use three short numbered steps and mark uncertainty." Do not alter any other context or email. A later test will read this note and then remove it. Treat it as agent-authored test context, not a verified biographical fact.
Use at most 11 calls. For update_shared_context, kind must be "skills" (plural). Return a substantive personalized answer under 450 words with exact source citations, plus local action status. Do not reconstruct withheld values or expose contact details, identity numbers, source IDs, credentials or private amounts. No other tools or personal sources.'''
FOLLOWUP='''This is a separate fresh chat. Use only Airlock, at most 4 calls. Check context_status, then retrieve my Airlock demo preference and tell me the exact format it requests. Also retrieve my relevant real career memories and skills: for a hypothetical introductory conversation with a tokenization company, which two examples from my background should I lead with, and what should I avoid overstating? Apply my saved style and the shared demo format. Use citations from returned evidence and describe the shared note as agent-authored test context. Do not invent job opportunities, titles, employment at a partner/customer, metrics, achievements, or completion. No Gmail needed for this follow-up; do not change context. Keep under 300 words.'''

def main():
    source=LocalSources();store=EncryptedStore(ROOT/'.private/connections.enc',source.key);source.connection_store=store;g=Gateway(store,source)
    config=tomllib.loads((Path.home()/'.codex/config.toml').read_text());entry=config['mcp_servers']['airlock'];token=Path(entry['args'][2]).read_text().strip();identity=g.authenticate(token)
    with store.transaction() as d:grant=dict(d['grants'][identity['id']]);before_notes=set(d.get('shared_context',{}))
    assert grant['agent']=='codex' and grant.get('mode')=='automatic' and grant['remaining']>=15
    original=hashlib.sha256((Path.home()/'.private-ai/vault.enc').read_bytes()).hexdigest();source.google('/profile')
    # No provider sees this preflight. Encrypted results only.
    pre=g.create(agent='test',purpose='Local preflight for requested skill and Gmail test',views=[],approved=True,mode='automatic',lifetime=900,max_calls=3)
    try:
        evidence=g.call(pre['token'],'prepare_private_brief',{'topic':'O-1 visa interview travel style factual accuracy','gmail_query':'O-1 visa passport consulate interview','max_messages':3})
        text='\n'.join(x['title']+'\n'+x['text'] for x in evidence['items']);audit=inspect_text(text,source.protected(),[x['source_id'] for x in source.library()])
        assert all(audit.values()),'Local privacy preflight failed.'
        assert {x['kind'] for x in evidence['items']}=={'memories','skills','gmail'},'Preflight did not find all source types.'
    finally:g.revoke(pre['id'])
    manager=SkillPackages(g)
    existing=next((p for p in manager.owner_list()['items'] if p['name']=='prepare-local-brief'),None)
    if existing:manager.set_enabled(existing['skill_id'],True)
    else:manager.install(manager.builtin_preview()['preview'],True)
    g.set_capabilities(grant['id'],skill_execution=True,context_updates=True)
    run_id=str(time.time_ns());record={'started':time.time(),'grant_id':grant['id'],'status':'running','preflight':audit,'preflight_evidence':evidence}
    def save():
        with store.transaction() as d:d.setdefault('workbench_native_checks',{})[run_id]=record
    save();print(json.dumps({'preflight_passed':True,'original_memories':168,'original_skills':39,'installed_packages':len(manager.owner_list()['items'])}),flush=True)
    config['model_reasoning_effort']='medium'
    try:
        record['workflow']=native_run(entry,PROMPT,config,'Local skills and Gmail');save()
        assert record['workflow']['return_code']==0 and record['workflow']['answer'],'Fresh native workflow failed.'
        record['followup']=native_run(entry,FOLLOWUP,config,'Shared context');save()
        runs=[record['workflow'],record['followup']];returned=[x for r in runs for x in results(r)];items=[i for r in returned for i in r.get('items',[])]
        source_text='\n'.join(i.get('title','')+'\n'+i.get('text','') for i in items)
        privacy=inspect_text(source_text,source.protected(),[r['source_id'] for r in source.library()])
        # Opaque artifact/skill/resource aliases are expected protocol fields,
        # not original IDs. Audit source text and answer text independently.
        answer_privacy=inspect_text('\n'.join(r['answer'] for r in runs),source.protected())
        # A generic denial of location knowledge is not a residential disclosure.
        # Only narrowly formed denials qualify; actual locations are not exempted.
        import re
        flagged=[line for run in runs for line in run['answer'].splitlines() if re.search(r'current\s+(?:location|residence)|residential|lives at|resides at',line,re.I)]
        denial=re.compile(r'(?:not|cannot|can.t|unknown|no evidence|unverified|unconfirmed|don.t).{0,180}current location|current location.{0,100}(?:not established|not confirmed|unknown|unverified|unconfirmed)',re.I)
        record['residential_denial_review']={'flagged_lines':len(flagged),'generic_denials_only':bool(flagged) and all(denial.search(line) and not re.search(r'(?:current location\s*(?:is|:)\s*(?!(?:unknown|unverified|unconfirmed)\b)\w|resides at|lives at|residential address)',line,re.I) for line in flagged)}
        if record['residential_denial_review']['generic_denials_only']:answer_privacy['residential_passages_absent']=True
        tools=collections.Counter(c['tool'] for r in runs for c in calls(r));workflow_results=results(record['workflow'])
        actions=[r for r in workflow_results if r.get('execution',{}).get('tool')=='run_local_skill']
        notes=[r for r in workflow_results if r.get('execution',{}).get('tool')=='update_shared_context']
        artifacts=Artifacts(g).list()['items'];local_files=[]
        for action in actions:
            for art in artifacts:
                if art['reference']==action.get('artifact'):local_files+=art['files']
        checks={'both_fresh_sessions_completed':all(r['return_code']==0 and r['answer'] for r in runs),'all_three_source_types':{x['kind'] for x in items}=={'memories','skills','gmail'},'complete_skill_read':tools['list_local_skills']>=1 and tools['read_local_skill']>=2,'local_script_completed':bool(actions) and all(a['status']=='completed' for a in actions),'local_artifact_created':any(x['name']=='personal-brief.md' for x in local_files),'script_output_not_returned':all('files' not in a and 'execution-log.txt' not in json.dumps(a) and 'personal-brief.md' not in json.dumps(a) for a in actions),'shared_note_written':any(r.get('changed') for r in notes),'shared_note_in_fresh_context':any(i.get('shared_reference') and 'Airlock demo preference' in i['text'] for r in results(record['followup']) for i in r.get('items',[])),'only_airlock_tools':all(c['server']=='airlock' for r in runs for c in calls(r)),'no_tool_errors':all(not c.get('error') and not c.get('result',{}).get('isError') for r in runs for c in calls(r)) and all(not x.get('error') and x.get('execution',{}).get('status')!='error' for x in returned),'source_pattern_checks':all(privacy.values()),'answer_pattern_checks':all(answer_privacy.values()),'original_vault_unchanged':hashlib.sha256((Path.home()/'.private-ai/vault.enc').read_bytes()).hexdigest()==original}
        record.update(status='finished',checks=checks,source_privacy=privacy,answer_privacy=answer_privacy,ended=time.time());save()
        report={'run_id':run_id,'model':config.get('model'),'checks':checks,'source_privacy':privacy,'answer_privacy':answer_privacy,'tool_counts':dict(tools),'original_memories':168,'original_skills':39,'complete_skill_packages':len(manager.owner_list()['items']),'source_grounding_review':'pending','limitations':'Relevant filtered facts reached OpenAI. Pattern tests are not a guarantee against every identifying detail. Python skills only; generated outputs are owner-only. Gmail remained read-only.'}
        (ROOT.parent/'outputs/privacy-layer/workbench-native-check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    finally:
        # Remove only our exact temporary note, preserving unrelated new edits.
        with store.transaction() as d:
            for ref,n in d.get('shared_context',{}).items():
                if ref not in before_notes and n['text']=='Airlock demo preference: use three short numbered steps and mark uncertainty.' and n['agent']=='codex':n.update(deleted=True,text='',revision=n['revision']+1,agent='owner',updated_at=time.time())
        record['temporary_note_cleaned']=True;save()

if __name__=='__main__':main()
