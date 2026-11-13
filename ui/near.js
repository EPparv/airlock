'use strict';
// All note/model output is rendered as text. Only static UI markup uses HTML.
let nearReview=null,nearState=null,nearBusy=false,nearEpoch=0,nearDemoOpened=false;
const nearPage=el('section',undefined,'page');nearPage.id='page-near';nearPage.hidden=true;
nearPage.innerHTML=`
<div class="near-heading"><div><p class="eyebrow">AIRLOCK · FOUNDER DEMO</p><h1>A follow-up, without oversharing.</h1><p class="lede">Give your assistant the meeting notes. Keep the financials private.</p></div><button id="nearReset" class="text-button">Reset demo</button></div>
<div class="near-modebar"><label for="nearMode">Generate with</label><select id="nearMode"><option value="local">Local AI · Ollama on this Mac</option><option value="live">NEAR · confidential inference</option><option value="rehearsal">Scripted backup · no AI call</option></select><span id="nearModeBadge" class="pill"></span><button id="nearCheck" class="text-button">Check connection</button></div>
<p id="nearReadiness" class="near-status" role="status"></p>
<details id="nearSetup" class="near-details" hidden><summary>What NEAR needs before sending</summary><ul id="nearMissing"></ul><p>Create an API key at <a href="https://cloud.near.ai" target="_blank" rel="noreferrer">NEAR AI Cloud</a>, then follow NEAR_DEMO.md for the verifier and reviewed deployment hashes. Keep your key out of chats and recordings.</p></details>
<p class="near-fiction">All notes are fictional. This workspace has no access to your real memories or email.</p>
<div class="near-workspace">
<section class="near-panel near-context"><div class="near-step"><span>1</span><h2>Choose what AI can use</h2></div><div id="nearNotes" class="near-notes"></div><button id="nearGrant" class="primary">Allow meeting notes for 10 minutes</button><div class="near-access"><p id="nearAccess"></p><button id="nearRevoke" class="text-button">Revoke access</button></div></section>
<div class="near-main">
<section class="near-panel"><div class="near-step"><span>2</span><h2>Review before generating</h2></div><p>Write a concise investor follow-up from Alex to Maya.</p><div class="near-route"><div><small>DESTINATION</small><p id="nearDestination"></p></div><div><small>MODEL</small><p id="nearModel"></p></div></div><button id="nearPrepare" class="primary">Review request</button>
<div id="nearReview" hidden><p id="nearReviewDest" class="near-approved"></p><div class="near-preview"><h3>Instructions to the assistant</h3><pre id="nearSystem"></pre><h3>Task & selected context</h3><pre id="nearContext"></pre></div><p class="near-private">Excluded: financial note. It stays outside the request.</p><details class="near-details"><summary>Exact JSON request & approval details</summary><pre id="nearPayload" class="near-payload"></pre><p id="nearHash" class="fine"></p><p class="fine">This is the exact application-level body. Transport headers contain routing and authentication, with no additional local context.</p></details><label class="check near-consent"><input id="nearConsent" type="checkbox"><span id="nearConsentLabel"></span></label><button id="nearSend" class="primary" disabled>Approve & generate</button></div>
</section>
<div id="nearBlocked" class="near-feedback" role="status" aria-live="polite" hidden></div>
<section id="nearResult" class="near-panel" hidden><div class="near-output-heading"><div><p id="nearResultMode" class="eyebrow"></p><div class="near-step"><span>3</span><h2>Your follow-up draft</h2></div></div><button id="nearCopy">Copy draft</button></div><pre id="nearDraft" class="near-draft"></pre><p id="nearLatency" class="fine"></p><p class="fine">Review before using. No email has been sent.</p><details class="near-details"><summary>Privacy & verification checks</summary><div id="nearChecks"></div><p id="nearGuarantee" class="fine"></p></details></section>
<section class="near-boundary"><div><h3>Test the boundary</h3><p>Ask the assistant to include the financial note.</p></div><button id="nearRestricted">Try restricted request</button></section>
</div></div>`;
document.querySelector('main').insertBefore(nearPage,document.querySelector('main footer'));
const nearNav=el('button','↗  Founder demo','nav');nearNav.dataset.page='near';document.querySelector('nav').append(nearNav);
const nearLabels={local:'LOCAL AI · OLLAMA',live:'NEAR · VERIFIED MODEL SIGNATURE',rehearsal:'SCRIPTED BACKUP · NO AI CALL'};
function nearActive(){return !!nearState?.grant&&!nearState.grant.revoked&&nearState.grant.expires*1000>Date.now();}
function nearButtons(){
 const active=nearActive(),loaded=!!nearState?.loaded;
 $('nearGrant').disabled=!loaded||active||nearBusy;
 $('nearRevoke').disabled=!active;
 $('nearPrepare').disabled=!active||nearBusy;
 $('nearRestricted').disabled=!loaded||nearBusy;
 $('nearMode').disabled=nearBusy;
 $('nearSend').disabled=nearBusy||!nearReview||!$('nearConsent').checked||!active||(nearReview.mode==='live'&&!nearState?.readiness.ready);
}
function nearMessage(text,kind='error'){$('nearBlocked').hidden=!text;$('nearBlocked').textContent=text;$('nearBlocked').dataset.kind=kind;}
function clearNearReview(){nearReview=null;$('nearReview').hidden=true;$('nearConsent').checked=false;nearButtons();}
function nearAction(fn){return async event=>{event?.preventDefault?.();try{notice('');await fn();}catch(error){nearMessage(error.message);}finally{nearButtons();}};}
function nearRoute(){
 if(!nearState)return;
 const mode=$('nearMode').value,s=nearState;
 $('nearDestination').textContent=mode==='local'?'This Mac · 127.0.0.1:11434':mode==='live'?'NEAR AI Cloud':'This page · scripted backup';
 $('nearModel').textContent=mode==='local'?s.local_model:mode==='live'?s.model:'No model is called';
 $('nearModeBadge').textContent=mode==='local'?'Local inference':mode==='live'?'Verification required':'Scripted output';
 $('nearReadiness').textContent=mode==='local'?'Uses your installed Ollama model. Checks local weights before generating; no cloud fallback.':mode==='live'?(s.readiness.ready?'Setup present. Required verification must pass before your notes are sent.':'NEAR sending is blocked until setup is complete.'):'Shows a fixed sample draft. Permission checks still run. This mode does not call AI.';
 $('nearCheck').hidden=mode==='rehearsal';$('nearCheck').textContent=mode==='local'?'Check local AI':'Check NEAR setup';
 $('nearSetup').hidden=mode!=='live'||s.readiness.ready;
 $('nearMissing').replaceChildren();for(const item of s.readiness.missing)$('nearMissing').append(el('li',item));
 nearButtons();
}
function nearResult(result){
 $('nearResult').hidden=!result;if(!result)return;
 $('nearResultMode').textContent=nearLabels[result.mode];$('nearDraft').textContent=result.draft;
 const duration=result.elapsed_ms<1000?`${result.elapsed_ms} ms`:`${(result.elapsed_ms/1000).toFixed(1)} s`;
 $('nearLatency').textContent=`${duration} observed · ${result.inference_calls} ${result.mode==='local'?'local AI':'inference'} call${result.inference_calls===1?'':'s'} · ${result.cloud_inference_calls||0} cloud inference calls`;
 $('nearChecks').replaceChildren();for(const [key,value]of Object.entries(result.checks))$('nearChecks').append(el('p',`${key.replaceAll('_',' ')}: ${value}`));
 $('nearGuarantee').textContent=result.mode==='live'?'Gateway, model and response signature are separate checks. The official SDK encrypts approved message fields to an attested model key. Model and routing metadata remain visible.':result.mode==='local'?'This is local Ollama inference, not NEAR confidential inference. The local daemon and weights are trusted; they are not remotely attested.':'No gateway, model or response-signature verification was performed. The draft is a fixed sample.';
 $('nearCopy').textContent='Copy draft';
}
async function loadNear(){
 const s=await api('near-state');
 if(s.workflow_version!==2){nearState=null;nearButtons();throw Error('This tab is connected to an older demo server. Launch Run-NEAR-Demo.command again and use the new tab.');}
 nearState=s;
 $('nearReset').textContent=s.loaded?'Reset demo':'Load demo';$('nearNotes').replaceChildren();
 for(const [id,n]of Object.entries(s.records)){
  const card=el('article',undefined,'near-note'+(n.never_share?' near-locked':''));
  card.append(el('p',n.never_share?'NEVER SHARE':'MEETING NOTES','eyebrow'),el('h3',n.title),el('p',n.text));
  card.append(el('span',n.never_share?'Stays local':nearActive()?'Allowed for this task':'Waiting for your permission','pill'));
  $('nearNotes').append(card);
 }
 $('nearAccess').textContent=nearActive()?'Access expires at '+new Date(s.grant.expires*1000).toLocaleTimeString()+'.':'Only meeting notes can be approved for this task.';
 nearRoute();nearResult(s.result?.mode===$('nearMode').value?s.result:null);
}
nearNav.onclick=nearAction(async()=>{switchPage('near');$('pageTitle').textContent='Founder demo';await loadNear();});
$('nearReset').onclick=nearAction(async()=>{nearEpoch++;clearNearReview();nearMessage('');await api('near-reset');await loadNear();});
$('nearGrant').onclick=nearAction(async()=>{nearEpoch++;clearNearReview();nearMessage('');await api('near-grant');await loadNear();});
$('nearRevoke').onclick=nearAction(async()=>{nearEpoch++;clearNearReview();await api('near-revoke');await loadNear();nearMessage('Task access revoked. Review and approve again before generating.','blocked');});
$('nearMode').onchange=()=>{nearEpoch++;clearNearReview();nearMessage('');nearResult(null);nearRoute();};
$('nearCheck').onclick=nearAction(async()=>{
 const mode=$('nearMode').value,epoch=nearEpoch;$('nearCheck').disabled=true;
 try{const s=await api('near-check',{mode});if(epoch!==nearEpoch)return;
 $('nearReadiness').textContent=s.message||(s.ready?'Setup present; verification will run before sending.':s.missing.join('; '));}
 finally{$('nearCheck').disabled=false;}
});
async function prepareNear(ids){
 nearEpoch++;clearNearReview();nearMessage('');
 const epoch=nearEpoch,r=await api('near-review',{ids,mode:$('nearMode').value});if(epoch!==nearEpoch)return;
 if(r.blocked){nearMessage(r.reason+' Inference calls for this request: 0.','blocked');return;}
 nearReview=r;$('nearReview').hidden=false;$('nearPayload').textContent=r.payload;
 const messages=JSON.parse(r.payload).messages;
 $('nearSystem').textContent=messages.filter(x=>x.role==='system').map(x=>x.content).join('\n\n');
 $('nearContext').textContent=messages.filter(x=>x.role==='user').map(x=>x.content).join('\n\n');
 $('nearReviewDest').textContent=r.destination+' · '+(r.mode==='rehearsal'?'no model called':r.model);
 $('nearHash').textContent='SHA-256: '+r.sha256+' · approval expires at '+new Date(r.expires*1000).toLocaleTimeString();
 $('nearSend').textContent=r.mode==='live'?'Approve & send to NEAR':r.mode==='local'?'Approve & generate locally':'Run scripted backup';
 $('nearConsentLabel').textContent=r.mode==='live'?'I approve sending the displayed prompt and context to NEAR and this model.':r.mode==='local'?'I approve giving the displayed prompt and context to Ollama on this Mac.':'I understand this is a scripted sample, with no AI call.';
 nearButtons();
}
$('nearPrepare').onclick=nearAction(()=>prepareNear(['meeting-notes']));
$('nearRestricted').onclick=nearAction(()=>prepareNear(['meeting-notes','financial-note']));
$('nearConsent').onchange=nearButtons;
$('nearSend').onclick=nearAction(async()=>{
 if($('nearSend').disabled||!nearReview||!$('nearConsent').checked)return;
 const r=nearReview,epoch=nearEpoch;nearBusy=true;clearNearReview();nearResult(null);
 nearMessage(r.mode==='local'?'Checking local model and permissions, then generating. First load may take a minute.':r.mode==='live'?'Verifying NEAR before sending approved context…':'Running the scripted backup…','pending');
 try{const result=await api('near-send',{approval_id:r.approval_id,payload_hash:r.sha256,approved:true});if(epoch!==nearEpoch)return;nearMessage('');nearResult(result);}
 catch(error){if(epoch===nearEpoch)nearMessage(error.message);}
 finally{nearBusy=false;nearButtons();}
});
$('nearCopy').onclick=nearAction(async()=>{await navigator.clipboard.writeText($('nearDraft').textContent);$('nearCopy').textContent='Copied';});
function openStandaloneDemo(){
 if(!dashboard?.demo_only)return;
 if(!nearDemoOpened){nearDemoOpened=true;document.body.classList.add('near-demo-only');$('nearMode').value='local';for(const nav of document.querySelectorAll('nav [data-page]'))nav.hidden=nav.dataset.page!=='near';document.title='Airlock · Founder demo';}
 window.nearReady=nearNav.onclick({});
}
// Expiry only updates controls; server permissions remain authoritative at send.
setInterval(()=>{if(!nearPage.hidden&&nearState){nearButtons();if(nearReview&&nearReview.expires*1000<=Date.now()){clearNearReview();nearMessage('Approval expired. Review the request again.','blocked');}}},1000);
window.addEventListener('private-ai-refresh',openStandaloneDemo);if(dashboard)openStandaloneDemo();
