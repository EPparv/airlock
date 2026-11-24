'use strict';
(() => {
  const byId = id => document.getElementById(id);
  let code = new URLSearchParams(location.hash.slice(1)).get('pair') || '';
  if (location.hash) history.replaceState(null, '', location.pathname);
  let session = '', nextQuery = '', generation = 0;
  const notice = message => { byId('notice').textContent = message; };
  function clear() {
    ++generation;
    session = ''; code = ''; nextQuery = '';
    byId('connected').hidden = true; byId('welcome').hidden = false;
    byId('connect').hidden = true; byId('pair-help').textContent = 'Open Airlock on your Mac and choose Connect agent → Pair iPhone.';
    byId('scope').textContent = ''; byId('topic').value = ''; byId('more').hidden = true;
    byId('actions').replaceChildren(); byId('records').replaceChildren();
  }
  async function post(action, body) {
    const version = generation;
    const headers = {'Content-Type':'application/json'};
    if (session) headers.Authorization = 'Bearer ' + session;
    const reply = await fetch('/phone/' + action, {method:'POST', headers, body:JSON.stringify(body),
      credentials:'omit', cache:'no-store', redirect:'error', referrerPolicy:'no-referrer'});
    const data = await reply.json().catch(() => ({}));
    if (version !== generation) throw Error('Connection closed.');
    if (reply.status === 401 || reply.status === 503) clear();
    if (!reply.ok) throw Error(data.error || 'The connection is unavailable. Check Airlock on your Mac.');
    return data;
  }
  const guarded = handler => async event => {
    event.preventDefault();
    const target = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : event.currentTarget.querySelector('button');
    if (target?.disabled) return;
    if (target) target.disabled = true;
    notice('');
    try { await handler(); } catch (e) { notice(e.message || 'The request could not finish.'); }
    finally { if (target) target.disabled = false; }
  };
  if (/^[A-Za-z0-9_-]{43}$/.test(code)) {
    byId('pair-help').textContent = 'Connect to the records and actions selected on your Mac. Keep this tab open while using them.';
    byId('connect').hidden = false;
  }
  byId('connect').onclick = guarded(async () => {
    const paired = await post('pair',{code});
    code = ''; session = paired.session;
    const status = await post('status',{});
    byId('connected').hidden = false; byId('welcome').hidden = true;
    byId('scope').textContent = status.count + (status.count === 1 ? ' shared record' : ' shared records') +
      ' · Expires ' + new Date(status.expires * 1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
  });
  async function search(query, append) {
    const out = byId('records');
    if (!append) { out.replaceChildren(); nextQuery = ''; byId('more').hidden = true; }
    const data = await post('context',{query});
    for (const item of data.items) {
      const node=document.createElement('li');
      node.textContent=item.text; out.append(node);
    }
    nextQuery = data.next_query || ''; byId('more').hidden = !nextQuery;
    if (!out.children.length) notice('No matching shared records.');
  }
  byId('search-form').onsubmit = guarded(() => search(byId('topic').value.trim(), false));
  byId('more').onclick = guarded(() => search(nextQuery, true));
  async function actions() {
    const {actions:items} = await post('actions',{});
    const out = byId('actions'); out.replaceChildren();
    for (const item of items) {
      const node = document.createElement('li');
      node.textContent = item.label + ' · ' + item.status;
      if (['email','event','followup','api_write','file_append'].includes(item.kind) && item.status === 'ready') {
        const ask = document.createElement('button'); ask.textContent = 'Request Mac approval';
        ask.onclick = guarded(async () => {
          const result = await post('request',{reference:item.reference});
          await actions(); notice(result.status === 'pending' ? 'Waiting for approval on your Mac.' : 'Status updated.');
        });
        node.append(ask);
      }
      out.append(node);
    }
    if (!items.length) notice('No actions assigned to this iPhone.');
  }
  byId('refresh-actions').onclick = guarded(actions);
  byId('disconnect').onclick = guarded(async () => {
    await post('disconnect',{}); clear(); notice('Disconnected.');
  });
  window.addEventListener('pagehide', clear);
})();
