'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const owner=location.hash.slice(1)||sessionStorage.getItem('airlock-test-owner');
if(owner)sessionStorage.setItem('airlock-test-owner',owner);
history.replaceState(null,'',location.pathname);
let state,busy=false;
const steps=[
 ['recall','Recall facts and preferences','Ask for the launch date and the preferred update style.','Check recall'],
 ['privacy','Keep a private note private','Ask for the restricted fictional note and try accessing Gmail. Both boundaries must hold.','Check blocked access'],
 ['correction','Correct an outdated fact','Change the launch date from November 20 to November 27, then read it again.','Save correction and check'],
 ['propose','Keep new memories pending','An agent proposes a fictional rehearsal date. It must remain unavailable until you approve it.','Propose rehearsal note'],
 ['approve','Review before remembering','Approve “Cypress demo rehearsal is November 18.” and share it with test connections.','Approve and share fictional note'],
 ['persistence','Recover saved context','Open a fresh reader of the encrypted test vault and compare the result. For a full restart check, quit and reopen Airlock.','Check saved context'],
 ['revoke','Make disconnected mean disconnected','Revoke the simulated connection, then try another request. Optional AI test connections have their own revoke button below.','Revoke and verify']
];
function notice(text,error=false){$('notice').hidden=!text;$('notice').textContent=text;$('notice').classList.toggle('error',error);}
async function api(action,body={}){if(!owner)throw Error('Open Airlock.app to connect this browser to your test workspace.');const r=await fetch('/api/'+action,{method:'POST',headers:{'Authorization':'Bearer '+owner,'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});let v;try{v=await r.json();}catch{throw Error('Connection closed. Reopen Airlock.app.');}if(!r.ok)throw Error(v.error||'Request blocked. Reopen Airlock.app.');return v;}
function action(fn){return async()=>{if(busy)return;busy=true;try{notice('');if(state)render();await fn();await refresh();}catch(e){notice(e.message,true);}finally{busy=false;if(state)render();}};}
async function refresh(){state=await api('test-state');render();}
function render(){
 $('isolation').textContent=state.personal_open?'Personal workspace is also open. Close personal access below to isolate this session again.':'Personal sources are closed. Your existing library, Gmail and source files are not loaded.';
 $('closePersonal').hidden=!state.personal_open;
 $('personal').disabled=busy||!$('personalConsent').checked;
 $('connect').disabled=busy||!$('testConsent').checked;
 $('reset').disabled=busy;$('disconnect').disabled=busy||!state.live.some(g=>!g.revoked&&g.expires*1000>Date.now());
 $('progress').textContent=`${Object.values(state.checks).filter(x=>x.passed).length} of 7 checks passed`;
 $('records').replaceChildren();for(const r of state.records){const card=node('div',undefined,'record'+(r.private?' private':''));card.append(node('span',r.private?'NEVER SHARE':'ALLOWED FOR TEST','tag'),node('span',r.text));$('records').append(card);}
 const host=$('checks'),open=new Set([...host.querySelectorAll('details[open]')].map(x=>x.dataset.step));host.replaceChildren();
 for(const [i,[id,title,description,label]] of steps.entries()){
  const result=state.checks[id],card=node('article',undefined,'step');card.dataset.step=id;card.append(node('span',result?.passed?'✓':String(i+1),'number'));const content=node('div');content.append(node('h3',title),node('p',description));const b=node('button',label);b.disabled=busy||!!result?.passed||steps.slice(0,i).some(([s])=>!state.checks[s]?.passed);b.onclick=action(async()=>{await api('test-check',{step:id});});content.append(b);
  if(result){content.append(node('p',(result.passed?'Passed · ':'Failed · ')+result.detail,(result.passed?'result':'failed')));if(result.response){const details=node('details');details.dataset.step=id;details.open=open.has(id);details.append(node('summary','Inspect exact response'),node('pre',JSON.stringify(result.response,null,2)));content.append(details);}}
  card.append(content);host.append(card);
 }
 $('live').replaceChildren();for(const g of state.live){$('live').append(node('div',`${g.agent} · ${g.revoked?'Revoked':g.expires*1000<=Date.now()?'Expired':g.last_context_read?'Context requested '+new Date(g.last_context_read*1000).toLocaleTimeString():'Waiting for its first context request'}`,'live'));}
 $('pending').replaceChildren();for(const p of state.pending){const card=node('div',undefined,'pending');card.append(node('strong','Pending fictional memory'),node('p',p.text));const b=node('button','Approve and share this fictional note');b.disabled=busy;b.onclick=action(()=>api('test-check',{step:'approve'}));card.append(b);$('pending').append(card);}
 $('receipts').textContent=state.receipts.length?JSON.stringify(state.receipts,null,2):'No responses yet.';
}
$('testPrompt').textContent='Use only the airlock-test connection for this fictional exercise. Request fresh Airlock context about Cypress, then tell me its launch date using the saved writing preference. Cite the returned records. Ask for the fictional private note too; if it is withheld, say so without guessing. Do not use other tools or my personal memories.';
$('proposalPrompt').textContent='Using only airlock-test, propose this memory with update_shared_context: Cypress demo rehearsal is November 18. Use operation add, kind memories, reference empty and expected_revision 0. Do not claim it is saved before I approve it in Airlock.';
$('copyPrompt').onclick=action(async()=>{await navigator.clipboard.writeText($('testPrompt').textContent);notice('Test prompt copied.');});
$('copyProposal').onclick=action(async()=>{await navigator.clipboard.writeText($('proposalPrompt').textContent);notice('Proposal prompt copied.');});
$('reset').onclick=action(async()=>{await api('test-reset',{approved:true});notice('Fictional test reset. Previous test connections are invalid.');});
$('testConsent').onchange=()=>{if(state)render();};$('personalConsent').onchange=()=>{if(state)render();};
$('connect').onclick=action(async()=>{const r=await api('test-connect',{agent:$('agent').value,approved:$('testConsent').checked});$('testConsent').checked=false;notice(r.message);});
$('disconnect').onclick=action(async()=>{await api('test-disconnect');notice('All test AI connections revoked. Their saved config entries remain, but their requests are blocked.');});
$('personal').onclick=action(async()=>{const r=await api('open-personal',{approved:$('personalConsent').checked});location.assign(r.url);});
$('closePersonal').onclick=action(async()=>{await api('close-personal');sessionStorage.removeItem('private-ai-owner');$('personalConsent').checked=false;notice('Personal access is closed. Already shared facts cannot be recalled.');});
async function poll(){if(!document.hidden&&!busy){try{await refresh();}catch(e){notice(e.message,true);}}setTimeout(poll,4000);}
poll();
