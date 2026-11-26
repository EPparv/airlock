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
    byId('connect').hidden = true; byId('pair-help').textContent = 'Open Airlock on your Mac and choose Privacy & connections → Pair iPhone.';
    byId('scope').textContent = ''; byId('topic').value = ''; byId('more').hidden = true;
    byId('actions').replaceChildren(); byId('records').replaceChildren();
  }
  async function post(action, body) {
    const version = generation;
    const headers = {'Content-Type':'application/json'};
    if (session) headers.Authorization = 'Bearer ' + session;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let reply, data;
    try {
      reply = await fetch('/phone/' + action, {method:'POST', headers, body:JSON.stringify(body),
        credentials:'omit', mode:'same-origin', cache:'no-store', redirect:'error',
        // WebKit uses this policy to populate Origin on same-origin POSTs.
        // Send only the bridge origin, never the pairing URL or its fragment.
        signal:controller.signal, referrerPolicy:'origin'});
      if ((reply.headers.get('Content-Type') || '').includes('application/json')) data = await reply.json();
    } catch {
      if (version !== generation) throw Error('Connection closed.');
      throw Error(action === 'request' ? 'The Mac didn’t confirm the request. Check actions before trying again.' :
        'This iPhone couldn’t reach Airlock. Check your connection and keep Airlock open and unlocked on your Mac.');
    } finally {
      clearTimeout(timeout);
    }
    if (version !== generation) throw Error('Connection closed.');
    if (reply.status === 401 || (action === 'pair' && reply.status === 403)) {
      clear();
      throw Error('This phone connection has closed. Use Pair iPhone on your Mac to get a new link.');
    }
    if (reply.status === 503 && data?.closed === true) {
      clear();
      throw Error('The Mac connection is unavailable. Unlock Airlock and open a fresh pairing link.');
    }
    if (reply.status >= 500) {
      throw Error(action === 'request' ? 'The bridge didn’t confirm the request. Check actions before trying again.' :
        'The bridge couldn’t reach your Mac. Keep Airlock open and unlocked, then try again.');
    }
    if (reply.status === 429) throw Error('The connection is receiving too many requests. Wait a moment and try again.');
    if (!reply.ok || !data || typeof data !== 'object' || Array.isArray(data)) {
      throw Error(typeof data?.error === 'string' ? data.error :
        'The link did not return an Airlock response. Check that the HTTPS bridge is running on your Mac.');
    }
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
    let status;
    if (!session) {
      const paired = await post('pair',{code});
      if (!/^[A-Za-z0-9_-]{43}$/.test(paired.session || '')) {
        throw Error('Airlock didn’t return a phone session. Get a new pairing link on your Mac.');
      }
      code = '';
      session = paired.session;
      status = paired;
    }
    // Older Macs send the record count separately. A retry resumes the issued
    // session even when that second request lost its response.
    if (!Number.isInteger(status?.count)) status = await post('status',{});
    if (!Number.isInteger(status.count) || !Number.isFinite(status.expires)) {
      throw Error('This Mac returned an incomplete connection status. Try connecting again.');
    }
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
    try {
      await post('disconnect',{});
      notice('Disconnected.');
    } catch {
      notice('Access cleared on this iPhone. Revoke the phone connection in Airlock on your Mac to end it there.');
    } finally {
      clear();
    }
  });
  window.addEventListener('pagehide', clear);
})();
