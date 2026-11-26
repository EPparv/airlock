// Real Chromium checks with its DevTools pipe. No external npm dependencies.
// node tests/safe_ui.cjs /path/to/python /path/to/chrome [screenshot-directory]
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'airlock-safe-ui-'));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let service,chrome,n=0,buffer='',session,browserError='';const pending=new Map(),errors=[];
function send(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++n;const timer=setTimeout(()=>{pending.delete(id);reject(Error('Timed out: '+method+' '+browserError));},sessionId?15000:45000);pending.set(id,{resolve,reject,timer});chrome.stdio[3].write(JSON.stringify({id,method,params,...(sessionId?{sessionId}: {})})+'\0');});}
const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
async function until(expression){for(let i=0;i<80;i++){if(await evaluate(expression))return;await pause(100);}throw Error('UI did not reach: '+expression);}
async function click(id){await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);}
(async()=>{
 const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
 const env={...process.env,PYTHONPATH:root};
 service=spawn(process.argv[2]||'python3',[path.join(__dirname,'safe_ui_fixture.py'),tmp,String(port)],{cwd:root,env,stdio:['ignore','ignore','pipe']});let serverError='';service.stderr.on('data',d=>serverError+=d);
 for(let i=0;i<60;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===59)throw Error(serverError||'Fixture did not start');await pause(100);}
 chrome=spawn(process.argv[3]||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--remote-debugging-pipe','--no-first-run','--no-default-browser-check','--disable-extensions','--disable-background-networking','--disable-dev-shm-usage','--disable-gpu','--user-data-dir='+path.join(tmp,'chrome'),'about:blank'],{stdio:['ignore','ignore','pipe','pipe','pipe']});
 chrome.stderr.on('data',chunk=>{browserError=(browserError+chunk.toString()).slice(-1500);});
 chrome.stdio[4].on('data',data=>{buffer+=data.toString();let at;while((at=buffer.indexOf('\0'))>=0){const raw=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!raw)continue;const message=JSON.parse(raw),p=pending.get(message.id);if(p){pending.delete(message.id);clearTimeout(p.timer);message.error?p.reject(Error(JSON.stringify(message.error))):p.resolve(message.result);}else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);}});
 chrome.on('exit',(code,signal)=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Chrome exited: '+(signal||code)));}pending.clear();});
 let tab;
 for(let i=0;i<100&&!tab;i++){
  const list=await send('Target.getTargets');
  tab=list.targetInfos.find(t=>t.type==='page');
  if(!tab)await pause(100);
 }
 if(!tab)throw Error('Chrome did not open its initial page. '+browserError);
 session=(await send('Target.attachToTarget',{targetId:tab.targetId,flatten:true})).sessionId;
 await send('Runtime.enable',{},session);await send('Page.enable',{},session);
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
 await send('Page.navigate',{url:`http://127.0.0.1:${port}/workspace#fictional-browser-owner`},session);
 const controls=['Connect agent','Context & memory','Privacy & connections'];
 const labels=()=>evaluate("Array.from(document.querySelectorAll('#app.home nav button'),b=>b.textContent)");
 const byText=async(selector,label)=>{
  const expr='Array.from(document.querySelectorAll('+JSON.stringify(selector)+')).find(b=>b.getClientRects().length && (b.getAttribute("aria-label")||b.textContent.trim())==='+JSON.stringify(label)+')';
  await until('!!('+expr+')');return evaluate('('+expr+').click()');
 };
 const btn=label=>byText('#app button',label), sheet=label=>byText('dialog[open] button',label);
 const contains=text=>until('document.getElementById("app")?.innerText.includes('+JSON.stringify(text)+')');
 const titled=title=>until('document.querySelector("#app h1")?.textContent==='+JSON.stringify(title));
 const pickerChoices = ['Codex','Cursor','Claude Desktop','Claude Code','ChatGPT','Meta Muse','Manus','IronClaw','Dot','OpenClaw',
   'VS Code · GitHub Copilot','Gemini CLI','Muse Code','Custom MCP client','Other remote MCP client'];
 const visibleActions = () => evaluate("Array.from(document.querySelectorAll('#app button:not(.back), #app a[href], #app summary')).filter(b=>b.getClientRects().length).map(b=>b.getAttribute('aria-label')||b.textContent.trim())");
 async function matchesPicker() {
   await until("document.querySelector('#app [aria-busy]')===null");
   const labels=await visibleActions();
   assert.equal(labels.includes('Other agents'),false);
   for(const name of pickerChoices) assert.ok(labels.includes(name),'Missing agent: '+name);
 }
 async function noManualHandoff() {
   await until("!document.querySelector('#app [aria-busy]') && [...document.querySelectorAll('#app button')].some(b=>b.textContent==='Manage access' && b.getClientRects().length)");
   assert.equal(await evaluate("!!document.querySelector('dialog[open]') || /Copy test request|Settings saved\.|Check connection/.test(document.querySelector('#app').innerText)"),false);
 }
 const launched=()=>fs.existsSync(path.join(tmp,'launched.jsonl'))?fs.readFileSync(path.join(tmp,'launched.jsonl'),'utf8').trim().split('\n').map(line=>JSON.parse(line).agent):[];
 async function screenshot(name){if(!process.argv[4])return;fs.mkdirSync(process.argv[4],{recursive:true});const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},session);fs.writeFileSync(path.join(process.argv[4],name),Buffer.from(shot.data,'base64'));}
 async function type(label,value,area='dialog[open]'){
  const expr='Array.from(document.querySelectorAll('+JSON.stringify(area+' label')+')).find(x=>x.firstChild.textContent==='+JSON.stringify(label)+')?.querySelector("input,textarea,select")';
  await until('!!('+expr+')');await evaluate('(()=>{const e='+expr+';e.value='+JSON.stringify(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));})()');
 }
 async function home(){for(let i=0;i<8;i++){if(await evaluate("document.querySelectorAll('#app.home nav button').length===3"))return;await until("!!document.querySelector('.back')");await evaluate("document.querySelector('.back').click()");}throw Error('Home unavailable');}
 await until("document.querySelectorAll('nav button').length===3");assert.deepEqual(await labels(),controls);
 assert.ok(!(await evaluate("document.body.innerText.includes('Investor follow-up')")));await screenshot('workspace-desktop.png');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true},session);
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);await screenshot('workspace-mobile.png');
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
 await btn('Connect agent');await matchesPicker();await screenshot('workspace-connect.png');
 assert.equal(await evaluate("api('test-state').then(s=>s.personal_open)"),false);
 assert.deepEqual(launched(),[]);
 await btn('Cursor');await noManualHandoff();await screenshot('workspace-handoff.png');
 assert.equal(await evaluate("document.querySelector('.handoff-status').textContent"),'Waiting for Cursor');
 assert.deepEqual(launched(),['cursor']);
 const firstCursor=await evaluate("api('workspace-state').then(s=>s.agents.find(g=>g.name==='cursor'))");
 assert.equal(firstCursor.scope.records.length,0);assert.equal(firstCursor.last_call,null);assert.equal(firstCursor.last_discovery,null);
 assert.ok(fs.existsSync(path.join(tmp,'profile/.cursor/mcp.json')));
 await home();await btn('Privacy & connections');await btn('App settings');await btn('Lock workspace');await sheet('Lock workspace');
 await until("location.pathname==='/workspace' && document.querySelectorAll('nav button').length===3");
 await btn('Context & memory');await contains('Proposed changes');await screenshot('workspace-context.png');await home();
 await btn('Privacy & connections');await contains('App settings');await screenshot('workspace-privacy.png');
 await btn('Privacy checks');await btn('Example actions');await contains('Investor follow-up');
 await evaluate("Array.from(document.querySelectorAll('.item-button')).find(b=>b.innerText.includes('Investor follow-up')).click()");
 await sheet('Approve example');await contains('Simulated');
 await evaluate("Array.from(document.querySelectorAll('.item-button')).find(b=>b.innerText.includes('Pipeline stage')).click()");
 await sheet('Read filtered fields');await until("document.querySelector('dialog[open] pre')?.innerText.includes('Pilot')");
 assert.ok(!(await evaluate("document.querySelector('dialog pre').innerText.includes('client@example.com')")));await click('close');
 await send('Page.navigate',{url:`http://127.0.0.1:${port}/#fictional-browser-owner`},session);
 await until("document.querySelector('#checks .step') && document.querySelectorAll('#checks .step').length===7");
 assert.equal(await evaluate('location.hash'),'');assert.equal(await evaluate("document.querySelectorAll('.record').length"),3);
 assert.equal(await evaluate("document.getElementById('connect').disabled"),true);
 assert.equal(await evaluate("document.getElementById('personal').disabled"),true);
 if(process.argv[4]){fs.mkdirSync(process.argv[4],{recursive:true});const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},session);fs.writeFileSync(path.join(process.argv[4],'safe-test-desktop.png'),Buffer.from(shot.data,'base64'));}
 await click('nearDemo');await until("document.getElementById('nearSetupLink') && document.getElementById('nearNotes')?.textContent.includes('Maya')");
 await click('nearSetupLink');await until("document.getElementById('status')?.textContent.includes('Add a NEAR key')");
 assert.equal(await evaluate("[...document.styleSheets].some(s=>s.href?.endsWith('/memory.css') && s.cssRules.length>0)"),true);
 assert.equal(await evaluate("document.getElementById('apiKey').type"),'password');
 assert.equal(await evaluate("document.getElementById('probe').disabled"),true);
 await evaluate("document.getElementById('apiKey').value='sk-fictional-browser-test';document.getElementById('keyForm').requestSubmit()");
 await until("document.getElementById('status').textContent.includes('key is present')");
 assert.equal(await evaluate("document.getElementById('apiKey').value"),'');
 assert.equal(await evaluate("document.body.innerText.includes('sk-fictional-browser-test')"),false);
 assert.equal(await evaluate("document.getElementById('probe').disabled"),true);
 await click('clear');await until("document.getElementById('status').textContent.includes('Add a NEAR key')");
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true},session);
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
 await send('Page.navigate',{url:`http://127.0.0.1:${port}/`},session);
 await until("document.querySelectorAll('#checks .step').length===7");
 await evaluate("document.querySelector('#privacyChecks summary').click()");
 assert.equal(await evaluate("document.getElementById('privacyChecks').open"),true);
 for(const [i,id] of ['recall','privacy','correction','propose','approve','persistence','revoke'].entries()){
  await until(`!document.querySelector('[data-step="${id}"] button').disabled && document.querySelector('[data-step="${id}"] button').getClientRects().length>0`);
  await evaluate(`document.querySelector('[data-step="${id}"] button').click()`);
  await until(`document.getElementById('progress').textContent==='${i+1} of 7 checks passed'`);
 }
 assert.equal(await evaluate("document.getElementById('receipts').textContent.includes('FICTIONAL-ORCHID-7429')"),false);
 await click('testConsent');await click('connect');await until("document.getElementById('live').textContent.includes('Waiting for')");
 assert.ok(fs.existsSync(path.join(tmp,'profile/.codex/config.toml')));
 await click('disconnect');await until("document.getElementById('live').textContent.includes('Revoked')");
 await send('Page.reload',{},session);await until("document.getElementById('progress')?.textContent==='7 of 7 checks passed'");
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true},session);
 assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 if(process.argv[4]){const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},session);fs.writeFileSync(path.join(process.argv[4],'safe-test-mobile.png'),Buffer.from(shot.data,'base64'));}
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
 await click('personalConsent');await click('personal');await until("location.pathname==='/personal'&&document.getElementById('serviceStatus')?.textContent==='Running on this Mac'");
 assert.equal(await evaluate('location.hash'),'');
 await click('setupAi');await until("document.querySelectorAll('#connectRecords input[type=checkbox]').length===3");
 assert.equal(await evaluate("document.getElementById('connectAgent').disabled"),true);
 assert.equal(await evaluate("document.getElementById('otherAgents').open"),false);
 assert.equal(await evaluate("document.getElementById('connectionOptions').open"),false);
 assert.equal(await evaluate("document.getElementById('connectRecords').textContent.includes('FICTIONAL_PRIVATE_PERSONAL')"),false);
 await evaluate("document.querySelector('#connectRecords input[type=checkbox]').click()");
 assert.equal(await evaluate("document.getElementById('connectRecords').textContent.includes('Sensitive · private task only')"),true);
 await evaluate("[...document.querySelectorAll('.connect-record')].find(r=>r.textContent.includes('Medical appointment')).querySelector('input').click()");
 assert.equal(await evaluate("document.getElementById('selectionCount').textContent"),'2 records selected');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true},session);
 assert.equal(await evaluate("document.getElementById('connectDialog').getBoundingClientRect().width<=390"),true);
 if(process.argv[4]){const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},session);fs.writeFileSync(path.join(process.argv[4],'connect-context-mobile.png'),Buffer.from(shot.data,'base64'));}
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
 await click('connectAgent');await until("document.getElementById('setupDialog').open && document.getElementById('setupMessage').textContent.includes('2 selected')");
 assert.equal(await evaluate("document.getElementById('setupTitle').textContent"),'Open your AI.');
 assert.equal(await evaluate("document.getElementById('connectionState').textContent.includes('Waiting for your AI')"),true);
 const permissions=await evaluate("api('memory-state').then(s=>s.connections.find(g=>g.agent==='codex'&&!g.revoked).scope)");
 assert.equal(permissions.compute,true);assert.equal(permissions.disclose,true);assert.equal(permissions.records.length,2);assert.equal(permissions.disclose_records.length,1);
 const migrated=fs.readFileSync(path.join(tmp,'profile/.codex/config.toml'),'utf8');
 assert.ok(migrated.includes('model = "fixture"') && !migrated.includes('/old-source/') && migrated.includes('mcp_servers.airlock-test'));
 await evaluate("document.querySelector('#setupDialog [data-close]').click()");
 await send('Page.navigate',{url:`http://127.0.0.1:${port}/`},session);
 await until("document.getElementById('isolation')?.textContent.includes('Personal workspace is also open')");
 await click('closePersonal');await until("document.getElementById('isolation').textContent.includes('Personal sources are closed')");
 await click('reset');await until("document.getElementById('progress').textContent==='0 of 7 checks passed'");
 await send('Page.navigate',{url:`http://127.0.0.1:${port}/workspace`},session);
 await until("document.querySelectorAll('#app.home nav button').length===3");
 await btn('Context & memory');await btn('Memories');await sheet('Unlock workspace');
 await until("location.pathname==='/workspace/personal' && document.querySelector('h1')?.textContent==='Memories'");
 await btn('Add memory');await type('Memory','Follow up about the fictional pilot.');await sheet('Save');await contains('Follow up about the fictional pilot.');
 await btn('Follow up about the fictional pilot.');await btn('Edit');await type('Memory','Follow up about the revised fictional pilot.');await sheet('Save changes');await contains('Follow up about the revised fictional pilot.');
 await btn('Pin to core profile');await contains('Unpin from core profile');await btn('Retire from recall');await contains('Restore to recall');await btn('Restore to recall');await contains('Retire from recall');
 await home();await btn('Connect agent');await matchesPicker();await btn('Cursor');await noManualHandoff();
 await btn('Manage access');await titled('Cursor');
 await byText('summary','Shared records · 0 selected');await type('Follow up about the revised fictional pilot.','excerpt','#app');
 assert.ok(!(await evaluate("document.querySelector('#app').innerText.includes('FICTIONAL_PRIVATE_PERSONAL')")));
 await btn('Save access');await titled('Connected agents');
 const savedCursor=await evaluate("api('workspace-state').then(s=>s.agents.find(g=>g.name==='cursor'&&g.status==='configured'))");
 assert.equal(savedCursor.id,firstCursor.id);assert.equal(savedCursor.scope.records.length,1);assert.equal(savedCursor.scope.disclose_records.length,1);
 await home();await btn('Connect agent');await btn('Cursor');await noManualHandoff();
 const cursorGrants=await evaluate("api('workspace-state').then(s=>s.agents.filter(a=>a.name==='cursor'&&a.status==='configured'))");
 assert.equal(cursorGrants.length,1);assert.deepEqual(cursorGrants[0].scope,savedCursor.scope);
 assert.equal(cursorGrants[0].last_discovery,null);assert.equal(cursorGrants[0].last_call,null);
 assert.deepEqual(launched(),['cursor','cursor','cursor']);
 await home();await btn('Privacy & connections');await btn('Data protection');await type('Always hide these phrases','Sensitive Pilot Code','#app');await btn('Save phrases');await until("document.getElementById('notice').textContent==='Private phrases saved.'");
 await byText('summary','Test redaction');await type('Sample','Write to test@example.org about Sensitive Pilot Code.','#app');await btn('Show filtered result');await until("document.querySelector('#app pre')?.textContent.length>0");
 const redacted=await evaluate("document.querySelector('#app pre').textContent");assert.ok(!redacted.includes('test@example.org')&&!redacted.includes('Sensitive Pilot Code'));
 await type('Input','json','#app');await type('Sample',JSON.stringify({email:'test@example.org',stage:'Pilot',password:'ExampleOnly'}),'#app');await btn('Show filtered result');await until("document.querySelector('#app pre')?.textContent.includes('Pilot')");
 const screened=JSON.parse(await evaluate("document.querySelector('#app pre').textContent"));assert.equal(screened.stage,'Pilot');assert.ok(screened.email.startsWith('[email-'));assert.equal(screened.password,'[withheld]');
 await home();await btn('Privacy & connections');await btn('Apps & data');await btn('Apple Mail');await btn('New email');
 for(const [k,v] of [['Label visible to the agent','Local action'],['Recipients','fictional@example.org'],['Subject','Local review'],['Message','Test only']])await type(k,v);
 await evaluate("Array.from(document.querySelectorAll('dialog label')).find(l=>l.textContent==='Cursor').querySelector('input').click()");await sheet('Save action');await contains('Local action');
 // Open every secondary settings group through its normal parent, including an installed skill and source history.
 async function visit(route,expected){
   await home(); for(const label of route) await btn(label);
   await contains(expected);await until("!document.querySelector('#app [aria-busy]')");
   assert.equal(await evaluate("Array.from(document.querySelectorAll('#app button')).some(b=>b.textContent==='Try again')"),false,route.join(' / '));
 }
 await visit(['Context & memory','Skills','Skill packages'],'Add briefing skill');
 await btn('Add briefing skill');await sheet('Install package');await contains('prepare-local-brief');
 await visit(['Context & memory','Skills','Generated files'],'Files from local skill runs');
 await visit(['Context & memory','Sources & imports'],'Claude Code memories');
 await btn('Shared note history');await contains('No shared notes');
 await visit(['Context & memory','Proposed changes'],'No changes waiting');
 await visit(['Context & memory','Import context'],'Bring context from another agent');
 const chatFixture = [
   {name:'First chat',chat_messages:[{sender:'human',text:'Fictional bicycle repair is Friday.'},
     {sender:'assistant',text:'An unverified model reply.'},{sender:'human',text:'Leave this message out.'}]},
   {name:'Second chat',chat_messages:[{sender:'human',text:'Other conversation.'}]}];
 await type('Import as','chat','#app');await type('Paste context',JSON.stringify(chatFixture),'#app');
 await btn('Review import');await sheet('Review messages');
 await until("document.querySelectorAll('dialog[open] input[type=checkbox]').length===2");
 assert.equal(await evaluate("document.querySelectorAll('dialog[open] input:checked').length"),0);
 assert.ok(!(await evaluate("document.querySelector('dialog[open]').innerText.includes('An unverified model reply.')")));
 await evaluate("document.querySelector('dialog[open] input[type=checkbox]').click()");await sheet('Add selected records');
 await until("document.querySelector('dialog[open]').innerText.includes('1 added')");
 await sheet('View memories');await contains('Fictional bicycle repair is Friday.');
 assert.ok(!(await evaluate("document.querySelector('#app').innerText.includes('Leave this message out.')")));
 await visit(['Context & memory','Import context'],'Bring context from another agent');
 await byText('summary','Bring context from another agent');await btn('Get transfer request');await contains('Copy request');
 await visit(['Privacy & connections','Apps & data','Apple Calendar'],'New event');
 await visit(['Privacy & connections','Apps & data','Files & databases'],'New view');
 await visit(['Privacy & connections','Apps & data','JSON APIs'],'Add endpoint');
 await visit(['Privacy & connections','Apps & data','Gmail search'],'Read-only');
 await visit(['Privacy & connections','Data protection','Filter model requests'],'No model connections');
 await btn('Add model connection');await type('Connection name','Browser fixture');await type('Model installed in Ollama','fictional');
 await sheet('Create connection');await until("document.querySelector('dialog[open] h2')?.textContent==='Configure your client'");
 await sheet('Done');await contains('Browser fixture');
 await evaluate("Array.from(document.querySelectorAll('#app .item-button')).find(b=>b.innerText.includes('Browser fixture')).click()");
 await sheet('Revoke');await contains('No model connections');
 await visit(['Privacy & connections','Approvals & activity','Agent handoffs'],'Agent handoffs');
 await visit(['Context & memory','Reviewed excerpts'],'Reviewed excerpts');
 assert.equal(await evaluate("document.querySelector('.back').textContent"),'Context & memory');
 await visit(['Privacy & connections','Pair iPhone'],'Pair iPhone');
 assert.equal(await evaluate("document.querySelector('.back').textContent"),'Privacy & connections');
 await visit(['Privacy & connections','Cloud agents'],'Cloud agents');
 await btn('ChatGPT');await btn('Create connection');
 await until("document.querySelector('dialog[open] h2')?.textContent==='Connect ChatGPT'");
 await evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('Clipboard unavailable')}}})");
 await sheet('Copy command');await until("document.querySelector('dialog .manual-copy textarea')?.value.includes('tunnel')");
 assert.equal(await evaluate("document.querySelector('dialog h2').textContent"),'Connect ChatGPT');
 await sheet('Done copying');await evaluate("delete navigator.clipboard");
 await sheet('Test this connection');await contains('Waiting for a status call');await byText('summary','Connection help');await contains('HTTP 429');
 await btn('End test');await contains('Unconfirmed');
 await visit(['Privacy & connections','Cloud agents'],'Cloud agents');await btn('ChatGPT');await contains('Waiting for first call');
 await home();await btn('Connect agent');await btn('ChatGPT');await titled('ChatGPT');await contains('Open tunnel setup');
 assert.equal(await evaluate("document.querySelector('#app a.button').href"),'https://chatgpt.com/plugins');
 assert.equal(await evaluate("document.querySelector('.handoff-status').textContent"),'Finish setup');
 assert.equal(await evaluate("!!document.querySelector('dialog[open]')"),false);
 assert.equal(await evaluate("api('remote-state').then(s=>s.connections.filter(g=>g.vendor==='chatgpt' && g.active).length)"),1);
 await visit(['Privacy & connections','Approvals & activity','Private task approvals'],'No private tasks');
 await visit(['Privacy & connections','Approvals & activity','Disclosure receipts'],'Refresh');
 await visit(['Privacy & connections','Approvals & activity','Access log'],'Refresh');
 await visit(['Privacy & connections','Private inference','Local model · Ollama'],'Check local model');
 await visit(['Privacy & connections','Private inference','Confidential inference · NEAR'],'NEAR API key');
 await visit(['Privacy & connections','Privacy checks','Test agent connection'],'Connect fictional workspace');
 await visit(['Privacy & connections','Privacy checks','Private inference walkthrough'],'Run a private task');
 await visit(['Privacy & connections','Connected agents'],'Cursor');
 await home();await btn('Privacy & connections');await btn('App settings');await btn('Lock workspace');await sheet('Lock workspace');
 await until("location.pathname==='/workspace' && document.querySelectorAll('nav button').length===3");assert.equal(await evaluate("api('test-state').then(s=>s.personal_open)"),false);
 if(process.argv[4]){
   const file=path.resolve(process.argv[4],'Airlock-Preview.html');assert.ok(fs.existsSync(file));
   await send('Page.navigate',{url:require('node:url').pathToFileURL(file).href},session);
   await until("document.querySelector('.preview-note') && document.querySelectorAll('nav button').length===3");assert.deepEqual(await labels(),controls);
   await btn('Context & memory');await btn('Import context');await type('Paste context','Remember the demo date.','#app');await btn('Review import');await sheet('Add selected records');await sheet('View memories');await contains('Remember the demo date.');
   await home();await btn('Connect agent');
   assert.equal(await evaluate("document.querySelector('#app a.external-link').href"), 'https://try-airlock.parv223885.chatgpt.site/#connect');
   assert.equal((await visibleActions()).some(label=>pickerChoices.includes(label)),false);
   await btn('Try sample agents');await matchesPicker();await btn('Cursor');await byText('summary','Shared records · 0 selected');await type('Remember the demo date.','excerpt','#app');await btn('Connect Cursor');await sheet('Close');await contains('Cursor');
   await home();await btn('Privacy & connections');await btn('Data protection');await type('Always hide these phrases','Preview code','#app');await btn('Save phrases');await byText('summary','Test redaction');await type('Sample','Preview code at sample@example.org','#app');await btn('Show filtered result');await until("document.querySelector('#app pre')?.textContent.includes('[withheld]')");assert.ok(!(await evaluate("document.querySelector('#app pre').textContent.includes('sample@example.org')")));
   await home();await btn('Privacy & connections');await btn('Approvals & activity');await btn('Device actions');await contains('Investor follow-up');
   await evaluate("Array.from(document.querySelectorAll('.item-button')).find(b=>b.innerText.includes('Investor follow-up')).click()");await sheet('Approve example');await contains('Simulated');
   await home();await btn('Privacy & connections');await btn('App settings');await btn('Reset preview');await sheet('Reset preview');await titled('Airlock');
   assert.equal(await evaluate("api('workspace-state').then(s=>s.records.some(r=>r.text==='Remember the demo date.'))"),false);
   assert.ok(!(await evaluate("performance.getEntriesByType('resource').some(r=>/^https?:/.test(r.name))")));
 }
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,guided_checks:7,desktop:1280,mobile:390,consent:true,separate_config:true,personal_open_close:true,context_selection:true,old_install_migrated:true,no_false_connection_success:true,reset:true,browser_errors:errors}));
})().catch(e=>{console.error(e.message);process.exitCode=1;}).finally(()=>{if(chrome)chrome.kill();if(service)service.kill();for(const p of pending.values())clearTimeout(p.timer);});
