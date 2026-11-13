"""Two real Codex sessions: import actual filtered context, then fresh retrieval.

The destination is an empty disposable encrypted store. Personal transcripts are
retained only in the existing encrypted owner store; stdout is metadata only.
"""
import asyncio,collections,copy,json,os,re,secrets,shutil,socket,subprocess,tempfile,threading,time,tomllib
from pathlib import Path
from urllib.request import Request,urlopen
import uvicorn
from .sources import LocalSources
from .core import EncryptedStore,Gateway,SECRET,IDENTIFIER,EMAIL,canonical,normalized
from .automatic import PHONE,STREET,POSTAL_LINE,PLUS_CODE_LINE,MONEY,EXPORT_RECORD_LABEL,FILE_REFERENCE,LOCAL_PATH,clean
from .context import ContextHub
from .server import owner_app,mcp_app
from .setup import ROOT,private_write

QUESTION="I have a 20-minute introductory call with a tokenization company. What should I lead with, which two concrete stories should I use, and what should I avoid overstating? Keep it in my usual style."
FEATURES=('apps','plugins','remote_plugin','plugin_discovery_prefetch','memories','skill_search','skill_mcp_dependency_install','shell_tool','unified_exec','shell_snapshot','code_mode','multi_agent','computer_use','browser_use','browser_use_external','in_app_browser','image_generation','view_image','hooks','workspace_dependencies')

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def inspect_text(text,protected,raw_ids=()):
    return {'known_private_values_absent':not any(clean(x).casefold() in clean(text).casefold() for x in protected if len(x)>=6),
        'source_ids_absent':not any(x in text for x in raw_ids if len(x)>=8),
        'credentials_absent':not bool(SECRET.search(text)), 'identity_patterns_absent':not bool(IDENTIFIER.search(text)),
        'contact_emails_absent':not bool(EMAIL.search(text)), 'phone_patterns_absent':not bool(PHONE.search(text)),
        'street_addresses_absent':not bool(STREET.search(text)), 'postal_codes_absent':not bool(POSTAL_LINE.search(text)),
        'map_codes_absent':not bool(PLUS_CODE_LINE.search(text)), 'private_amount_patterns_absent':not bool(MONEY.search(text)),
        'embedded_message_ids_absent':not bool(re.search(r'\b[a-fA-F0-9]{16,}\b',text)),
        'legacy_export_labels_absent':not bool(EXPORT_RECORD_LABEL.search(text)),
        'source_file_references_absent':not bool(FILE_REFERENCE.search(text)),
        'local_paths_absent':not bool(LOCAL_PATH.search(text)),
        'residential_passages_absent':not bool(re.search(r'\b(?:location\s*/\s*residence|(?:current|home)\s+(?:location|residence)|residential (?:locality|location)|lives at|resides at)\b',text,re.I))}

