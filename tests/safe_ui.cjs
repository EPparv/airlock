// Real Chromium checks with its DevTools pipe. No external npm dependencies.
// node tests/safe_ui.cjs /path/to/python /path/to/chrome [screenshot-directory]
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'airlock-safe-ui-'));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let service,chrome,n=0,buffer='',session;const pending=new Map(),errors=[];
function send(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++n;const timer=setTimeout(()=>{pending.delete(id);reject(Error('Timed out: '+method));},10000);pending.set(id,{resolve,reject,timer});chrome.stdio[3].write(JSON.stringify({id,method,params,...(sessionId?{sessionId}: {})})+'\0');});}
const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
async function until(expression){for(let i=0;i<80;i++){if(await evaluate(expression))return;await pause(100);}throw Error('UI did not reach: '+expression);}
async function click(id){await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);}
(async()=>{
 const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
 const env={...process.env,PYTHONPATH:root};
 service=spawn(process.argv[2]||'python3',[path.join(__dirname,'safe_ui_fixture.py'),tmp,String(port)],{cwd:root,env,stdio:['ignore','ignore','pipe']});let serverError='';service.stderr.on('data',d=>serverError+=d);
 for(let i=0;i<60;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===59)throw Error(serverError||'Fixture did not start');await pause(100);}
 chrome=spawn(process.argv[3]||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--remote-debugging-pipe','--no-first-run','--no-default-browser-check','--disable-extensions','--disable-background-networking','--user-data-dir='+path.join(tmp,'chrome'),'about:blank'],{stdio:['ignore','ignore','pipe','pipe','pipe']});
 chrome.stdio[4].on('data',data=>{buffer+=data.toString();let at;while((at=buffer.indexOf('\0'))>=0){const raw=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!raw)continue;const message=JSON.parse(raw),p=pending.get(message.id);if(p){pending.delete(message.id);clearTimeout(p.timer);message.error?p.reject(Error(JSON.stringify(message.error))):p.resolve(message.result);}else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);}});
 chrome.on('exit',(code,signal)=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Chrome exited: '+(signal||code)));}pending.clear();});
 const target=await send('Target.createTarget',{url:'about:blank'});session=(await send('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;
 await send('Runtime.enable',{},session);await send('Page.enable',{},session);
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
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
 await click('setupAi');await until("document.querySelectorAll('#connectRecords input[type=checkbox]').length===2");
 assert.equal(await evaluate("document.getElementById('connectAgent').disabled"),true);
 assert.equal(await evaluate("document.getElementById('otherAgents').open"),false);
 assert.equal(await evaluate("document.getElementById('connectionOptions').open"),false);
 assert.equal(await evaluate("document.getElementById('connectRecords').textContent.includes('FICTIONAL_PRIVATE_PERSONAL')"),false);
 await evaluate("document.querySelector('#connectRecords input[type=checkbox]').click()");
 assert.equal(await evaluate("document.getElementById('selectionCount').textContent"),'1 record selected');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true},session);
 assert.equal(await evaluate("document.getElementById('connectDialog').getBoundingClientRect().width<=390"),true);
 if(process.argv[4]){const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},session);fs.writeFileSync(path.join(process.argv[4],'connect-context-mobile.png'),Buffer.from(shot.data,'base64'));}
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false},session);
 await click('connectAgent');await until("document.getElementById('setupDialog').open && document.getElementById('setupMessage').textContent.includes('1 selected')");
 assert.equal(await evaluate("document.getElementById('setupTitle').textContent"),'Open your AI.');
 assert.equal(await evaluate("document.getElementById('connectionState').textContent.includes('Waiting for your AI')"),true);
 const migrated=fs.readFileSync(path.join(tmp,'profile/.codex/config.toml'),'utf8');
 assert.ok(migrated.includes('model = "fixture"') && !migrated.includes('/old-source/') && migrated.includes('mcp_servers.airlock-test'));
 await evaluate("document.querySelector('#setupDialog [data-close]').click()");
 await send('Page.navigate',{url:`http://127.0.0.1:${port}/`},session);
 await until("document.getElementById('isolation')?.textContent.includes('Personal workspace is also open')");
 await click('closePersonal');await until("document.getElementById('isolation').textContent.includes('Personal sources are closed')");
 await click('reset');await until("document.getElementById('progress').textContent==='0 of 7 checks passed'");
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,guided_checks:7,desktop:1280,mobile:390,consent:true,separate_config:true,personal_open_close:true,context_selection:true,old_install_migrated:true,no_false_connection_success:true,reset:true,browser_errors:errors}));
})().catch(e=>{console.error(e.message);process.exitCode=1;}).finally(()=>{if(chrome)chrome.kill();if(service)service.kill();for(const p of pending.values())clearTimeout(p.timer);});
