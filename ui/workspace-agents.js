'use strict';
const localAgents=['claude-desktop','codex','cursor','claude-code'];
addPage('connect','Connect agent','home',host=>{
  const list=el('div',null,'menu');host.append(list);
  for(const id of localAgents)row(list,names[id],()=>go('agent',{agent:id}));
  const more=details(host,'Other clients');
  for(const id of ['mcp','ironclaw','dot'])row(more,names[id],()=>go('agent',{agent:id}));
  choose(more,'Share exact excerpts','excerpts');
},false);

addPage('connections','Connected agents','privacy',async(host,options,bar)=>{
  bar.append(button('Connect agent',()=>go('connect')));
  const ws=await api('workspace-state');
  const current=ws.agents.filter(active),past=ws.agents.filter(a=>!active(a));
  const list=el('div',null,'menu');host.append(list);
  if(!current.length)empty(list,'No agents connected.');
  for(const a of current)item(list,names[a.name]||a.name,a.scope?(a.scope.records.length+' selected · '+(a.last_read?'Last read '+when(a.last_read):'Waiting for first request')):'Existing '+a.mode+' connection',()=>go('agent',{id:a.id,agent:a.name}));
  if(past.length){const last=details(host,'Past connections');for(const a of past)item(last,names[a.name]||a.name,a.status==='expired'?'Expired':'Revoked',()=>go('agent',{id:a.id,agent:a.name}));}
});

function limits(form){
  const l=field(form,'Expires in',select([['3600','1 hour'],['86400','1 day'],['604800','7 days'],['2592000','30 days']],'86400'));
  const c=field(form,'Request limit',input('number','100'));c.min='1';c.max='1000';
  return ()=>({lifetime:Number(l.value),max_calls:Number(c.value)});
}
function revokeAgent(a){
  confirmAction('Revoke '+(names[a.name]||a.name)+'?','This connection will lose access immediately.','Revoke connection',async()=>{
    await api('revoke',{id:a.id});await go('connections');
  },true);
}
addPage('agent','Agent access','connect',async(host,opt,bar)=>{
  const agent=opt.agent;
  if(!names[agent]){empty(host,'Choose an agent first.');host.append(button('Choose agent',()=>go('connect')));return;}
  bar.querySelector('h1').textContent=names[agent];
  const [ws,context]=await Promise.all([api('workspace-state'),api('client-context')]);
  const existing=opt.id&&ws.agents.find(a=>a.id===opt.id&&a.name===agent);
  if(opt.id&&!existing)throw Error('This connection no longer exists.');
  if(existing){
    host.closest('.page').querySelector('.back').replaceWith(button('Connected agents',()=>go('connections'),'back'));
    host.append(facts([['Status',existing.status==='used'?'Has requested context':existing.status==='configured'?'Configured':existing.status],
                      ['Requests left',existing.remaining],['Expires',when(existing.expires)||'—']]));
    if(!active(existing)){host.append(button('Create new connection',()=>go('agent',{agent})));return;}
  }
  if(agent==='dot'&&!existing){const d=await api('saved-dot');if(!d.configured){note(host,'Dot needs a private MCP tunnel on this Mac.');host.append(button('Set up Dot',()=>go('dot')));return;}}
  const form=el('div',null,'form');host.append(form);
  const records=context.records||[],scope=existing?.scope;
  const choices=details(form,'Shared records'), summary=choices.parentElement.querySelector('summary'), checks=[];
  if(!records.length)note(choices,'Your library is empty. You can connect now and add records later.');
  const allowed=scope?.disclose_records??scope?.records??[];
  for(const r of records){
    const selected=scope?.records?.includes(r.ref);
    const opts=[['off','No access']];
    if(!r.sensitive)opts.push(['excerpt','Filtered excerpt']);
    opts.push(['private','Private task only']);
    const value=selected?(scope.disclose&&allowed.includes(r.ref)&&!r.sensitive?'excerpt':scope.compute?'private':'off'):'off';
    const control=field(choices,r.text.length>180?r.text.slice(0,180)+'…':r.text,select(opts,value));
    checks.push([r,control]);
  }
  const count=()=>{const n=checks.filter(([,c])=>c.value!=='off').length;summary.textContent='Shared records · '+n+' selected';};
  for(const [,c] of checks)c.onchange=count;count();
  const devices=details(form,'Permissions');
  const mail=check(devices,'Request a follow-up to the selected email',existing?.device?.mail);
  const calendar=check(devices,'Request a follow-up to recent meeting attendees',existing?.device?.calendar);
  const proposals=check(devices,'Propose memory updates',existing?.proposals);
  const compute=check(devices,'Allow private tasks on selected records',scope?.compute);
  note(devices,'Sending mail and releasing a private task result each require your approval.');
  const readLimits=existing?null:limits(details(form,'Connection limits'));
  if(existing&&!existing.scope){
    note(form,'Saving assigns the selected records to this existing connection.');
    const mode=existing.mode==='automatic',modeName=mode?'Use reviewed excerpts only':'Use automatic context';
    form.append(button(modeName,()=>confirmAction(modeName+'?',mode?'Only previously reviewed excerpts will be available.':'This gives the agent automatic filtered access to your whole shareable library and connected read-only Gmail.',modeName,async()=>{
      await api('automatic',{identifier:existing.id,enabled:!mode,approved:true});await refresh();
    })));
    if(mode){
      const legacy=details(form,'Existing tool permissions');
      const exec=check(legacy,'Run enabled local skill packages',existing.capabilities?.skill_execution);
      const updates=check(legacy,'Allow shared note updates',existing.capabilities?.context_updates);
      legacy.append(button('Save tool permissions',async()=>{await api('capabilities',{identifier:existing.id,skill_execution:exec.checked,context_updates:updates.checked});await refresh();flash('Tool permissions saved.');}));
    }
  }
  formAction(form,existing?'Save access':'Connect '+names[agent],async()=>{
    const selected=checks.filter(([,c])=>c.value!=='off');
    const response=await api('workspace-connect',{agent,identifier:existing?.id||'',selection:Object.fromEntries(selected.map(([r])=>[r.ref,r.text_hash])),excerpt_selection:selected.filter(([,c])=>c.value==='excerpt').map(([r])=>r.ref),
      compute:compute.checked||selected.some(([,c])=>c.value==='private'),proposals:proposals.checked,mail:mail.checked,calendar:calendar.checked,...(readLimits?readLimits():{})});
    if(existing){await go('connections');flash('Access saved.');return;}
    await go('connections');
    const f=modal(preview?'Connection added to preview':'Connection configured');
    note(f,preview?'These permissions apply to this preview.':response.message||'Restart your agent and enable Airlock.');
    if(response.credential_path)f.append(facts([['Credential file',response.credential_path]]));
    if(response.config){const box=details(f,'Connection configuration');const v=typeof response.config==='string'?response.config:JSON.stringify(response.config,null,2);put(box,el('pre',v),button('Copy configuration',()=>copyText(v)));}
    const prompt='Use Airlock to check your access, then retrieve my selected context.';
    f.append(button('Copy first request',()=>copyText(prompt)));
    if(response.id)f.append(button('Check connection',async()=>{const status=await api('client-status',{id:response.id});note(f,status.status==='verified'?'Your agent requested context.':'Waiting for the agent’s first context request.');}));
    f.append(button('Close',close,'primary'));
  });
  if(existing)form.append(button('Revoke connection',()=>revokeAgent(existing),'danger'));
});

