"""Requested live Codex test; full results are encrypted, no persistent transcript."""
import argparse,json,os,shutil,subprocess,tempfile,threading,time,tomllib
from pathlib import Path
from .core import EncryptedStore,Gateway
from .sources import LocalSources
from .setup import ROOT

PROMPT='''Run a real personalization and privacy test using only the airlock MCP connection. Do not use any other personal-data source or tool. Today is November 10, 2026, America/New_York. Start by calling privacy_status; if access is unavailable, stop and report the actual error.
Complete these tasks using at most 12 privacy-layer calls:
1. Help me prepare for a hypothetical introductory recruiter conversation: draft a concise, natural 80–120 word introduction, and choose two concrete examples from my actual background. Automatically retrieve the relevant memories and skills from my full library; do not use prior chat knowledge. Apply my saved writing style and identify the skills used. Do not invent achievements, metrics, dates, titles or a current job opportunity. Partner/customer relationships do not establish employment.
2. What can I honestly say about my US visa and travel situation based on my saved context and relevant Gmail correspondence? Automatically select the relevant memories and skills, search live Gmail, and read at least two relevant messages if available. Use general topic searches; do not guess message references. Prefer the most recent relevant evidence, and explain incomplete search coverage. Distinguish historical plans, scheduled travel, document return, visa issuance, actual travel and admission. Never treat one as proof of another. State uncertainty instead of inventing status or current location. No generic legal advice is needed.
3. Report whether tool results exposed credential values, identity numbers, contact/residential details, booking or payment references, card suffixes, masked membership identifiers, legacy export labels, original source identifiers or raw HTML/tracking fragments. Connection-scoped citation aliases are not original source identifiers. If anything appears, report ONLY its category, never repeat or reconstruct values.
Use exact citations from actual results for personal claims, and label suggested wording. Read cited email bodies before drawing conclusions from them. Missing evidence is uncertainty. Never bypass local filtering. Do not save new memories, stage imports, or change email. Return useful personal answers under 650 words, not a plan. Include a compact list of actual successful and failed tool calls.'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-calls',type=int,choices=range(6,13),default=12);options=parser.parse_args()
    prompt=PROMPT.replace('at most 12 privacy-layer calls',f'at most {options.max_calls} privacy-layer calls')
    if options.max_calls<=8:
        prompt+='\nFor this limited-call retest, reserve two calls to read selected email bodies. Use one status call, at most two memory/skill queries and two Gmail searches, then read two relevant messages. Choose the queries and sources yourself; do not skip a source kind to save calls.'
    config=tomllib.loads((Path.home()/'.codex/config.toml').read_text());entry=config.get('mcp_servers',{}).get('airlock')
    if not entry or entry.get('command')!=str(ROOT/'.venv/bin/python') or entry.get('args',[])[:2]!=[str(ROOT/'privacy_layer/stdio.py'),'--token-file']:raise RuntimeError('Connect Codex in the control panel first.')
    token=Path(entry['args'][2]).read_text().strip();sources=LocalSources();store=EncryptedStore(ROOT/'.private/connections.enc',sources.key);sources.connection_store=store
    grant=Gateway(store,sources).authenticate(token)
    if grant['agent']!='codex':raise RuntimeError('Unexpected agent connection.')
    with store.transaction() as data:access=data['grants'][grant['id']]
    if access.get('mode')!='automatic':raise RuntimeError('The installed connection is not using automatic full-library selection.')
    if access['remaining']<options.max_calls:raise RuntimeError('The installed connection does not have enough calls for this test.')
    binary=shutil.which('codex')
    if not binary:raise RuntimeError('Codex CLI unavailable.')
    run_id=str(time.time_ns());started=time.time();events=[];stderr=[]
    with store.transaction() as data:data.setdefault('codex_native_checks',{})[run_id]={'started_at':started,'grant_id':grant['id'],'status':'running'}
    with tempfile.TemporaryDirectory(prefix='private-ai-codex-test-') as workspace:
        args=[binary,'exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only','--json','--color','never','-C',workspace]
        for key in ('model','model_reasoning_effort'):
            if config.get(key):args+=['-c',key+'='+json.dumps(config[key])]
        for key in ('apps','plugins','remote_plugin','plugin_discovery_prefetch','memories','skill_search','skill_mcp_dependency_install','shell_tool','unified_exec','shell_snapshot','code_mode','multi_agent','computer_use','browser_use','browser_use_external','in_app_browser','image_generation','view_image','hooks','workspace_dependencies'):
            args+=['-c',f'features.{key}=false']
        args+=['-c','features.skip_host_skill_discovery=true','-c','web_search="disabled"']
        for key in ('command','args'):args+=['-c','mcp_servers.airlock.'+key+'='+json.dumps(entry[key])]
        args+=['-'];env=dict(os.environ)
        for name in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN'):env.pop(name,None)
        process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        timer=threading.Timer(540,process.kill);timer.start();reader=threading.Thread(target=lambda:stderr.append(process.stderr.read()),daemon=True);reader.start()
        print('Fresh Codex test started with the installed local connection.',flush=True)
        try:
            process.stdin.write(prompt);process.stdin.close()
            for line in process.stdout:
                try:event=json.loads(line)
                except ValueError:continue
                events.append(event);item=event.get('item',{})
                if event.get('type')=='item.completed' and item.get('type')=='mcp_tool_call':print('Completed privacy tool: '+str(item.get('tool','unknown')),flush=True)
                elif event.get('type') in ('turn.completed','turn.failed'):print(event['type'],flush=True)
            process.wait();reader.join(timeout=5)
        finally:timer.cancel()
    ended=time.time();answers=[e.get('item',{}).get('text','') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message'];answer=answers[-1] if answers else ''
    with store.transaction() as data:
        receipts=[x for x in data.get('disclosures',[]) if x['agent']==grant['id'] and x['at']>=started];audit=[x for x in data['audit'] if x['agent']==grant['id'] and x['at']>=started]
        result={'started_at':started,'ended_at':ended,'grant_id':grant['id'],'status':'finished' if process.returncode==0 and answer else 'failed','return_code':process.returncode,'model':config.get('model'),'prompt':prompt,'events':events,'stderr':''.join(stderr),'answer':answer,'receipts':receipts,'audit':audit};data['codex_native_checks'][run_id]=result
    metadata={'run_id':run_id,'status':result['status'],'model':result['model'],'answer_chars':len(answer),'receipt_count':len(receipts),'tools_released':sum(x['status']=='released' for x in audit),'tool_errors':sum(x['status']=='blocked' for x in audit),'exit_code':process.returncode}
    (ROOT.parent/'outputs/privacy-layer/codex-native-latest.json').write_text(json.dumps(metadata,indent=2)+'\n');print(json.dumps(metadata),flush=True)

if __name__=='__main__':main()
