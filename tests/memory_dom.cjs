// Real production frontend and ASGI routes, with explicitly mocked Ollama.
// This checks interactions, not rendered browser layout or live AI output.
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert'),vm=require('vm');
const {execFileSync}=require('child_process');
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom');
const root=path.resolve(__dirname,'..'),state=fs.mkdtempSync(path.join(os.tmpdir(),'airlock-memory-dom-'));
const dom=new JSDOM(fs.readFileSync(path.join(root,'ui/memory.html'),'utf8'),{url:'http://127.0.0.1:8791/memory#test-owner',runScripts:'outside-only'});
const w=dom.window;let outbound=[],calls=[],checks=0;
function check(v,msg){assert(v,msg);checks++;}
w.fetch=async(url,options)=>{calls.push(url);const r=JSON.parse(execFileSync(path.join(root,'.venv/bin/python'),[path.join(__dirname,'memory_api_bridge.py'),state],{cwd:root,env:{...process.env,PYTHONPATH:root},input:JSON.stringify({url,body:JSON.parse(options.body)}),encoding:'utf8',stdio:['pipe','pipe','pipe']}));outbound.push(...r.outbound);return {ok:r.status===200,json:async()=>r.body};};
new vm.Script(fs.readFileSync(path.join(root,'ui/memory.js'),'utf8')).runInContext(dom.getInternalVMContext());
const $=id=>w.document.getElementById(id),tick=()=>new Promise(r=>setImmediate(r));
async function click(target){const b=typeof target==='string'?$(target):target;await b.onclick({currentTarget:b});await tick();}
const button=(text,root=w.document)=>[...root.querySelectorAll('button')].find(b=>b.textContent===text);
(async()=>{
await tick();check($('records').children.length===4,'Loads fictional context');check(!$('walkthrough').hidden,'Shows simulator label');
await click('read');check($('simOutput').textContent.includes('calendar integration'),'Coding context');check(!$('simOutput').textContent.includes('Maya'),'No meeting leak');
$('simAgent').value='ironclaw';await click('read');check($('simOutput').textContent.includes('Maya'),'Writing context');check(!$('simOutput').textContent.includes('calendar integration'),'No engineering leak');
await click('blocked');check($('simOutput').textContent.includes('Blocked locally'),'Never-share denial');check(outbound.length===0,'No provider on denial');
await click('propose');check($('proposalCount').textContent==='1 pending','Stages proposal');check($('records').children.length===4,'Proposal inactive');
await click(button('Accept and save locally'));check($('records').children.length===5,'Owner saves memory');
const coding=$('connections').querySelector('[data-agent=codex]');for(const c of coding.querySelectorAll('input[type=checkbox]'))if(!c.disabled)c.checked=true;
await click(button('Save access',coding));$('simAgent').value='codex';await click('read');check($('simOutput').textContent.includes('follow up after the Thursday walkthrough'),'Other agent reuses approved memory');
$('simAgent').value='ironclaw';await click('request');let card=$('tasks').querySelector('.task');check(!!card,'Stages private task');check(! $('simOutput').textContent.includes('Maya'),'Staging returns no source text');check(button('Approve and generate').disabled,'Consent required');
let c=card.querySelector('input[type=checkbox]');c.checked=true;c.onchange();await click(button('Approve and generate'));
card=$('tasks').querySelector('.task');check(outbound.length===1,'One provider call');check(!outbound[0].includes('FINANCE-ORCHID-9247'),'Restricted value absent');check(JSON.parse(outbound[0]).messages.some(m=>m.content.includes('Maya')),'Approved context reaches mock');check(card.querySelector('textarea').value.startsWith('MOCK AI OUTPUT'),'Generated fixture distinctly labelled');
await click(button('Read result as requesting agent'));check(JSON.parse($('simOutput').textContent).text===null,'Result hidden before second approval');
c=$('tasks').querySelector('input[type=checkbox]');check(button('Release this result').disabled,'Separate result consent');c.checked=true;c.onchange();await click(button('Release this result'));await click(button('Read result as requesting agent'));check(JSON.parse($('simOutput').textContent).text.startsWith('MOCK AI OUTPUT'),'Released result available');
await click('refresh');check($('records').children.length===5,'Saved memory persists');
const writing=$('connections').querySelector('[data-agent=ironclaw]');await click(button('Revoke',writing));await click('read');check($('simOutput').textContent.includes('Blocked locally'),'Revocation enforced');
await click('reset');check($('records').children.length===4,'Reliable reset');check(!$('tasks').querySelector('.task'),'Reset removes tasks');
console.log(JSON.stringify({passed:checks,provider:'mocked Ollama',renderedBrowser:false}));w.close();
})().catch(e=>{console.error(e);process.exit(1)});
