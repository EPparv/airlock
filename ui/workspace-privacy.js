'use strict';

addPage('privacy','Privacy & connections','home',host=>{
  const m=el('div',null,'menu');host.append(m);
  for(const [label,key] of [['Connected agents','connections'],['Data protection','protection'],['Apps & data','apps'],['Approvals & activity','activity'],['Private inference','inference'],['Privacy checks','checks'],['App settings','settings']])choose(m,label,key);
},false);
addPage('protection','Data protection','privacy',async host=>{
  const [phrases,ws]=await Promise.all([api('private-phrases'),api('workspace-state')]);
  const f=el('div',null,'form');host.append(f);
  const text=field(f,'Always hide these phrases',el('textarea'));text.value=phrases.phrases.join('\n');text.placeholder='One phrase per line';
  formAction(f,'Save phrases',async()=>{await api('private-phrases',{phrases:text.value.split('\n').map(x=>x.trim()).filter(Boolean)});flash('Private phrases saved.');});
  const inspect=details(host,'Test redaction'),test=el('div',null,'form');inspect.append(test);
  note(test,'See how Airlock filters text or selected fields before returning them to an agent.');
  const kind=field(test,'Input',select([['text','Text'],['json','JSON object']]));
  const conn=field(test,'Connection',select([['','Temporary example'],...ws.agents.filter(active).map(a=>[a.id,names[a.name]||a.name])]));
  const raw=field(test,'Sample',el('textarea')),out=el('div');raw.placeholder='Paste a sample to check locally';
  test.append(button('Show filtered result',async()=>{const v=await api('workspace-screen',{kind:kind.value,identifier:conn.value,text:raw.value});out.replaceChildren(el('pre',typeof v.result==='string'?v.result:JSON.stringify(v.result,null,2)));}),out);
  const views=section(host,'Field access');choose(views,'File and database views','views');choose(views,'API endpoints','apis');
  note(host,'Airlock filters its tool responses locally. Free text can still identify someone by context.');
});
addPage('apps','Apps & data','privacy',host=>{
  const m=el('div',null,'menu');host.append(m);
  for(const [label,key] of [['Apple Mail','mail'],['Apple Calendar','calendar'],['Gmail search','gmail'],['Files & databases','views'],['JSON APIs','apis']])choose(m,label,key);
},false);
addPage('gmail','Gmail search','apps',async host=>{
  const g=await api('gmail-state');host.append(facts([['Account',g.account||'No account linked'],['Access','Read-only'],['Status',g.sign_in.replaceAll('_',' ')]]));
  if(g.error)note(host,g.error);
  if(!g.configured){note(host,'Google sign-in has not been configured for this installation. Gmail accounts already in Apple Mail can use the Mail connector.');choose(host,'Apple Mail','mail');return;}
  host.append(button(g.account?'Reconnect Gmail':'Connect Gmail',async()=>{if(preview)return nativeOnly('Connect Gmail');const r=await api('gmail-connect');const u=new URL(r.url);if(u.protocol!=='https:'||u.hostname!=='accounts.google.com')throw Error('Google returned an unexpected sign-in address.');
    const f=modal('Sign in to Gmail');const a=el('a','Continue to Google');a.href=u.href;a.rel='noreferrer noopener';a.target='_blank';f.append(a,button('Check connection',async()=>{const result=await api('gmail-check');close();await refresh();flash(result.message);}));}));
  host.append(button('Check connection',async()=>{if(preview)return nativeOnly('Check Gmail');const r=await api('gmail-check');await refresh();flash(r.message);}));
  choose(host,'Share a reviewed Gmail excerpt','excerpts');
});
addPage('activity','Approvals & activity','privacy',host=>{
  const m=el('div',null,'menu');host.append(m);
  for(const [label,key] of [['Device actions','actions'],['Private task approvals','tasks'],['Disclosure receipts','receipts'],['Access log','audit']])choose(m,label,key);
});
addPage('receipts','Disclosure receipts','activity',async(host,opt,bar)=>{
  bar.append(button('Refresh',refresh));const ws=await api('workspace-state'),list=el('div',null,'list');host.append(list);
  if(!ws.receipts.length)empty(list,'Responses appear here after an agent uses Airlock.');
  for(const r of ws.receipts){const box=details(list,agentName(r.agent,ws)+' · '+r.tool);note(box,when(r.at));box.append(el('pre',JSON.stringify(r.response,null,2)));}
});
addPage('audit','Access log','activity',async(host,opt,bar)=>{
  bar.append(button('Refresh',refresh));const v=await api('audit'),ws=await api('workspace-state'),list=el('div',null,'list');host.append(list);
  if(!v.events.length)empty(list,'No tool access recorded.');
  for(const e of [...v.events].reverse()){const d=details(list,e.tool+' · '+e.status);note(d,agentName(e.agent,ws)+' · '+when(e.at));d.append(el('pre',JSON.stringify(e,null,2)));}
});
addPage('inference','Private inference','privacy',host=>{
  const m=el('div',null,'menu');host.append(m);choose(m,'Local model · Ollama','ollama');choose(m,'Confidential inference · NEAR','near');choose(m,'Private task approvals','tasks');
});
addPage('ollama','Local model','inference',host=>{
  note(host,'Airlock uses the Ollama model installed on this Mac.');const out=el('div');
  host.append(button('Check local model',async()=>{if(preview)return nativeOnly('Check local model');const r=await api('memory-local-check');out.replaceChildren(el('p',r.message,'hint'));}),out);
});
addPage('near','NEAR settings','inference',async(host,opt)=>{
  if(!opt.walk&&!preview&&!personal){unlock('near');return;}
  const call=opt.walk?testAPI:api;const s=await call('near-setup-status');const f=el('div',null,'form');host.append(f);
  if(opt.walk)note(f,'These settings apply to the isolated walkthrough.');
  f.append(facts([['Model',s.model],['Session key',s.key_present?'Present':'None'],['Verifier',s.sdk.message],['Deployment',s.deployment_approved?'Approved':'Awaiting approval']]));
  const key=field(f,'NEAR API key',input('password'));key.autocomplete='off';
  f.append(button('Use key for this session',async()=>{if(preview)return nativeOnly('NEAR credentials');const api_key=key.value;key.value='';await call('near-setup-key',{api_key});await refresh();}));
  if(s.key_present)f.append(button('Clear key and approvals',async()=>{await call('near-setup-clear');await refresh();},'plain'));
  if(!s.sdk.ready)f.append(button('Install verifier',()=>confirmAction('Install NEAR verifier?','Airlock will download the pinned verification library.','Install',async()=>{if(preview)return nativeOnly('Install verifier');await call('near-setup-install',{approved:true});await refresh();})));
  if(s.key_present&&s.sdk.ready)f.append(button('Verify deployment',async()=>{await call('near-setup-discover');await refresh();}));
  if(s.deployment_review){for(const d of s.deployment_review.deployments)details(f,d.kind+' · '+d.sha256,el('pre',d.configuration));
    formAction(f,'Approve displayed deployment',async()=>{await call('near-setup-approve',{review_id:s.deployment_review.id,approved:true});await refresh();});}
  if(s.ready)f.append(button('Test inference',()=>confirmAction('Run a billed test?',s.probe_prompt,'Run test',async()=>{if(preview)return nativeOnly('NEAR inference');await call('near-setup-probe',{approved:true});await refresh();})));
  if(s.last_test)details(f,'Last test',el('pre',JSON.stringify(s.last_test,null,2)));
},false);
addPage('tasks','Private task approvals','activity',async(host,opt,bar)=>{
  bar.append(button('Refresh',refresh));const s=await api('memory-state'),list=el('div',null,'list');host.append(list);
  if(!s.tasks.length)empty(list,'No private tasks waiting for review.');
  for(const t of [...s.tasks].reverse())item(list,t.instruction,(names[t.agent]||t.agent)+' · '+t.status,()=>taskSheet(t));
});
function taskSheet(t){
  const f=modal('Private task');f.append(el('p',t.instruction),facts([['Destination',t.destination],['Status',t.status]]));details(f,'Exact request',el('pre',t.payload));
  if(t.status==='awaiting approval')formAction(f,'Review generation',()=>confirmAction('Approve generation?',t.destination,'Generate',async()=>{await api('memory-send',{task_id:t.id,approved:true,payload_hash:t.sha256});await refresh();}));
  if(t.result){const out=field(f,'Result to release',el('textarea'));out.value=t.release??t.result.screening?.text??t.result.draft;
    out.readOnly=t.status!=='result held locally';details(f,'Provider checks',el('pre',JSON.stringify(t.result.checks,null,2)));
    if(!out.readOnly){f.append(button('Screen edits locally',async()=>{const r=await api('memory-screen',{task_id:t.id,text:out.value,result_hash:t.result_hash});out.value=r.text;flash(r.blocked?'No releasable text remains.':'Screened locally.');}));
      f.append(button('Review release',()=>{const value=out.value;const confirm=modal('Release this exact text?');confirm.append(el('pre',value));formAction(confirm,'Release to requesting agent',async()=>{await api('memory-release',{task_id:t.id,approved:true,text:value,result_hash:t.result_hash});close();await refresh();});}));}}
  if(t.error)note(f,t.error);f.append(button('Remove task',()=>confirmAction('Remove task?',t.instruction,'Remove',async()=>{await api('memory-forget',{task_id:t.id});await refresh();},true),'danger'));
}
const checks=[['recall','Read the selected memory'],['privacy','Withhold a private record'],['correction','Apply a correction'],['propose','Propose a memory'],['approve','Approve the proposal'],['persistence','Reopen the vault'],['revoke','Revoke access']];
addPage('checks','Privacy checks','privacy',async host=>{
  if(!testToken()&&!preview){empty(host,'Open the regular Mac app to use its isolated test workspace.');return;}
  const s=await testAPI('test-state');const list=el('div',null,'list');host.append(list);note(host,'These checks use fictional records.');
  for(const [id,label] of checks){const r=s.checks[id];row(list,label,async()=>{const v=await testAPI('test-check',{step:id});await refresh();const f=modal(label);note(f,v.detail);if(v.response)details(f,'Agent response',el('pre',JSON.stringify(v.response,null,2)));},r?r.passed?'Passed':'Review':'');}
  const extra=section(host,'Diagnostics');choose(extra,'Example actions','examples');choose(extra,'Test agent connection','testagent');choose(extra,'Private inference walkthrough','walkthrough');
  if(personal||preview)row(extra,'Latest verification results',async()=>{const [a,b]=await Promise.all([api('evaluation'),api('prepared-review')]);const f=modal('Verification results');details(f,'Tested answer',el('pre',JSON.stringify(a,null,2)));details(f,'Prepared review',el('pre',JSON.stringify(b,null,2)));});
  row(extra,'Reset fictional checks',()=>confirmAction('Reset fictional checks?','This clears the test vault and revokes its example connections.','Reset checks',async()=>{await testAPI('test-reset',{approved:true});await refresh();}));
},false);
addPage('testagent','Test agent connection','checks',async host=>{
  const s=await testAPI('test-state'),f=el('div',null,'form');host.append(f);details(f,'Fictional library',el('pre',s.records.map(r=>r.text+(r.private?' (device only)':'')).join('\n\n')));
  const agent=field(f,'Agent',select(localAgents.map(k=>[k,names[k]])));formAction(f,'Connect fictional workspace',async()=>{if(preview)return nativeOnly('Test an installed agent');await testAPI('test-connect',{agent:agent.value,approved:true});await refresh();});
  f.append(button('Copy test request',()=>copyText('Use only airlock-test. Read the Cypress launch date and my writing preference. Cite the selected records.')),button('Copy proposal request',()=>copyText('Using only airlock-test, propose a memory: Cypress product rehearsal is November 18. Use update_shared_context and wait for owner approval.')));
  if(s.live.length){for(const c of s.live)note(f,(names[c.agent]||c.agent)+' · '+(c.revoked?'Revoked':c.last_context_read?'Has read context':'Awaiting first request'));f.append(button('Revoke test connections',async()=>{await testAPI('test-disconnect');await refresh();},'danger'));}
  if(s.receipts.length)details(f,'Test responses',el('pre',JSON.stringify(s.receipts,null,2)));
},false);
addPage('walkthrough','Inference walkthrough','checks',async host=>{
  const s=await testAPI('near-state'),f=el('div',null,'form');host.append(f);note(f,'Run a private task with fictional meeting notes.');
  if(!s.loaded){formAction(f,'Load fictional notes',async()=>{await testAPI('near-reset');await refresh();});return;}
  for(const r of Object.values(s.records))details(f,r.title+(r.never_share?' · device only':''),el('p',r.text));
  const access=s.grant&&!s.grant.revoked&&s.grant.expires*1000>Date.now();
  f.append(button(access?'Revoke task access':'Allow meeting notes',async()=>{await testAPI(access?'near-revoke':'near-grant');await refresh();}));
  const mode=field(f,'Destination',select([['rehearsal','Scripted example'],['local','Local Ollama'],['live','NEAR confidential inference']]));
  if(access){async function review(ids){if(preview&&mode.value!=='rehearsal')return nativeOnly('Private inference');const v=await testAPI('near-review',{ids,mode:mode.value});if(v.blocked){const d=modal('Request blocked');note(d,v.reason);return;}
      const d=modal('Review request');note(d,v.destination);d.append(el('pre',v.payload));formAction(d,'Approve and run',async()=>{const result=await testAPI('near-send',{approval_id:v.approval_id,approved:true,payload_hash:v.sha256});close();await refresh();flash(result.mode==='rehearsal'?'Scripted example complete.':'Task completed.');});}
    f.append(button('Review request',()=>review(['meeting-notes'])),button('Test restricted record',()=>review(['meeting-notes','financial-note'])));
  }
  f.append(button('Walkthrough NEAR settings',()=>go('near',{walk:true})));
  if(s.result){details(f,'Generated result',el('pre',s.result.draft),true);details(f,'Verification',el('pre',JSON.stringify(s.result.checks,null,2)));}
  f.append(button('Reset walkthrough',()=>confirmAction('Reset walkthrough?','Clear its fictional notes, access, and results.','Reset',async()=>{await testAPI('near-reset');await refresh();}),'plain'));
},false);
addPage('settings','App settings','privacy',async host=>{
  const native=window.webkit?.messageHandlers?.airlockSettings;
  host.append(facts([['Version','0.9.0'],['Workspace',preview?'Preview':personal?'Unlocked':'Locked']]));
  if(personal&&testToken())host.append(button('Lock workspace',lockWorkspace));
  if(!personal&&!preview)host.append(button('Unlock workspace',()=>unlock('settings')));
  if(native){const prefs=await native.postMessage({action:'status'});const box=section(host,'Updates'),auto=check(box,'Check for updates on launch',prefs.automatic);
    auto.onchange=run(async()=>{await native.postMessage({action:'automatic',enabled:auto.checked});});
    box.append(button('Check for updates',()=>native.postMessage({action:'check'})));}
  else note(host,preview?'Updates are managed in the Mac app.':'Use Airlock’s menu on your Mac to check for updates.');
  if(preview)host.append(button('Reset preview',()=>confirmAction('Reset preview?','Remove changes made in this tab.','Reset preview',async()=>{await api('preview-reset');await go('home');})));
},false);