addPage('dot','Dot tunnel','connect',async host=>{
  const status=await api('saved-dot');
  note(host,status.configured?'A tunnel configuration is saved on this Mac.':'Use the tunnel ID and runtime key from your private Dot connection.');
  const f=el('div',null,'form');host.append(f);
  const id=field(f,'Tunnel ID',input()),key=field(f,'Runtime key',input('password')),token=field(f,'Agent credential',input('password'));
  key.autocomplete=token.autocomplete='off';
  formAction(f,'Save tunnel configuration',async()=>{if(preview)return nativeOnly('Dot tunnel');await api('install-dot',{token:token.value,tunnel_id:id.value,runtime_key:key.value});await refresh();flash('Tunnel saved.');});
  f.append(button('Check tunnel',async()=>{if(preview)return nativeOnly('Check tunnel');const r=await api('dot-status');note(f,r.message||r.status||'Status checked.');}));
  if(status.configured)f.append(button('Reconnect saved setup',async()=>{if(preview)return nativeOnly('Reconnect Dot');const r=await api('restore-dot');flash(r.message||'Reconnected.');}));
});

addPage('excerpts','Reviewed excerpts','connect',async host=>{
  const form=el('div',null,'form');host.append(form);
  const agent=field(form,'Agent',select(Object.entries(names).map(([k,v])=>[k,v])));
  const purpose=field(form,'Purpose',input());
  const source=field(form,'Source',select([['library','Local library'],['gmail','Gmail']]));
  const query=field(form,'Search source',input('search')),matches=el('div'),selected=new Map();
  const chosen=el('div'),rules=limits(details(form,'Connection limits'));
  function show(){chosen.replaceChildren();for(const [k,v] of selected){const part=el('div',null,'detail-block');chosen.append(part);
    const title=field(part,'Shared title',input('text',v.title)),text=field(part,'Exact text to share',el('textarea'));text.value=v.text;
    title.oninput=()=>v.title=title.value;text.oninput=()=>v.text=text.value;part.append(button('Remove',()=>{selected.delete(k);show();},'plain'));}}
  form.append(button('Find records',async()=>{
    if(!query.value.trim())throw Error('Enter a search term.');
    const data=source.value==='gmail'?await api('gmail',{query:query.value}):await api('library');matches.replaceChildren();
    const found=data.items.filter(r=>!r.device_only&&(source.value==='gmail'||r.text.toLowerCase().includes(query.value.toLowerCase())));
    if(!found.length)empty(matches,'No matching records.');
    for(const r of found.slice(0,50))item(matches,r.title||r.text.slice(0,75),r.kind,()=>{selected.set(r.kind+':'+r.source_id,{kind:r.kind,source_id:r.source_id,title:r.title||r.kind,text:r.suggested||''});show();});
  }),matches,chosen);
  formAction(form,'Review connection',()=>{
    if(!selected.size||!purpose.value.trim())throw Error('Enter a purpose and select at least one excerpt.');
    const views=Array.from(selected.values(),v=>({...v})),body={agent:agent.value,purpose:purpose.value,views,approved:true,...rules()};
    const f=modal('Share these excerpts?');for(const v of views)put(f,el('h3',v.title),el('pre',v.text));
    formAction(f,'Create reviewed connection',async()=>{const r=await api('create',body);const next=modal('Connection credential');note(next,'Use this credential in the agent’s connection settings.');
      const t=field(next,'Credential',input('password',r.token));t.readOnly=true;next.append(button('Copy credential',()=>copyText(r.token)));
      if(body.agent==='claude-code')next.append(button('Install for Claude Code',async()=>{if(preview)return nativeOnly('Install on this Mac');await api('install-claude',{token:r.token});flash('Installed.');}));
      if(body.agent==='dot')next.append(button('Use saved Dot tunnel',async()=>{if(preview)return nativeOnly('Dot tunnel');await api('restore-dot',{token:r.token});flash('Connected.');}));
    });
  });
});
