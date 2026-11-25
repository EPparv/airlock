'use strict';
(() => {
  const crypt = globalThis.crypto;
  const bytes = new TextEncoder();
  const maxEntries = 250;
  const b64 = value => {
    let out = '';
    const data = new Uint8Array(value);
    for (let offset = 0; offset < data.length; offset += 8192) out += String.fromCharCode(...data.subarray(offset, offset + 8192));
    return btoa(out);
  };
  const un64 = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
  const random = size => crypt.getRandomValues(new Uint8Array(size));
  const id = () => Array.from(random(16), b => b.toString(16).padStart(2, '0')).join('');
  const clean = (value, limit, label) => {
    if (typeof value !== 'string' || !value.trim() || value.trim().length > limit) throw Error('Enter ' + label + ' under ' + (limit + 1) + ' characters.');
    return value.trim();
  };
  const empty = () => ({records: [], agents: [], proposals: [], phrases: []});
  function dbOpen() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open('airlock-iphone-v1', 1);
      req.onupgradeneeded = () => req.result.createObjectStore('vault');
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(Error('Safari could not open local storage.'));
    });
  }
  async function envelope(expected, next) {
    const db = await dbOpen();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction('vault', next ? 'readwrite' : 'readonly');
        const store = tx.objectStore('vault');
        let current, conflict = false;
        const read = store.get('device');
        read.onsuccess = () => {
          current = read.result || null;
          if (!next) return;
          if ((current?.rev || 0) !== expected) { conflict = true; tx.abort(); return; }
          store.put(next, 'device');
        };
        tx.oncomplete = () => resolve(current);
        tx.onabort = () => reject(Error(conflict ? 'This vault changed in another tab. Lock and reopen it.' : 'Safari could not save the vault. Check device storage.'));
        tx.onerror = () => {};
      });
    } finally { db.close(); }
  }
  async function derive(pass, salt) {
    const material = await crypt.subtle.importKey('raw', bytes.encode(pass), 'PBKDF2', false, ['deriveKey']);
    return crypt.subtle.deriveKey({name:'PBKDF2', hash:'SHA-256', salt, iterations:600000}, material,
      {name:'AES-GCM', length:256}, false, ['encrypt','decrypt']);
  }
  const context = bytes.encode('Airlock iPhone vault / 1');
  async function pack(state, key, salt, rev) {
    const iv = random(12);
    const ciphertext = await crypt.subtle.encrypt({name:'AES-GCM', iv, additionalData:context}, key, bytes.encode(JSON.stringify(state)));
    return {format:1, rev, salt:b64(salt), iv:b64(iv), ciphertext:b64(ciphertext)};
  }
  async function open(pass, create) {
    if (!globalThis.isSecureContext || !crypt?.subtle || !globalThis.indexedDB) throw Error('Open this link in Safari over HTTPS.');
    if (!pass || pass.length > 1024 || (create && pass.length < 12)) throw Error('Use a passphrase of at least 12 characters.');
    const saved = await envelope();
    if (!!saved === create) throw Error(saved ? 'A vault already exists. Open it with its passphrase.' : 'Create a vault on this device first.');
    if (saved && saved.format !== 1) throw Error('This vault needs a newer version of Airlock.');
    const salt = saved ? un64(saved.salt) : random(16);
    const key = await derive(pass, salt);
    let state = empty();
    if (saved) {
      try {
        const clear = await crypt.subtle.decrypt({name:'AES-GCM', iv:un64(saved.iv), additionalData:context}, key, un64(saved.ciphertext));
        state = JSON.parse(new TextDecoder().decode(clear));
      } catch { throw Error('The vault could not be opened with that passphrase.'); }
    } else { await envelope(0, await pack(state, key, salt, 1)); }
    return {key, salt, state, rev:saved?.rev || 1};
  }
  async function changed(vault, edit) {
    const copy = JSON.parse(JSON.stringify(vault.state));
    edit(copy);
    const rev = vault.rev + 1;
    await envelope(vault.rev, await pack(copy, vault.key, vault.salt, rev));
    vault.state = copy; vault.rev = rev;
  }
  const find = (rows, reference) => {
    const row = rows.find(r => r.id === reference);
    if (!row) throw Error('This item is unavailable.');
    return row;
  };
  function agent(state, reference) {
    const a = find(state.agents, reference);
    if (a.revoked) throw Error('This session has been revoked.');
    return a;
  }
  function addRecord(state, text, isPrivate = false) {
    if (state.records.length >= maxEntries) throw Error('The vault holds up to 250 records.');
    const r = {id:id(), text:clean(text, 4000, 'a memory'), private:!!isPrivate};
    state.records.push(r); return r.id;
  }
  function addAgent(state, name) {
    name = clean(name, 60, 'a session name');
    if (state.agents.filter(a => !a.revoked).length >= 8) throw Error('Revoke a session before creating another.');
    if (state.agents.some(a => !a.revoked && a.name.toLowerCase() === name.toLowerCase())) throw Error('Use a different session name.');
    state.agents = state.agents.filter(a => !a.revoked || state.proposals.some(p => p.agent === a.id)).slice(-maxEntries);
    const a = {id:id(), name, revoked:false, selected:[], salt:b64(random(32))};
    state.agents.push(a); return a.id;
  }
  function setScope(state, reference, selected) {
    const a = agent(state, reference);
    if (selected.some(ref => find(state.records, ref).private)) throw Error('A device-only record cannot be shared.');
    a.selected = [...new Set(selected)];
  }
  function revoke(state, reference) {
    const a = agent(state, reference);
    a.revoked = true; a.selected = []; a.salt = '';
    state.proposals = state.proposals.filter(p => p.agent !== reference);
  }
  function propose(state, reference, value) {
    agent(state, reference);
    if (state.proposals.length >= maxEntries) throw Error('Review pending proposals first.');
    state.proposals.push({id:id(), agent:reference, text:clean(value, 4000, 'a proposal')});
  }
  function decide(state, reference, approved) {
    const p = find(state.proposals, reference);
    if (approved) { agent(state, p.agent); addRecord(state, p.text); }
    state.proposals = state.proposals.filter(x => x.id !== reference);
  }
  function hide(value, phrase) {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return value.replace(new RegExp(escaped, 'gi'), '[withheld]');
  }
  async function filtered(value, state, a) {
    let text = value;
    for (const phrase of [...state.phrases].sort((a, b) => b.length - a.length)) text = hide(text, phrase);
    text = text.replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g, '[credential withheld]')
      .replace(/\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|Bearer\s+[A-Za-z0-9_.+=/-]{6,})/gi, '[credential withheld]')
      .replace(/\b\d{3}-\d{2}-\d{4}\b/g, '[identifier withheld]');
    const values = /[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:\+?\d[\s().-]*){7,15}\d/gi;
    const key = await crypt.subtle.importKey('raw', un64(a.salt), {name:'HMAC', hash:'SHA-256'}, false, ['sign']);
    let out = '', last = 0;
    for (const match of text.matchAll(values)) {
      const raw = match[0], type = raw.includes('@') ? 'email' : 'phone';
      const normalized = type === 'email' ? raw.toLowerCase() : raw.replace(/\D/g, '');
      const signature = await crypt.subtle.sign('HMAC', key, bytes.encode(type + '|' + normalized));
      const token = Array.from(new Uint8Array(signature).slice(0, 8), b => b.toString(16).padStart(2, '0')).join('');
      out += text.slice(last, match.index) + '[' + type + '-' + token + ']';
      last = match.index + raw.length;
    }
    return out + text.slice(last);
  }
  function selectedRecords(state, a) {
    return Promise.all(state.records.filter(r => !r.private && a.selected.includes(r.id))
      .map(r => filtered(r.text, state, a)));
  }
  function createSample() {
    const state = empty();
    const writing = addRecord(state, 'Send the two-paragraph launch update to editor@example.com.');
    const planning = addRecord(state, 'The launch check-in is Friday at 10 am.');
    const writer = addAgent(state, 'Writing agent'), planner = addAgent(state, 'Planning agent');
    setScope(state, writer, [writing]); setScope(state, planner, [planning]);
    return {
      agents: state.agents,
      async read(reference) {
        const rows = await selectedRecords(state, agent(state, reference));
        agent(state, reference);
        return rows;
      },
      revoke: reference => revoke(state, reference)
    };
  }
  async function read(vault, reference) {
    const a = agent(vault.state, reference);
    const persist = await envelope();
    if (!persist || persist.rev !== vault.rev) throw Error('This vault changed in another tab. Lock and reopen it.');
    const revision = vault.rev;
    const items = await selectedRecords(vault.state, a);
    if (vault.rev !== revision || (await envelope())?.rev !== revision) throw Error('The permissions changed. Try again.');
    return items;
  }
  globalThis.PhoneVault = {exists:async () => !!(await envelope()), open, changed, addRecord, addAgent, setScope, revoke, propose, decide, read, filtered, createSample};
})();
