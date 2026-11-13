// Real frontend + real ASGI routes. JSDOM is a DOM test, not a browser render.
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert');
const {execFileSync}=require('child_process');
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom');
const root=path.resolve(__dirname,'..');const state=fs.mkdtempSync(path.join(os.tmpdir(),'airlock-near-dom-'));
const dom=new JSDOM(fs.readFileSync(path.join(root,'ui/index.html'),'utf8'),{url:'http://127.0.0.1:8795/#fixture-owner',runScripts:'outside-only'});
const w=dom.window;w.scrollTo=()=>{};let lastPayload,oldServer=false;const calls=[],outbound=[];
w.fetch=async(url,options)=>{
 const body=JSON.parse(options.body);calls.push({url,body});
 const r=JSON.parse(execFileSync(path.join(root,'.venv/bin/python'),[path.join(__dirname,'near_api_bridge.py'),state],{
  cwd:root,env:{...process.env,PYTHONPATH:root,AIRLOCK_DOM_MOCK_LOCAL:'1'},input:JSON.stringify({url,body}),encoding:'utf8',stdio:['pipe','pipe','pipe']}));
 outbound.push(...r.outbound);
 if(oldServer&&url==='/api/near-state')delete r.body.workflow_version;
 if(url==='/api/near-review'&&!r.body.blocked)lastPayload=r.body;
 return {ok:r.status===200,json:async()=>r.body};
};
// Load every production script, in the same order as index.html.
for(const script of w.document.querySelectorAll('script[src]')){
 const file=path.basename(script.getAttribute('src'));
 new (require('vm').Script)(fs.readFileSync(path.join(root,'ui',file),'utf8'),{filename:file}).runInContext(dom.getInternalVMContext());
}
const $=id=>w.document.getElementById(id);
const click=async id=>{await $(id).onclick({currentTarget:$(id),type:'click'});};
function capture(name){
 if(!process.env.CAPTURE_DIR)return;
 const copy=w.document.documentElement.cloneNode(true);
 copy.querySelectorAll('script,link').forEach(n=>n.remove());
 for(const select of w.document.querySelectorAll('select[id]')){for(const option of copy.querySelector('#'+select.id).options)option.toggleAttribute('selected',option.value===select.value);}
 const style=w.document.createElement('style');style.textContent=['ui.css','near.css'].map(f=>fs.readFileSync(path.join(root,'ui',f),'utf8')).join('\n');copy.querySelector('head').append(style);
 const banner=w.document.createElement('p');banner.textContent='OFFLINE REHEARSAL CAPTURE · real app DOM and ASGI routes · scripted output · no live NEAR inference';banner.style.cssText='position:sticky;top:0;z-index:100;background:#382c21;color:#ffdcad;padding:12px;margin:0;text-align:center';copy.querySelector('body').prepend(banner);
 copy.querySelectorAll('img').forEach(n=>n.remove());
 fs.mkdirSync(process.env.CAPTURE_DIR,{recursive:true});fs.writeFileSync(path.join(process.env.CAPTURE_DIR,name+'.html'),'<!doctype html>\n'+copy.outerHTML);
}
(async()=>{
 await w.airlockReady;await w.nearReady;
 await new Promise(resolve=>setImmediate(resolve));
 assert($('notice').hidden,`Startup error: ${$('notice').textContent}`);
 assert(!$('page-near').hidden,'Standalone demo must open the founder workflow');
 assert($('onboarding').hidden,'Personal onboarding must be hidden');
 assert.strictEqual($('nearMode').value,'local');
 assert($('nearNotes').children.length===2,'Fictional notes load on first launch');
 assert(!calls.some(c=>c.url==='/api/private-phrases'),'Demo must not request personal settings');
 assert([...w.document.querySelectorAll('nav [data-page]')].filter(n=>!n.hidden).every(n=>n.dataset.page==='near'));
 await click('nearReset');await click('nearGrant');
 $('nearMode').value='rehearsal';$('nearMode').onchange();await click('nearPrepare');
 assert.strictEqual($('nearPayload').textContent,lastPayload.payload);
 assert.strictEqual($('nearSystem').textContent,JSON.parse(lastPayload.payload).messages[0].content);
 assert.strictEqual($('nearContext').textContent,JSON.parse(lastPayload.payload).messages[1].content);
 assert(!$('nearPayload').textContent.includes('ORCHID-NEVER-SHARE-83Q'));
 capture('01-review');
 assert($('nearSend').disabled);
 const before=calls.length;await click('nearSend');assert.strictEqual(calls.length,before);
 $('nearConsent').checked=true;$('nearConsent').onchange();await click('nearSend');
 assert(!$('nearResult').hidden);assert($('nearResultMode').textContent.includes('SCRIPTED'));
 assert($('nearDraft').textContent.includes('Thursday'));
 assert($('nearChecks').textContent.includes('not performed'));
 capture('02-draft');
 await click('nearRestricted');assert($('nearBlocked').textContent.includes('never share'));assert($('nearReview').hidden);
 capture('03-blocked');
 await click('nearPrepare');await click('nearRevoke');assert($('nearReview').hidden);
 await click('nearPrepare');assert($('nearBlocked').textContent.includes('revoked'));
 await click('nearReset');assert($('nearResult').hidden);
 $('nearMode').value='local';$('nearMode').onchange();
 await click('nearCheck');assert($('nearReadiness').textContent.includes('No note content'));
 await click('nearGrant');await click('nearPrepare');
 const shown=$('nearPayload').textContent;
 assert.strictEqual($('nearContext').textContent,JSON.parse(shown).messages[1].content);
 $('nearConsent').checked=true;$('nearConsent').onchange();await click('nearSend');
 assert($('nearDraft').textContent.includes('Mocked Ollama'));
 assert($('nearResultMode').textContent.includes('LOCAL AI'));
 assert(!$('nearResultMode').textContent.includes('NEAR'));
 assert($('nearLatency').textContent.includes('0 cloud inference calls'));
 assert.strictEqual(outbound.find(r=>r.url.endsWith('/api/chat')).body,shown);
 const beforeBlocked=outbound.length;await click('nearRestricted');assert.strictEqual(outbound.length,beforeBlocked);
 $('nearMode').value='live';$('nearMode').onchange();await click('nearPrepare');
 $('nearConsent').checked=true;$('nearConsent').onchange();
 assert($('nearSend').disabled,'Unconfigured NEAR must stay blocked');
 assert(!$('nearSetup').hidden);
 oldServer=true;await w.document.querySelector('[data-page="near"]').onclick({});
 assert($('nearBlocked').textContent.includes('older demo server'));
 assert($('nearPrepare').disabled);
 console.log(JSON.stringify({status:'passed',checks:35,transport:'real ASGI in process; all production frontend scripts in JSDOM',provider:'scripted rehearsal + explicitly mocked Ollama HTTP',api_calls:calls.length}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{w.close();fs.rmSync(state,{recursive:true,force:true});});