def native_run(entry,prompt,config,phase):
    events=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='codex-import-'+phase+'-') as workspace:
        args=[shutil.which('codex'),'exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only','--json','--color','never','-C',workspace]
        for k in ('model','model_reasoning_effort'):
            if config.get(k):args+=['-c',k+'='+json.dumps(config[k])]
        for k in FEATURES:args+=['-c',f'features.{k}=false']
        args+=['-c','features.skip_host_skill_discovery=true','-c','web_search="disabled"']
        for k in ('command','args'):args+=['-c','mcp_servers.airlock.'+k+'='+json.dumps(entry[k])]
        args+=['-'];env=dict(os.environ)
        for k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN'):env.pop(k,None)
        proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        timer=threading.Timer(540,proc.kill);timer.start();reader=threading.Thread(target=lambda:errors.append(proc.stderr.read()),daemon=True);reader.start()
        print(phase+': fresh Codex session started.',flush=True)
        try:
            proc.stdin.write(prompt);proc.stdin.close()
            for line in proc.stdout:
                try:event=json.loads(line)
                except ValueError:continue
                events.append(event);item=event.get('item',{})
                if event.get('type')=='item.completed' and item.get('type')=='mcp_tool_call':print(phase+': '+item.get('tool','unknown')+' completed.',flush=True)
            proc.wait();reader.join(timeout=5)
        finally:timer.cancel()
    answers=[e['item'].get('text','') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
    answer=answers[-1] if answers else ''
    return {'events':events,'answer':answer,'stderr':''.join(errors),'return_code':proc.returncode,'prompt':prompt}

def calls(run):return [e['item'] for e in run['events'] if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
def results(run):
    return [json.loads(p['text']) for c in calls(run) for p in c.get('result',{}).get('content',[]) if p.get('type')=='text']


def main():
    config=tomllib.loads((Path.home()/'.codex/config.toml').read_text());installed=config.get('mcp_servers',{}).get('airlock',{})
    assert installed.get('command')==str(ROOT/'.venv/bin/python') and installed.get('args',[])[:2]==[str(ROOT/'privacy_layer/stdio.py'),'--token-file']
    source=LocalSources();primary=EncryptedStore(ROOT/'.private/connections.enc',source.key);source.connection_store=primary
    original=source.library();protected=source.protected();ids=[x['source_id'] for x in original]
    source_gateway=Gateway(primary,source);seed_grant=source_gateway.create(agent='test',purpose='Local selection for requested Codex import verification',views=[],mode='automatic',approved=True,lifetime=3600,max_calls=2)
    try:selected=source_gateway.call(seed_grant['token'],'get_private_context',{'query':'Estate Protocol SmartCrowd Mogul partnerships commercial legal onboarding tokenization career natural application writing concise accuracy'})
    finally:source_gateway.revoke(seed_grant['id'])
    seed={kind:[x['text'] for x in selected['items'] if x['kind']==kind] for kind in ('memories','skills')}
    assert seed['memories'] and seed['skills']
    preflight=inspect_text('\n'.join(seed['memories']+seed['skills']),protected,ids)
    if not all(preflight.values()):print(json.dumps({'preflight_failed':[k for k,v in preflight.items() if not v]}));return
    run_id=str(time.time_ns());record={'started':time.time(),'model':config.get('model'),'seed':seed,'seed_selection':selected,'preflight':preflight,'status':'running','question':QUESTION}
    def save():
        with primary.transaction() as d:d.setdefault('codex_import_checks',{})[run_id]=record
    save();print(json.dumps({'run_id':run_id,'actual_memories':len(seed['memories']),'actual_skills':len(seed['skills']),'preflight_passed':True}),flush=True)
    servers=[];threads=[]
    try:
        with tempfile.TemporaryDirectory(prefix='private-ai-real-import-') as temp:
            temp=Path(temp);isolated=LocalSources(key=secrets.token_bytes(32),context_home=temp/'empty-home')
            isolated.snapshot=lambda:{'settings':{},'workspace':{},'memories':[],'skills':[]}
            isolated.protected=lambda:list(protected)
            isolated.gmail_state=lambda:{'configured':False,'account':'','sign_in':'not_checked','error':''}
            store=EncryptedStore(temp/'test.enc',isolated.key);isolated.connection_store=store;gateway=Gateway(store,isolated);hub=ContextHub(store,temp/'empty-home')
            grant=gateway.create(agent='codex',purpose='Requested isolated real-context import test',views=[],mode='automatic',approved=True,lifetime=3600,max_calls=12)
            token_path=temp/'agent.token';private_write(token_path,grant['token']);owner=secrets.token_urlsafe(32);owner_port=free_port();mcp_port=free_port()
            for app,port in [(owner_app(gateway,owner,owner_port),owner_port),(mcp_app(gateway,mcp_port)[0],mcp_port)]:
                server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='critical',access_log=False));thread=threading.Thread(target=server.run,daemon=True);thread.start();servers.append(server);threads.append(thread)
            for _ in range(100):
                if all(x.started for x in servers):break
                time.sleep(.1)
            assert all(x.started for x in servers) and isolated.library()==[]
            def owner_api(action,data={}):
                req=Request(f'http://127.0.0.1:{owner_port}/api/'+action,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+owner,'Content-Type':'application/json'})
                return json.load(urlopen(req,timeout=20))
            transfer=owner_api('context-transfer-start')
            entry={'command':installed['command'],'args':[installed['args'][0],'--token-file',str(token_path),'--port',str(mcp_port)]}
            prompt=transfer['prompt']+'\n\nFor this authorized test, the following JSON is the actual context available in this source session. It was selected from the user\'s existing library and filtered locally. Transfer EVERY supplied memory and skill verbatim, preserving grouping and withheld placeholders. Do not summarize, invent, reconstruct hidden values or call retrieval tools. Use stage_context_import once, then report only counts and staging status. Scope: selected actual career memories and writing/accuracy skills; not a full account export.\n\n'+json.dumps(seed,ensure_ascii=False)
            record['transfer']=native_run(entry,prompt,config,'Import');save()
            assert record['transfer']['return_code']==0
            staged=owner_api('context-transfer-status').get('preview');assert staged and isolated.library()==[]
            stage_content={kind:[x['text'] for x in staged['items'] if x['kind']==kind] for kind in ('memories','skills')}
            record['staged']=staged
            exact=all(collections.Counter(normalized(x) for x in seed[k])==collections.Counter(normalized(x) for x in stage_content[k]) for k in seed)
            record['transfer_verbatim']=exact;save()
            assert exact,'The model changed or omitted supplied context during transfer.'
            # Exercise the actual owner UI save, without recording screenshots or
            # displaying personal content in terminal output.
            ui_code='''import json,sys\nfrom playwright.sync_api import sync_playwright,expect\na=json.load(sys.stdin)\nwith sync_playwright() as p:\n b=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True);page=b.new_page();page.goto(a['url']);expect(page.locator('#memoryCount')).to_have_text('0');expect(page.locator('#skillCount')).to_have_text('0');page.locator('#addContext').click();expect(page.locator('#contextReview')).to_be_visible();page.locator('#saveContext').click();expect(page.locator('#contextDone')).to_be_visible();expect(page.locator('#memoryCount')).to_have_text(str(a['memories']));expect(page.locator('#skillCount')).to_have_text(str(a['skills']));b.close();print('Owner preview saved successfully.')\n'''
            ui=subprocess.run([str(ROOT.parent/'Private_AI/.venv/bin/python'),'-c',ui_code],input=json.dumps({'url':f'http://127.0.0.1:{owner_port}/#'+owner,'memories':len(seed['memories']),'skills':len(seed['skills'])}),text=True,capture_output=True,timeout=75)
            record['owner_ui']={'return_code':ui.returncode,'stderr':ui.stderr};save();assert ui.returncode==0,'Owner UI import did not complete.'
            imported=isolated.library();assert len(imported)==sum(map(len,seed.values()))
            print('Owner preview saved; only imported records are available in the empty test library.',flush=True)
            fresh_prompt='Today is November 10, 2026, America/New_York. Use only the airlock connection for personal context. Start with privacy_status, then retrieve relevant memories and skills using at most three get_private_context calls. Do not use Gmail or any other data source. This is a hypothetical preparation exercise; do not save the question as a new fact.\n\n'+QUESTION+'\n\nGive a useful answer under 450 words, with exact citations for personal claims and a short note naming the saved skills you applied. Separate facts from recommended wording or suggestions. A partner company is not an employer. Do not invent metrics, tenure, job offers or immigration status. Finally check whether the tool results exposed credential values, identity numbers, contact/residential details, private amounts or raw source identifiers. Report only exposure categories, never repeat their values. Report actual tool failures only.'
            record['fresh']=native_run(entry,fresh_prompt,config,'Fresh answer');save();assert record['fresh']['return_code']==0
            fresh_results=results(record['fresh']);returned=[i for r in fresh_results for i in r.get('items',[])]
            cited=set(re.findall(r'\[(?:M|S|E)[0-9a-f]{8}\]',record['fresh']['answer']));labels={i['citation'] for i in returned}
            wire='\n'.join(i['title']+'\n'+i['text'] for i in returned)
            privacy=inspect_text(wire,protected,ids)
            answer_privacy=inspect_text(record['fresh']['answer'],protected,ids)
            # A statement that current location is unknown is not a disclosed
            # residential passage; source text is checked separately above.
            answer_privacy.pop('residential_passages_absent',None)
            with store.transaction() as d:record['isolated_receipts']=copy.deepcopy(d.get('disclosures',[]));record['isolated_audit']=copy.deepcopy(d['audit'])
            read_receipts=[i for r in record['isolated_receipts'] for i in r['items']]
            original_identity={canonical((r['kind'],normalized(r['text']))) for r in original}
            current_identity={canonical((r['kind'],normalized(r['text']))) for r in source.library()}
            checks={'source_library_considered':selected.get('library_counts')=={'memories':168,'skills':39},'two_fresh_native_sessions':True,'transfer_successful':all(not c.get('result',{}).get('isError') for c in calls(record['transfer'])),'only_stage_tool_used_for_transfer':len(calls(record['transfer']))==1 and calls(record['transfer'])[0]['tool']=='stage_context_import','verbatim_actual_context_imported':exact,'owner_browser_saved_import':ui.returncode==0,'fresh_session_has_no_seed_context':all(x not in fresh_prompt for x in ['Estate Protocol','SmartCrowd','Mogul']),'only_imported_records_available':all(x['source_id'].startswith('import:') for x in imported),'fresh_native_succeeded':record['fresh']['return_code']==0,'retrieved_memories_and_skills':{'memories','skills'}<={i['kind'] for i in returned},'all_answer_citations_real':bool(cited) and cited<=labels,'memory_and_skill_citations_used':any(x.startswith('[M') for x in cited) and any(x.startswith('[S') for x in cited),'only_expected_context_tools_used':all(c['server']=='airlock' and c['tool'] in ('privacy_status','get_private_context') for c in calls(record['fresh'])),'no_other_personal_data_tools':all(e.get('item',{}).get('type') in (None,'mcp_tool_call','agent_message','error','reasoning') for phase in ['transfer','fresh'] for e in record[phase]['events']),'exact_wire_receipts_match':returned==read_receipts,'original_personal_library_unchanged':original_identity==current_identity,'filtered_source_checks_passed':all(privacy.values()),'answer_pattern_checks_passed':all(answer_privacy.values())}
            record.update(status='finished',checks=checks,source_privacy=privacy,answer_privacy=answer_privacy,ended=time.time());save()
            report={'run_id':run_id,'model':config.get('model'),'checks':checks,'source_privacy':privacy,'answer_privacy':answer_privacy,'actual_memories_imported':len(seed['memories']),'actual_skills_imported':len(seed['skills']),'fresh_calls':dict(collections.Counter(c['tool'] for c in calls(record['fresh']))),'returned_memories':sum(i['kind']=='memories' for i in returned),'returned_skills':sum(i['kind']=='skills' for i in returned),'answer_review':'pending source-grounding review','isolated_test_library_removed':True,'production_imports_added':0,'limitations':'Actual filtered personal context reaches OpenAI. This targeted test cannot guarantee no unknown disclosures. No Gmail was used in this memory/skill import test.'}
            (ROOT.parent/'outputs/privacy-layer/codex-import-live.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    except Exception as e:
        record['status']='failed';record['failure_type']=type(e).__name__;save();print(json.dumps({'run_id':run_id,'status':'failed','failure_type':type(e).__name__}),flush=True);raise
    finally:
        for server in servers:server.should_exit=True
        for thread in threads:thread.join(timeout=5)

if __name__=='__main__':main()
