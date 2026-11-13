'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; };
let owner=location.hash.slice(1)||sessionStorage.getItem('private-ai-owner');
if(owner)sessionStorage.setItem('private-ai-owner',owner);
history.replaceState(null,'',location.pathname);
let dashboard=null, selectedAgent='codex', exportConfig='', library=null, libraryKind='memories';
let mode='library', found=[], chosen=new Map(), created=null, phrasesDirty=false;
const names={dot:'Dot',codex:'Codex','claude-desktop':'Claude Desktop','claude-code':'Claude Code',cursor:'Cursor',mcp:'Other agent',test:'Local verification'};
const marks={dot:'D',codex:'⌘','claude-desktop':'✳','claude-code':'C',cursor:'↗',mcp:'+'};
const prompt='Use Airlock to suggest what I should focus on this week, using my memories, skills and relevant Gmail. Cite what you found, distinguish facts from suggestions, and do not change or send any email.';
function notice(text,error=false){$('notice').textContent=text;$('notice').hidden=!text;$('notice').classList.toggle('error',error);}
async function api(action,body={}){
 const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+owner},body:JSON.stringify(body),cache:'no-store'});
 let result;try{result=await response.json();}catch{throw Error('Open the Airlock app to reconnect.');}
 if(!response.ok)throw Error(result.error||'Connection unavailable. Open the Airlock app to reconnect.');
 return result;
}
function guard(fn){return async function(event){if(event?.type==='submit')event.preventDefault();const button=event?.currentTarget?.tagName==='BUTTON'?event.currentTarget:null;const disabled=button?.disabled;try{notice('');if(button)button.disabled=true;await fn(event);}catch(error){notice(error.message,true);const dialog=document.querySelector('dialog[open]');if(dialog){let msg=dialog.querySelector('.dialog-error');if(!msg){msg=el('p',undefined,'dialog-error');msg.setAttribute('role','alert');dialog.append(msg);}msg.textContent=error.message;}}finally{if(button?.isConnected)button.disabled=disabled||(button.id==='create'&&(!$('consent').checked||!chosen.size));}};}
function switchPage(page){for(const node of document.querySelectorAll('.page'))node.hidden=node.id!=='page-'+page;for(const node of document.querySelectorAll('[data-page]')){node.classList.toggle('active',node.dataset.page===page);if(node.dataset.page===page)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');}$('pageTitle').textContent=page==='agents'?'Connections':page==='workbench'?'Skills & actions':page[0].toUpperCase()+page.slice(1);window.scrollTo({top:0,behavior:'instant'});if(page==='workbench'&&typeof loadWorkbench==='function')guard(loadWorkbench)();}
for(const button of document.querySelectorAll('[data-page],[data-go]'))button.onclick=()=>switchPage(button.dataset.page||button.dataset.go);
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>$(button.dataset.close).close();
for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
const active=c=>!c.revoked&&c.expires*1000>Date.now()&&c.remaining>0;
function stateLabel(c){return c.revoked?'Disconnected':c.expires*1000<=Date.now()?'Expired':c.remaining<=0?'Limit reached':'Access on';}
function avatar(agent){return el('span',marks[agent]||'+','agent-avatar');}
function connectionRow(c,compact=false){
 const row=el('div',undefined,'connection');row.append(avatar(c.agent));const info=el('div',undefined,'agent-info'),title=el('div',undefined,'agent-title');title.append(el('strong',names[c.agent]||'Agent'),el('span',stateLabel(c),'pill'+(active(c)?'':' off')));info.append(title);
 const automatic=c.mode==='automatic';info.append(el('p',automatic?'Automatic context · memories, skills & Gmail':`${c.counts.memories} memories · ${c.counts.skills} skills · ${c.counts.gmail} reviewed emails`));
 info.append(el('p',`${c.remaining} calls left · ${active(c)?'Until':'Ended'} ${new Date(c.expires*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}`));row.append(info);
 const actions=el('div',undefined,'connection-actions');
 if(compact){const manage=el('button','Manage');manage.onclick=()=>switchPage('agents');actions.append(manage);}
 else if(active(c)){
  const disconnect=el('button','Disconnect');disconnect.onclick=guard(async()=>{await api('revoke',{id:c.id});await refresh();notice((names[c.agent]||'Agent')+' disconnected. Future context requests are blocked.');});actions.append(disconnect);
  const options=el('details'),summary=el('summary','•••');summary.setAttribute('aria-label','More options for '+(names[c.agent]||'agent'));options.append(summary);const menu=el('div',undefined,'menu');
  const toggle=el('button',automatic?'Use reviewed excerpts only':'Use automatic context');toggle.onclick=guard(async()=>{await api('automatic',{identifier:c.id,enabled:!automatic,approved:true});await refresh();notice(automatic?'Automatic sharing is off. Only previously reviewed excerpts can be returned.':'Automatic context enabled. Expiry and call limits are unchanged.');});menu.append(toggle);options.append(menu);actions.append(options);
 }else{const reconnect=el('button','Connect again');reconnect.onclick=()=>openConnect(c.agent);actions.append(reconnect);}
 row.append(actions);return row;
}
function renderConnections(){
 const all=dashboard.connections,live=all.filter(active),past=all.filter(c=>!active(c));$('agentBadge').textContent=live.length;
 for(const [id,list,compact] of [['overviewConnections',live.slice(0,3),true],['connections',live,false],['pastConnections',past.slice().reverse(),false]]){const host=$(id);host.replaceChildren();if(!list.length&&id!=='pastConnections'){const empty=el('div',undefined,'empty');empty.append(el('p','No agents have active access. Add one to start using your context.'));const b=el('button','Add an agent','primary');b.onclick=()=>openConnect();empty.append(b);host.append(empty);}else for(const c of list)host.append(connectionRow(c,compact));}
 $('pastCount').textContent=`(${past.length})`;
}
function renderClients(){
 $('clientCards').replaceChildren();$('agentChoices').replaceChildren();
 for(const client of [...dashboard.clients].sort((a,b)=>Number(b.can_install)-Number(a.can_install))){
  const card=el('button',undefined,'client-card');card.append(avatar(client.id),el('strong',client.name),el('p',client.hint),el('span','Connect →','text-button'));card.onclick=()=>openConnect(client.id);$('clientCards').append(card);
  const choice=el('button',undefined,'agent-choice');choice.type='button';choice.dataset.agent=client.id;choice.append(avatar(client.id),el('span',client.id==='dot'&&!dashboard.saved_dot?'Dot · separate setup':client.name));choice.disabled=client.id==='dot'&&!dashboard.saved_dot;choice.onclick=()=>chooseAgent(client.id);$('agentChoices').append(choice);
 }
}
function chooseAgent(agent){selectedAgent=agent;$('connectAgent').disabled=agent==='dot'&&!dashboard.saved_dot;for(const c of document.querySelectorAll('.agent-choice')){c.classList.toggle('selected',c.dataset.agent===agent);c.setAttribute('aria-pressed',String(c.dataset.agent===agent));}const client=dashboard.clients.find(c=>c.id===agent);$('connectAgent').textContent=agent==='mcp'?'Create local connection':'Connect '+client.name;$('connectHint').textContent=agent==='dot'?(dashboard.saved_dot?'Uses your saved private Dot tunnel. No key entry.':'A private Dot tunnel must be configured in Advanced setup first.'):agent==='mcp'?'Creates a copyable setup for agents that support local MCP. It works on this Mac.':(client.app_present?'Detected on this Mac. ':'App not detected here. ')+'Saves the connection in this agent’s settings. Existing connections are preserved.';}
function openConnect(agent='codex'){if(!dashboard)return;chooseAgent(agent);$('connectDialog').querySelector('.dialog-error')?.remove();$('connectDialog').showModal();}
for(const b of document.querySelectorAll('[data-add]'))b.onclick=()=>openConnect();
async function refresh(){
 library=null;
 if(!owner)throw Error('Open the Airlock app to connect this browser.');
 dashboard=await api('dashboard');$('serviceStatus').textContent='Running on this Mac';$('memoryCount').textContent=dashboard.counts.memories;$('skillCount').textContent=dashboard.counts.skills;
 const gmail=dashboard.gmail;$('gmailSummary').textContent=gmail.sign_in==='connected'?'Connected':gmail.error?'Needs attention':gmail.account?'Sign-in saved':'Not connected';
 $('autoSummary').textContent=`All ${dashboard.counts.memories} memories and ${dashboard.counts.skills} skills are available for local selection. Gmail is searched live when relevant.`;
 renderConnections();renderClients();window.dispatchEvent(new Event('private-ai-refresh'));
}
$('refresh').onclick=guard(refresh);
$('connectAgent').onclick=guard(async()=>{
 const lifetime=Number($('newLifetime').value),max_calls=Number($('newCalls').value);
 if(!Number.isInteger(max_calls)||max_calls<1||max_calls>1000)throw Error('Choose between 1 and 1,000 tool calls.');
 const result=await api('client-connect',{agent:selectedAgent,approved:true,lifetime,max_calls,install:selectedAgent!=='mcp'});
 exportConfig=result.config||'';$('setupTitle').textContent=result.agent==='dot'?'Dot is connected':result.installed?'Settings saved':'Connection created';$('setupMessage').textContent=result.message;$('exportConfig').textContent=exportConfig;$('configDetails').hidden=!exportConfig;$('configDetails').open=!result.installed;$('connectDialog').close();$('setupDialog').showModal();await refresh();
});
$('copyConfig').onclick=guard(async()=>{await navigator.clipboard.writeText(exportConfig);notice('Setup copied. Paste it into your agent’s MCP settings.');$('copyConfig').textContent='Copied';setTimeout(()=>$('copyConfig').textContent='Copy setup',1500);});
$('copyPrompt').onclick=guard(async()=>{await navigator.clipboard.writeText(prompt);$('copyPrompt').textContent='Copied';setTimeout(()=>$('copyPrompt').textContent='Copy prompt',1500);});
$('checkGmail').onclick=guard(async()=>{const r=await api('gmail-check');await refresh();notice(r.message);});
$('reconnect').onclick=guard(async()=>{await connectGmail();});
async function loadLibrary(){if(!library)library=(await api('library')).items;return library;}
function renderLibrary(){const q=$('librarySearch').value.trim().toLocaleLowerCase();const items=library.filter(x=>x.kind===libraryKind&&(!q||x.text.toLocaleLowerCase().includes(q)));$('libraryItems').replaceChildren();if(!items.length)$('libraryItems').append(el('p','No matches. Try another word.','empty'));for(const item of items){const row=el('div',undefined,'library-item');if(item.device_only)row.append(el('span','Device only','pill'));row.append(el('p',item.text));$('libraryItems').append(row);}}
async function browse(kind){libraryKind=kind;await loadLibrary();$('libraryTitle').textContent=kind==='skills'?'Your skills':'Your memories';$('librarySearch').value='';renderLibrary();$('libraryDialog').showModal();}
$('browseMemories').onclick=guard(()=>browse('memories'));$('browseSkills').onclick=guard(()=>browse('skills'));$('librarySearch').oninput=renderLibrary;
$('privatePhrases').oninput=()=>{phrasesDirty=true;};
$('savePrivatePhrases').onclick=guard(async()=>{await api('private-phrases',{phrases:$('privatePhrases').value.split('\n').map(x=>x.trim()).filter(Boolean)});phrasesDirty=false;notice('Saved. These phrases will be removed from future automatic responses.');});
async function showDisclosures(){const data=await api('disclosures');$('disclosures').replaceChildren();if(!data.events.length)$('disclosures').append(el('p','No automatic context has been shared yet.','empty'));for(const event of data.events.slice().reverse()){const row=el('details',undefined,'receipt'),summary=el('summary');const label={get_private_context:'Memories & skills',search_gmail:'Gmail search',read_gmail:'Email excerpt'}[event.tool]||event.tool;summary.append(el('b',names[event.agent_name]||'Agent'),document.createTextNode(` · ${label} · ${event.items.length} excerpts · ${new Date(event.at*1000).toLocaleString()}`));row.append(summary,el('p',event.coverage,'fine'),el('pre',event.response?JSON.stringify(event.response,null,2):event.items.map(i=>`${i.citation} ${i.title}\n${i.text}`).join('\n\n')||'No excerpts returned.'));$('disclosures').append(row);}}
$('showDisclosures').onclick=guard(showDisclosures);$('openActivity').onclick=guard(async()=>{switchPage('privacy');await showDisclosures();$('disclosures').scrollIntoView({behavior:'smooth',block:'center'});});
$('audit').onclick=guard(async()=>{const r=await api('audit');$('events').textContent=r.events.map(x=>`${new Date(x.at*1000).toLocaleString()}  ${x.tool}: ${x.status}  (${x.released_refs.length} excerpts)`).join('\n')||'No activity.';});
$('showEvaluation').onclick=guard(async()=>{const r=await api('evaluation');$('evaluation').textContent=r.answer?((r.model||'Tested answer')+'\n\n'+r.answer):'No answer test has finished yet.';});
$('checkDot').onclick=guard(async()=>{const r=await api('dot-status');$('transportStatus').textContent=r.ready?'Private tunnel connected. The access duration and call limits above still apply.':'Tunnel disconnected. Reconnect your saved setup, or add a new Dot connection if access has expired.';});
$('restoreDot').onclick=guard(async()=>{const r=await api('restore-dot');$('transportStatus').textContent=r.message;await refresh();});
$('connectDot').onclick=guard(async()=>{if(!created||created.agent!=='dot')throw Error('First create a reviewed Dot connection in Privacy → Share exact excerpts instead.');const r=await api('install-dot',{token:created.token,tunnel_id:$('tunnelId').value,runtime_key:$('runtimeKey').value});$('runtimeKey').value='';$('dotStatus').textContent=r.message;await refresh();});
// Exact-excerpt mode remains available without crowding the everyday controls.
const sourceKey=x=>x.kind+':'+x.source_id;
function changed(){$('consent').checked=false;$('create').disabled=true;}
function renderSources(){const host=$('sources');host.replaceChildren();const q=$('search').value.toLocaleLowerCase();const list=mode==='gmail'?found:q?(library||[]).filter(x=>x.text.toLocaleLowerCase().includes(q)):[];if(!list.length){host.append(el('p',mode==='gmail'?'Search Gmail for a message.':q?'No matching sources.':'Search for a topic to select an excerpt.','empty'));return;}for(const x of list){const row=el('div',undefined,'source');row.append(el('span',x.kind,'tag'));if(x.title)row.append(el('strong',x.title));row.append(el('p',x.text));const b=el('button',x.device_only?'Device only':chosen.has(sourceKey(x))?'Selected':'Select excerpt');b.disabled=x.device_only||chosen.has(sourceKey(x));b.onclick=()=>{chosen.set(sourceKey(x),{kind:x.kind,source_id:x.source_id,text:x.suggested||x.text,title:x.kind==='gmail'?'Selected email':x.kind==='skills'?'Saved skill':'Saved background'});changed();renderSources();renderSelected();};row.append(b);host.append(row);}}
function renderSelected(){const host=$('selected');host.replaceChildren();if(!chosen.size)host.append(el('p','Choose a source to start.','empty'));for(const [k,v]of chosen){const row=el('div',undefined,'selected-item'),top=el('div',undefined,'top');top.append(el('span',v.kind,'tag'));const remove=el('button','Remove');remove.onclick=()=>{chosen.delete(k);changed();renderSelected();renderSources();};top.append(remove);const title=el('input');title.value=v.title;title.setAttribute('aria-label','Shared title');title.oninput=()=>{v.title=title.value;changed();};const text=el('textarea');text.value=v.text;text.setAttribute('aria-label','Exact shared excerpt');text.oninput=()=>{v.text=text.value;changed();};row.append(top,title,text);host.append(row);}}
$('exactReview').addEventListener('toggle',guard(async()=>{if($('exactReview').open){await loadLibrary();renderSources();renderSelected();}}));
$('libraryTab').onclick=()=>{mode='library';$('searchLabel').textContent='Find in your local library';$('libraryTab').classList.add('active');$('gmailTab').classList.remove('active');renderSources();};
$('gmailTab').onclick=()=>{mode='gmail';$('searchLabel').textContent='Search Gmail to review a message';$('gmailTab').classList.add('active');$('libraryTab').classList.remove('active');renderSources();};
$('search').oninput=()=>{if(mode==='library')renderSources();};
$('searchForm').onsubmit=guard(async()=>{if(mode==='gmail'){const r=await api('gmail',{query:$('search').value});found=r.items;notice(r.more_available?'Showing the first eight matches. Refine the search for more specific results.':'');}renderSources();});
for(const id of ['agent','purpose','lifetime','calls'])$(id).onchange=changed;
$('consent').onchange=()=>{$('create').disabled=!$('consent').checked||!chosen.size;};
$('create').onclick=guard(async()=>{if(!$('consent').checked)return;created=await api('create',{agent:$('agent').value,purpose:$('purpose').value,views:[...chosen.values()],approved:true,lifetime:Number($('lifetime').value),max_calls:Number($('calls').value)});created.agent=$('agent').value;$('created').hidden=false;$('token').value=created.token;$('save').hidden=created.agent!=='claude-code';$('useSavedDot').hidden=created.agent!=='dot'||!dashboard.saved_dot;$('next').textContent=created.agent==='dot'?'Use your saved Dot setup to activate these reviewed excerpts.':'Save the bundled Claude Code connection to use these reviewed excerpts.';chosen.clear();changed();renderSources();renderSelected();await refresh();$('created').scrollIntoView({behavior:'smooth'});});
$('copy').onclick=guard(async()=>{await navigator.clipboard.writeText(created.token);notice('Token copied. Paste only into the agent’s connection settings.');});
$('save').onclick=guard(async()=>{const r=await api('install-claude',{token:created.token});notice(r.message);});
$('useSavedDot').onclick=guard(async()=>{const r=await api('restore-dot',{token:created.token});notice(r.message);await refresh();});
window.addEventListener('beforeunload',event=>{if(phrasesDirty){event.preventDefault();event.returnValue='';}});
guard(async()=>{await refresh();const policy=await api('private-phrases');$('privatePhrases').value=policy.phrases.join('\n');})().catch(()=>{});
