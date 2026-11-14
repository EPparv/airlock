'use strict';
const $=id=>document.getElementById(id);
const token=location.hash.slice(1)||sessionStorage.getItem('private-ai-owner')||'';
if(location.hash){sessionStorage.setItem('private-ai-owner',token);history.replaceState(null,'',location.pathname);}
let state=null,busy=false;
async function api(action,body={}){const r=await fetch('/api/near-setup-'+action,{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok||data.error)throw Error(data.error||'NEAR setup request failed.');return data;}
function notice(text){$('notice').hidden=!text;$('notice').textContent=text;}
function buttons(){for(const b of document.querySelectorAll('button'))b.disabled=busy;$('clear').disabled=false;$('discover').disabled=busy||!state?.key_present||!state?.sdk.ready;$('probe').disabled=busy||!state?.ready;$('approve').disabled=busy||!state?.deployment_review||!$('consent').checked;}
function render(s){state=s;$('status').textContent=s.key_present?'A key is present for this session.':'Add a NEAR key to continue.';$('model').textContent=s.model;$('sdk').textContent=s.sdk.message;$('install').hidden=s.sdk.ready;$('prompt').textContent=s.probe_prompt;$('approved').textContent=s.deployment_approved?'Deployment configurations approved. Every inference call still runs the required verification checks.':'No deployments approved yet.';$('review').hidden=!s.deployment_review;$('deployments').replaceChildren();$('consent').checked=false;
for(const d of s.deployment_review?.deployments||[]){const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent=d.kind+' · SHA-256 '+d.sha256;pre.textContent=d.configuration;details.append(summary,pre);$('deployments').append(details);}
$('proof').hidden=!s.last_test;$('proof').textContent=s.last_test?JSON.stringify(s.last_test,null,2):'';buttons();}
async function run(action,body={},progress=''){if(busy)return;busy=true;buttons();notice(progress);try{render(await api(action,body));notice(action==='probe'?'Live NEAR test passed. You can now record the fictional demo.':'');}catch(e){notice(e.message);try{render(await api('status'));}catch{}}finally{busy=false;buttons();}}
$('keyForm').onsubmit=e=>{e.preventDefault();const api_key=$('apiKey').value;$('apiKey').value='';run('key',{api_key});};
$('clear').onclick=async()=>{try{render(await api('clear'));notice('Key and approvals cleared.');}catch(e){notice(e.message);}};
$('install').onclick=()=>run('install',{approved:true},'Installing the verifier. This can take a few minutes…');
$('discover').onclick=()=>run('discover',{},'Verifying hardware and deployment evidence. No inference prompt is sent…');
$('consent').onchange=buttons;
$('approve').onclick=()=>{if($('consent').checked&&state?.deployment_review)run('approve',{review_id:state.deployment_review.id,approved:true});};
$('probe').onclick=()=>run('probe',{approved:true},'Running the approved fictional test and checking its response signature…');
for(const id of ['home','memory','demo'])$(id).onclick=e=>{e.preventDefault();location.assign($(id).getAttribute('href').split('#')[0]+'#'+token);};
run('status');
