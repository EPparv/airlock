'use strict';

const $ = id => document.getElementById(id);
const preview = typeof window.airlockExample === 'function';
const personal = !preview && location.pathname.endsWith('/personal');
const key = personal ? 'private-ai-owner' : 'airlock-test-owner';
const ownerToken = preview ? null : location.hash.slice(1) || sessionStorage.getItem(key);
if (ownerToken) sessionStorage.setItem(key, ownerToken);
if(!preview)history.replaceState(null, '', location.pathname);
let state, tab = 'actions', pending = false, refreshing = false;
const names = {'claude-desktop':'Claude Desktop', 'claude-code':'Claude Code', codex:'Codex', cursor:'Cursor', mcp:'Custom agent', dot:'Dot', ironclaw:'IronClaw'};
const titles = {actions:'Private actions', agents:'Connected agents', library:'Local library', activity:'Activity'};
const subtitles = {actions:'Review what your agents can do on your behalf.', agents:'Choose what each agent may read or request.', library:'Memories and skills saved on this device.', activity:'Exact tool responses Airlock returned to your agents.'};
const kinds = {email:['✉','Mail'], event:['▦','Calendar'], data:['▤','Data view'],api:['⇄','API view']};
const statuses = {ready:'Ready',pending:'Needs approval',submitting:'Check the app',unconfirmed:'Check the app',sent:'Sent to Mail',created:'Event created',declined:'Declined'};
function el(tag, value, cls) { const x=document.createElement(tag); if(value!=null)x.textContent=value; if(cls)x.className=cls; return x; }
function put(parent,...children) { parent.append(...children); return parent; }
function button(label, fn, cls='outline') { const b=el('button',label,cls); b.type='button'; b.addEventListener('click',fn); return b; }
function report(msg,error=false){const n=$('notice');n.hidden=!msg;n.textContent=msg;n.classList.toggle('error',error);}
async function api(action,body={},token=ownerToken){if(preview)return window.airlockExample(action,body);if(!token)throw Error('Open Airlock.app to unlock this workspace.');const r=await fetch('/api/'+action,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.error||(r.status===401?'Reopen Airlock.app to reconnect.':'The request could not be completed.'));return data;}
function run(fn){return async()=>{if(pending)return;pending=true;try{await fn();}catch(e){if($('dialog').open){$('dialog-error').textContent=e.message;$('dialog-error').hidden=false;}else report(e.message,true);}finally{pending=false;}};}
function modal(title){$('dialog-title').textContent=title;const host=$('dialog-content');host.replaceChildren();$('dialog-error').hidden=true;if(!$('dialog').open)$('dialog').showModal();return put(host,el('div',null,'form')).firstElementChild;}
function close(){if($('dialog').open)$('dialog').close();}
$('close').onclick=close;
function field(parent,label,element){const l=el('label',label,'field');l.append(element);parent.append(l);return element;}
function input(type='text',value=''){const n=el('input');n.type=type;n.value=value;return n;}
function select(options){const s=el('select');for(const [v,t] of options){const o=el('option',t);o.value=v;s.append(o);}return s;}
function check(parent,label,value=false){const l=el('label',null,'check'),c=input('checkbox');c.checked=value;put(l,c,el('span',label));parent.append(l);return c;}
function group(parent,title){const x=el('fieldset');x.append(el('legend',title));parent.append(x);return x;}
function fine(parent,text){parent.append(el('p',text,'helper'));}
function person(id){const g=state?.agents.find(a=>a.id===id);return g?(names[g.name]||g.name):'Disconnected agent';}
function empty(title,hint){const box=el('article',null,'empty');return put(box,el('h2',title),el('p',hint));}
function active(a){return !['expired','revoked'].includes(a.status)&&a.scope!=null;}
function listRow(title,hint,controls=[]){const n=el('div',null,'row'),a=el('div',null,'row-copy');put(a,el('h3',title),el('p',hint));return put(n,a,put(el('div',null,'row-group'),...controls));}
function formAction(form,label,fn){const b=button(label,run(async()=>{b.disabled=true;try{await fn();}finally{b.disabled=false;}}),'button');form.append(b);return b;}
function setTab(next){tab=next;report('');render();}
const dtime=t=>new Date(t*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
function dateString(s){return new Date(s).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
function facts(pairs){const d=el('dl',null,'fields');for(const [k,v] of pairs)put(d,el('dt',k),el('dd',v));return d;}
function rawDetails(title,value,cls='agent-view'){const d=el('details',null,cls);put(d,el('summary',title),el('pre',JSON.stringify(value,null,2)));return d;}
async function refresh(){if(refreshing)return;refreshing=true;try{const next=await api('workspace-state');if(JSON.stringify(next)!==JSON.stringify(state)){state=next;render();}}finally{refreshing=false;}}
function decision(a,okay){return run(async()=>{const r=await api('workspace-decide',{identifier:a.id,fingerprint:a.fingerprint,approve:okay});await refresh();report(r.status==='unconfirmed'?'Delivery could not be confirmed. Check Mail or Calendar before trying again.':state.example?'Example decision saved.':okay?'Action submitted to your local app.':'Request declined.',r.status==='unconfirmed');});}
function card(a){
 const card=el('article',null,'card'), info=el('div');const [symbol,kind]=kinds[a.kind];
 const title=el('div',null,'kind');put(info,el('p',a.applicant?person(a.applicant)+' · '+kind:kind,'eyeline'),el('h2',a.label));
 const status=state.example&&['sent','created'].includes(a.state)?'Simulated':statuses[a.state]||a.state;
 put(title,el('span',symbol,'app-icon'),info);
 put(card,put(el('div',null,'card-head'),title,el('span',status,'badge '+(a.state==='pending'?'pending':['sent','created'].includes(a.state)?'done':'nostatus'))));
 const p=a.payload,body=el('div',null,'card-body');let fields;
 if(a.kind==='email'){fields=[['To',p.recipients.join(', ')],['Subject',p.subject]];if(p.attachment)fields.push(['Attachment',p.attachment.name+' · '+Math.ceil(p.attachment.size/1024)+' KB']);put(body,facts(fields),el('p',p.body,'message'));}
 else if(a.kind==='event')body.append(facts([['Calendar',p.calendar],['Event',p.title],['Starts',dateString(p.start)],['Ends',dateString(p.end)]]));
 else if(a.kind==='api')body.append(facts([['Endpoint',p.url],['Visible fields',p.fields.join(', ')]]));
 else body.append(facts([['Source',p.name],['Visible fields',p.fields.join(', ')],['Rows',String(p.count)+(p.truncated?' (first 100)':'')]]));
 card.append(body);
 const mostRecent=state.receipts.find(r=>r.response?.reference && r.response.reference===a.handles?.[r.agent]);
 if(mostRecent)card.append(rawDetails('Returned to '+person(mostRecent.agent),mostRecent.response));
 else {const box=el('div',null,'agent-view');box.textContent=['data','api'].includes(a.kind)?'Agents can retrieve only the selected fields.':'Agents can retrieve the label, a private reference, and the status.';card.append(box);}
 const bar=el('div',null,'bar');
 if(a.state==='pending'){put(bar,button(state.example?'Approve example':a.kind==='event'?'Approve & create event':'Approve & send',decision(a,true),'button'),button('Decline',decision(a,false),'quiet'));}
 if(['submitting','unconfirmed'].includes(a.state))bar.append(el('p','Check the destination app. Airlock will not retry this action.','small'));
 if(state.example&&a.state!=='pending'){
  const clients=select(state.agents.filter(x=>a.audience.includes(x.id)).map(x=>[x.id,person(x.id)]));clients.setAttribute('aria-label','Example agent');clients.className='inline-select';
  const tool=['data','api'].includes(a.kind)?'read_private_fields':a.state==='ready'?'request_private_action':'private_action_status';put(bar,clients,button(['data','api'].includes(a.kind)?'Read fields':a.state==='ready'?'Request example':'Check receipt',run(async()=>{const output=await api('workspace-try',{identifier:a.id,agent:clients.value,tool});await refresh();const f=modal('Returned to '+person(clients.value));f.append(el('pre',JSON.stringify(output,null,2)));})));}
 if(!state.example&&a.state!=='submitting')bar.append(button('Remove',()=>{const f=modal('Remove this action?');fine(f,'All assigned agents will lose access to this action.');formAction(f,'Remove action',async()=>{await api('workspace-remove',{identifier:a.id});close();await refresh();});},'quiet right'));
 if(bar.childNodes.length)card.append(bar);return card;
}
function actions(host){if(!state.actions.length)host.append(empty('No prepared actions','Prepare a local action for an agent, or enable follow-ups in its access settings.'));else state.actions.forEach(a=>host.append(card(a)));}
function agents(host){if(!state.agents.length){host.append(empty('Connect your first agent','Choose an AI app and the records it may use. You can change its access later.'));return;}
 const box=el('div',null,'card');for(const a of state.agents){const count=a.scope?.records?.length??0;const summary=(state.example?'Example connection':a.status==='configured'?'Settings saved':a.status==='used'?'Has requested context':a.status)+' · '+count+' selected record'+(count===1?'':'s');
 const controls=state.example?[]:[button('Manage',run(()=>manageAgent(a)))];box.append(listRow(names[a.name]||a.name,summary,controls));}host.append(box);
}
function library(host){
 if(!state.example&&state.proposals.length){host.append(el('h2','Proposed updates','list-title'));const queue=el('div',null,'card');for(const p of state.proposals){const decide=accept=>run(async()=>{await api('memory-decide',{proposal_id:p.id,accept});await refresh();});queue.append(listRow(p.text||p.operation,(names[p.agent]||p.agent)+' · '+p.kind,[button('Accept',decide(true),'button'),button('Decline',decide(false),'quiet')]));}host.append(queue);}
 if(!state.records.length){host.append(empty('Your library is empty','Add a preference or a skill. Choose who can use it in Agents.'));return;}
 const box=el('div',null,'card');for(const r of state.records){const hint=(r.kind==='skills'?'Skill':'Memory')+' · '+(r.never_share?'Only on this device':r.sensitive?'Private computation':'Available to assign');box.append(listRow(r.text,hint));}host.append(box);
}
function activity(host){if(!state.receipts.length){host.append(empty('No responses yet','Tool responses appear here after an agent makes a request.'));return;}
 for(const r of state.receipts){const d=rawDetails(person(r.agent)+' · '+r.tool,r.response,'receipt');d.append(el('time',dtime(r.at),'small'));host.append(d);}
}
function render(){if(!state)return;$('title').textContent=titles[tab];$('subtitle').textContent=subtitles[tab];$('mode').textContent=state.example?'Example workspace':'Personal workspace';
 const sw=$('switch');sw.hidden=preview||!state.example&&!sessionStorage.getItem('airlock-test-owner');sw.textContent=state.example?'Open my workspace':'Close workspace';sw.onclick=state.example?openPersonal:closePersonal;
 $('advanced').hidden=preview;
 $('advanced').textContent=state.example?'Privacy checks ↗':'Advanced settings ↗';$('advanced').href=preview||state.example||!sessionStorage.getItem('airlock-test-owner')?'/':'/personal';
 for(const n of document.querySelectorAll('[data-tab]')){n.classList.toggle('active',n.dataset.tab===tab);n.setAttribute('aria-current',n.dataset.tab===tab?'page':'false');}
 const pc=state.actions.filter(a=>a.state==='pending').length;$('pending-count').textContent=pc;$('pending-count').hidden=!pc;
 const primary=$('primary');primary.hidden=true;
 if(!state.example&&tab!=='activity'){primary.hidden=false;primary.textContent={actions:'New action',agents:'Connect agent',library:'Add record'}[tab];primary.onclick=run({actions:newAction,agents:()=>manageAgent(),library:addNote}[tab]);}
 if(state.example&&tab==='actions'&&!pc){primary.hidden=false;primary.textContent='Reset example';primary.onclick=()=>{const f=modal('Reset the example?');fine(f,'This clears fictional actions, receipts and test connections.');formAction(f,'Reset example',async()=>{await api('test-reset',{approved:true});close();await refresh();});};}
 const host=$('content');host.replaceChildren();host.setAttribute('aria-busy','false');({actions,agents,library,activity})[tab](host);
}
function openPersonal(){const f=modal('Open your personal workspace?');fine(f,'This unlocks your local library and resumes previously approved agent connections. Mail and Calendar are accessed when you choose a source or approve an action.');formAction(f,'Open my workspace',async()=>{const r=await api('open-personal',{approved:true});const url=new URL(r.url);location.assign('/workspace/personal'+url.hash);});}
function closePersonal(){const f=modal('Close personal access?');fine(f,'New personal requests will be blocked.');formAction(f,'Close workspace',async()=>{await api('close-personal',{},sessionStorage.getItem('airlock-test-owner'));sessionStorage.removeItem('private-ai-owner');location.assign('/workspace');});}
function addNote(){const f=modal('Add to your library');const kind=field(f,'Type',select([['memories','Memory'],['skills','Skill']]));const t=field(f,'Text',el('textarea'));t.placeholder='What should your agents remember or know how to do?';const only=check(f,'Keep this record on this device only');formAction(f,'Save record',async()=>{await api('workspace-note',{kind:kind.value,text:t.value,private:only.checked});close();await refresh();report('Saved locally. Choose an agent to grant access.');});}
async function manageAgent(agent){
 const f=modal(agent?'Manage '+person(agent.id):'Connect an agent');if(agent&&!active(agent)){fine(f,'This connection is expired, revoked or uses older access settings. Connect a new scoped agent.');return;}
 const which=agent?null:field(f,'Agent',select(['claude-desktop','codex','claude-code','cursor'].map(k=>[k,names[k]])));
 const available=await api('client-context');if(!f.isConnected)return;
 const fs=group(f,'Shared records'), checks=[];fs.classList.add('readout');
 for(const r of available.records){const c=check(fs,r.text.slice(0,130)+(r.sensitive?' · private computation':''),agent?.scope?.records?.includes(r.ref));checks.push([r,c]);}
 if(!checks.length)fine(fs,'You can connect now and add records later.');
 const perms=group(f,'Device permissions');const mail=check(perms,'Request a follow-up to the selected message in Mail',agent?.device?.mail);
 const cal=check(perms,'Request a follow-up to the most recent meeting with attendees',agent?.device?.calendar);
 const proposals=check(perms,'Propose memories for review',agent?.proposals);fine(f,'Every send needs local approval. Agent settings are saved on this Mac.');
 formAction(f,agent?'Save access':'Connect agent',async()=>{const selection=Object.fromEntries(checks.filter(([,c])=>c.checked).map(([r])=>[r.ref,r.text_hash]));
  const result=await api('workspace-connect',{agent:agent?.name||which.value,identifier:agent?.id||'',selection,proposals:proposals.checked,mail:mail.checked,calendar:cal.checked});close();await refresh();report(result.message||'Access saved.');});
 if(agent)f.append(button('Revoke connection',run(async()=>{await api('revoke',{id:agent.id});close();await refresh();}),'danger'));
}
async function upload(file){if(!file)throw Error('Choose a file first.');if(file.size>4*1024*1024)throw Error('Choose a file up to 4 MB.');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve({name:file.name,data:r.result.split(',')[1]});r.onerror=()=>reject(Error('The file could not be read.'));r.readAsDataURL(file);});}
function newAction(){
 if(!state.agents.some(active)){const f=modal('Connect an agent first');fine(f,'This action needs an agent with scoped access.');f.append(button('Connect agent',run(()=>manageAgent()),'button'));return;}
 const f=modal('Prepare a private action');const type=field(f,'Action',select([['email','Send an email'],['event','Create a calendar event'],['data','Share fields from a file or database'],['api','Share fields from an API']]));
 const name=field(f,'Label visible to the agent',input());name.placeholder='Investor follow-up';
 const area=el('div',null,'form');f.append(area);let getValues;
 function fieldsFor(){area.replaceChildren();if(type.value==='email'){
  const to=field(area,'Recipients',input());const source=select([['mail','Selected message in Mail'],['calendar','Recent meetings in Calendar']]);source.setAttribute('aria-label','Local source');
  const opts=el('div',null,'form');put(area,put(el('div',null,'inline-actions'),source,button('Read from Mac',run(async()=>{const r=await api('workspace-sources',{source:source.value});opts.replaceChildren();if(!r.items.length){fine(opts,'Select an email in Mail or choose a meeting with attendees.');return;}for(const item of r.items)opts.append(button(item.title||'Selected message',()=>{to.value=item.recipient||(item.recipients||[]).join(', ');opts.replaceChildren();}));}))),opts);
  const subject=field(area,'Subject',input());const body=field(area,'Message',el('textarea'));const file=field(area,'Attachment (optional)',input('file'));
  getValues=async()=>({recipients:to.value,subject:subject.value,body:body.value,attachment:file.files[0]?await upload(file.files[0]):null});
 }else if(type.value==='event'){
  const title=field(area,'Event title',input()),calendar=field(area,'Writable calendar name',input()),start=field(area,'Start',input('datetime-local')),end=field(area,'End',input('datetime-local'));
  getValues=async()=>{if(!start.value||!end.value)throw Error('Choose a start and end time.');return {title:title.value,calendar:calendar.value,start:new Date(start.value).toISOString(),end:new Date(end.value).toISOString()};};
 }else if(type.value==='api'){
  const url=field(area,'JSON endpoint',input('url')),credential=field(area,'Bearer token (optional)',input('password')),key=field(area,'Array field (optional)',input());
  url.placeholder='https://api.example.com/projects';credential.autocomplete='off';
  const picker=el('div',null,'form');let checked=[],verified='';
  const settings=()=>({url:url.value.trim(),credential:credential.value,array_key:key.value.trim()});
  const invalidate=()=>{checked=[];verified='';picker.replaceChildren();};[url,credential,key].forEach(x=>x.oninput=invalidate);
  put(area,button('Load fields',run(async()=>{invalidate();const current=settings(),r=await api('workspace-api-fields',current);if(JSON.stringify(current)!==JSON.stringify(settings()))return;verified=JSON.stringify(current);const fs=group(picker,'Fields visible to the agent');checked=r.fields.map(k=>[k,check(fs,k)]);fine(fs,'Airlock reads up to 100 rows per request.');})),picker);
  getValues=async()=>{const v=settings(),fields=checked.filter(([,c])=>c.checked).map(([k])=>k);if(!fields.length||verified!==JSON.stringify(v))throw Error('Load fields and choose at least one.');return {...v,fields};};
 }else{
  const source=field(area,'CSV, JSON or SQLite snapshot',input('file'));source.accept='.csv,.json,.sqlite,.sqlite3,.db';const fieldArea=el('div',null,'form');area.append(fieldArea);let data=null,table='',boxes=[];
  async function inspect(){const r=await api('workspace-fields',{...data,table});fieldArea.replaceChildren();boxes=[];
   if(r.tables.length){const sel=field(fieldArea,'Table',select([['','Choose a table'],...r.tables.map(x=>[x,x])]));sel.value=table;sel.onchange=run(async()=>{table=sel.value;await inspect();});}
   if(r.fields.length){const fs=group(fieldArea,'Fields visible to the agent');for(const value of r.fields)boxes.push([value,check(fs,value)]);fine(fs,'First '+r.count+' rows. Direct identifiers are filtered at retrieval.');}}
  source.onchange=run(async()=>{data=null;table='';boxes=[];fieldArea.replaceChildren();if(!source.files[0])return;data=await upload(source.files[0]);await inspect();});
  getValues=async()=>{if(!data||!boxes.some(([,c])=>c.checked))throw Error('Choose a file and at least one visible field.');return {...data,table,fields:boxes.filter(([,c])=>c.checked).map(([k])=>k)};};
 }}
 type.onchange=fieldsFor;fieldsFor();const fs=group(f,'Agents with access'),checks=state.agents.filter(active).map(a=>[a.id,check(fs,person(a.id))]);formAction(f,'Save action',async()=>{const id=await api('workspace-create',{kind:type.value,label:name.value,audience:checks.filter(([,c])=>c.checked).map(([id])=>id),values:await getValues()});close();await refresh();report(id.id?'Prepared locally. Your agent can now list its private actions.':'Saved.');});
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
refresh().catch(e=>{report(e.message,true);$('subtitle').textContent='Open Airlock.app to connect to the local service.';});
setInterval(()=>{if(!preview&&state&&!document.hidden&&!pending&&!$('dialog').open)refresh().catch(e=>report(e.message,true));},7000);
