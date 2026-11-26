'use strict';
(() => {
  const api = PhoneVault, root = document.querySelector('#app'), notice = document.querySelector('#notice');
  let vault = null, page = 'home', selected = '', request = 0, timer, busy = false, hiddenSince = 0;
  let sample = null;
  function node(tag, text, cls) {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }
  function say(text) {
    clearTimeout(timer); notice.textContent = text; notice.hidden = !text;
    if (text) timer = setTimeout(() => { notice.hidden = true; }, 6500);
  }
  function button(label, fn, cls = 'secondary') {
    const b = node('button', label, cls); b.type = 'button';
    b.onclick = async () => {
      if (busy) return;
      b.disabled = true; busy = true;
      try { await fn(); } catch (e) { say(e.message || 'Could not finish this request.'); }
      finally { busy = false; b.disabled = false; }
    };
    return b;
  }
  const info = (el, text) => el.append(node('p', text, 'hint'));
  function field(parent, text, type = 'text') {
    const label = node('label', text), input = node(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.className = 'field'; input.autocapitalize = type === 'password' ? 'none' : 'sentences';
    label.append(input); parent.append(label); return input;
  }
  function check(parent, text, checked = false) {
    const label = node('label', undefined, 'check'), cb = node('input'); cb.type = 'checkbox'; cb.checked = checked;
    label.append(cb, node('span', text)); parent.append(label); return cb;
  }
  function group() { const g = node('div', undefined, 'group'); root.append(g); return g; }
  function link(host, title, dest, ref) { host.append(button(title, () => go(dest, ref), 'row')); }
  const state = () => vault.state;
  const lookup = (key, ref = selected) => state()[key].find(row => row.id === ref);
  const needsVault = key => !['home','privacy','context','pair','sample','agents','mac','excerpt'].includes(key);
  const macSetup = 'https://try-airlock.parv223885.chatgpt.site/#mac';
  const macDownload = 'https://try-airlock.parv223885.chatgpt.site/Airlock-Mac.zip';
  const pages = {
    home: ['Airlock'], sample: ['Sample workspace'], agents: ['Connect agent','home'], mac:['Mac setup','agents'],
    excerpt:['Share an excerpt','context'], sessions:['Local test sessions','privacy'], newAgent:['New test session','sessions'],
    session:['Agent access','sessions'], try:['Test session','session'], scope:['Shared records','session'],
    revoke:['Revoke session','session'], context:['Context & memory','home'], memories:['Memories','context'],
    add:['Add memory','memories'], memory:['Memory','memories'], remove:['Remove memory','memory'],
    proposals:['Proposed changes','context'], privacy:['Privacy & connections','home'],
    protection:['Data protection','privacy'], pair:['Pair this iPhone','privacy']
  };
  function header(title, parent) {
    if (parent) root.append(button('‹ ' + pages[parent][0], () => go(parent), 'back'));
    root.append(node('h1', title)); document.title = title === 'Airlock' ? title : title + ' · Airlock';
  }
  function startSample() {
    vault = null; sample = api.createSample(); return go('sample', '');
  }
  function exitSample(destination = 'home') {
    if (location.hash === '#sample') history.replaceState(null, '', location.pathname + location.search);
    sample = null; return go(destination, '');
  }
  async function showSample(ref) {
    const demo = sample;
    const agent = demo.agents.find(a => a.id === ref) || demo.agents[0];
    info(root, 'Switch agents to see which memories each can read. Changes in this sample last until you leave.');
    const choices = node('div', undefined, 'agent-choices');
    choices.setAttribute('role', 'group'); choices.setAttribute('aria-label', 'Test agent');
    for (const a of demo.agents) {
      const choice = button(a.name, () => go('sample', a.id), 'choice');
      choice.setAttribute('aria-pressed', String(a.id === agent.id)); choices.append(choice);
    }
    root.append(choices, node('h2', 'What this agent can read'));
    const result = node('section'); result.setAttribute('aria-live','polite'); root.append(result);
    try {
      for (const row of await demo.read(agent.id)) result.append(node('p', row, 'result'));
    } catch (error) {
      if (!agent.revoked) throw error;
      result.append(node('p', 'Access revoked.', 'result')); return;
    }
    result.append(button('Revoke access', () => { demo.revoke(agent.id); return go('sample', agent.id); }, 'danger'));
  }
  function external(host, label, url, cls = 'secondary') {
    const a = node('a', label, cls + ' external');
    a.href = url; a.rel = 'noreferrer'; host.append(a);
  }
  async function copyText(text, feedback, fallback) {
    try {
      await navigator.clipboard.writeText(text);
      say(feedback);
    } catch {
      fallback.readOnly = true; fallback.hidden = false; fallback.value = text;
      fallback.focus(); fallback.select(); say('Select Copy to use the highlighted text.');
    }
  }
  function macHandoff(label) {
    const manual = node('textarea', undefined, 'field'); manual.hidden = true;
    manual.setAttribute('aria-label', 'Mac setup link');
    const send = button(label, async () => {
      if (navigator.share) {
        try { await navigator.share({title:'Airlock for Mac', url:macSetup}); return; }
        catch (error) { if (error.name === 'AbortError') return; }
      }
      await copyText(macSetup, 'Setup link copied. Open it on your Mac.', manual);
    }, 'primary');
    root.append(send, manual);
  }
  function showMacSetup() {
    const steps = node('ol', undefined, 'steps');
    for (const text of ['Open Airlock on your Mac and choose Connect agent.', 'Choose Connect & open Codex, Connect & open Cursor, or Other agents.']) {
      steps.append(node('li', text));
    }
    root.append(steps);
    const phone = window.matchMedia('(pointer: coarse)').matches;
    if (phone) macHandoff('Send setup link to Mac');
    external(root, 'Download Airlock for Mac', macDownload, phone ? 'secondary' : 'primary');
  }
  function showExcerpt(generation) {
    info(root, 'Review a filtered note, then paste it into any agent. This shares it once.');
    const input = field(root, 'Text to share', 'textarea');
    input.maxLength = 4000; input.autocomplete = 'off'; input.spellcheck = false;
    const section = node('section'); section.setAttribute('aria-live', 'polite');
    const review = button('Review excerpt', async () => {
      input.readOnly = true;
      let output;
      try { output = await api.previewExcerpt(input.value, vault); }
      catch (error) { input.readOnly = false; throw error; }
      if (generation !== request) return;
      review.hidden = true;
      const approved = field(section, 'Text to copy', 'textarea');
      approved.value = output; approved.readOnly = true;
      section.append(button('Copy reviewed text', () => copyText(output, 'Copied. Paste it into your agent.', approved), 'primary'),
        button('Edit', () => { section.replaceChildren(); input.readOnly = false; review.hidden = false; input.focus(); }));
    }, 'primary');
    root.append(review, section);
  }
  function showPairing() {
    info(root, 'On your Mac, open Privacy & connections → Pair iPhone. Choose what to share, then scan the QR code or paste the pairing link here.');
    const input = field(root, 'Pairing link from your Mac', 'url'); input.autocomplete = 'off';
    input.autocapitalize = 'none'; input.spellcheck = false;
    const next = node('div');
    input.oninput = () => next.replaceChildren();
    root.append(button('Check link', () => {
      next.replaceChildren();
      const raw = input.value.trim();
      const match = raw.match(/^https:\/\/((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?(?::[0-9]{1,5})?)\/phone#pair=[A-Za-z0-9_-]{43}$/);
      const invalid = 'Paste the complete one-time pairing link from your Mac.';
      if (!match || raw.length > 400) throw Error(invalid);
      let url;
      try { url = new URL(raw); } catch { throw Error(invalid); }
      if (url.port === '0' || /\.(?:localhost|local|internal|invalid)$/.test(url.hostname)) throw Error(invalid);
      input.value = '';
      info(next, 'Open the address shown on your Mac, then tap Connect to Mac.');
      external(next, 'Open ' + url.host, url.href, 'primary');
    }), next);
  }
  async function go(key, ref = selected) {
    if (!pages[key]) key = 'home';
    const generation = ++request; page = key; selected = ref; say('');
    root.replaceChildren(); root.className = key === 'home' ? 'home' : '';
    if (!vault && (needsVault(key) || key === 'excerpt')) {
      const available = await api.exists();
      if (generation !== request) return;
      if (needsVault(key) || available) {
        header('Your iPhone vault', pages[key][1]);
        info(root, available ? 'Open your local vault with its passphrase.' :
          'Choose a passphrase to encrypt memories in this browser. Keep it safe. Clearing website data removes this vault.');
        const pass = field(root, 'Passphrase', 'password'); pass.autocomplete = available ? 'current-password' : 'new-password';
        const confirm = available ? null : field(root, 'Confirm passphrase', 'password');
        if (confirm) { confirm.autocomplete = 'new-password'; info(root, 'Use at least 12 characters.'); }
        root.append(button(available ? 'Unlock vault' : 'Create vault', async () => {
          if (confirm && pass.value !== confirm.value) throw Error('The passphrases differ.');
          const opened = await api.open(pass.value, !available);
          if (generation !== request) return;
          pass.value = ''; if (confirm) confirm.value = '';
          vault = opened; await go(key, ref);
        }, 'primary'));
        return;
      }
    }
    if (key === 'sample') root.append(button('Exit sample', exitSample, 'back'));
    header(pages[key][0], pages[key][1]);
    if (key === 'home') {
      const mark = node('span', undefined, 'mark'); mark.setAttribute('aria-hidden','true');
      root.querySelector('h1').prepend(mark);
      const nav = node('nav'); root.append(nav);
      link(nav, 'Connect agent','agents'); link(nav,'Context & memory','context'); link(nav,'Privacy & connections','privacy');
      root.append(button('Try a sample', startSample, 'sample-entry'));
    } else if (key === 'sample') {
      await showSample(ref);
      if (generation === request) root.append(button('Connect my agent', () => exitSample('agents'), 'primary'));
    } else if (key === 'agents') {
      if (window.matchMedia('(pointer: coarse)').matches) {
        info(root, 'Agent connections run on your Mac. Send yourself the setup link to continue there.');
        macHandoff('Set up on Mac');
      } else {
        info(root, 'The Mac app connects your agent and lets you choose which memories it can read.');
        external(root, 'Download Airlock for Mac', macDownload, 'primary');
      }
    } else if (key === 'mac') {
      showMacSetup();
    } else if (key === 'excerpt') {
      showExcerpt(generation);
    } else if (key === 'sessions') {
      info(root, 'Test permissions in this browser using your iPhone vault.');
      const g = group();
      state().agents.filter(a => !a.revoked).forEach(a => link(g, a.name, 'session', a.id));
      root.append(button('New test session', () => go('newAgent'), 'primary'));
    } else if (key === 'newAgent') {
      const name = field(root, 'Session name'); name.placeholder = 'e.g. Research assistant';
      root.append(button('Create session', async () => {
        let ref; await api.changed(vault, s => { ref = api.addAgent(s, name.value); });
        await go('session', ref);
      }, 'primary'));
    } else if (['session','try','scope','revoke'].includes(key)) {
      const a = lookup('agents');
      if (!a || a.revoked) { await go('sessions'); say('Session revoked.'); return; }
      if (key === 'session') {
        root.querySelector('h1').textContent = a.name;
        info(root, a.selected.length + ' shared ' + (a.selected.length === 1 ? 'record' : 'records') + '. Local test session.');
        const g = group(); link(g, 'Shared records', 'scope'); link(g, 'Try session', 'try'); link(g, 'Revoke session', 'revoke');
      } else if (key === 'scope') {
        info(root, 'Choose what ' + a.name + ' can read. Device-only memories stay private.');
        const eligible = state().records.filter(r => !r.private);
        if (!eligible.length) info(root, 'No shareable memories yet. Add one in Context & memory.');
        const choices = eligible.map(r => [r.id, check(root, r.text, a.selected.includes(r.id))]);
        root.append(button('Save access', async () => {
          await api.changed(vault, s => api.setScope(s, a.id, choices.filter(([, cb]) => cb.checked).map(([ref]) => ref)));
          await go('session'); say('Access saved.');
        }, 'primary'));
      } else if (key === 'revoke') {
        info(root, 'End ' + a.name + '’s access and discard its pending proposals.');
        root.append(button('Revoke access', async () => {
          await api.changed(vault, s => api.revoke(s, a.id)); await go('sessions'); say('Session revoked.');
        }, 'danger'));
      } else {
        root.querySelector('h1').textContent = a.name;
        info(root, 'Run a local request to see exactly what this session receives.');
        const result = node('section'); result.setAttribute('aria-live', 'polite');
        root.append(button('Read shared memory', async () => {
          const rows = await api.read(vault, a.id);
          if (generation !== request) return;
          result.replaceChildren(node('h2', 'Session result'));
          if (!rows.length) info(result, 'No shared records.');
          rows.forEach(t => result.append(node('p', t, 'result')));
        }, 'primary'), result);
        const note = field(root, 'Propose a memory', 'textarea');
        root.append(button('Send for review', async () => {
          await api.changed(vault, s => api.propose(s, a.id, note.value)); note.value = ''; say('Proposal awaits owner review.');
        }));
      }
    } else if (key === 'context') {
      const g = group(); link(g,'Memories','memories'); link(g,'Share an excerpt','excerpt'); link(g,'Proposed changes','proposals');
    } else if (key === 'memories') {
      const g = group();
      if (!state().records.length) info(g,'No memories on this iPhone.');
      state().records.forEach(r => link(g, r.text.length > 90 ? r.text.slice(0, 90) + '…' : r.text, 'memory', r.id));
      root.append(button('Add memory', () => go('add'), 'primary'));
    } else if (key === 'add') {
      const text = field(root, 'Memory', 'textarea'); text.maxLength = 4000;
      const local = check(root, 'Device only');
      root.append(button('Save memory', async () => {
        await api.changed(vault, s => api.addRecord(s, text.value, local.checked)); await go('memories');
      }, 'primary'));
    } else if (key === 'memory' || key === 'remove') {
      const r = lookup('records');
      if (!r) return go('memories');
      root.append(node('p', r.text, 'record'));
      if (key === 'memory') {
        info(root, r.private ? 'Device only' : 'Available to explicitly selected sessions.');
        root.append(button('Remove memory', () => go('remove'), 'danger'));
      } else {
        info(root, 'Remove this memory from the vault and all future reads.');
        root.append(button('Confirm removal', async () => {
          await api.changed(vault, s => { s.records = s.records.filter(x => x.id !== r.id); s.agents.forEach(a => { a.selected = a.selected.filter(x => x !== r.id); }); });
          await go('memories');
        }, 'danger'));
      }
    } else if (key === 'proposals') {
      if (!state().proposals.length) info(root, 'No changes waiting for review.');
      for (const p of state().proposals) {
        const row = node('article', undefined, 'record'); row.append(node('p', p.text), node('span', 'From ' + lookup('agents', p.agent).name, 'quiet'));
        for (const approved of [true, false]) row.append(button(approved ? 'Approve' : 'Decline', async () => {
          await api.changed(vault, s => api.decide(s, p.id, approved)); await go('proposals');
        })); root.append(row);
      }
    } else if (key === 'privacy') {
      const g = group(); link(g, 'Pair this iPhone', 'pair'); link(g, 'Data protection', 'protection'); link(g, 'Local test sessions', 'sessions');
      if (vault) g.append(button('Lock iPhone vault', () => lock(), 'row'));
    } else if (key === 'protection') {
      info(root, 'Test-session reads replace detected emails and phone numbers with session-specific tokens. Protected phrases and recognized credentials are withheld. Free text may still identify you.');
      const phrases = field(root, 'Always hide these phrases', 'textarea');
      phrases.value = state().phrases.join('\n');
      root.append(button('Save phrases', async () => {
        const entries = [...new Set(phrases.value.split('\n').map(x => x.trim()).filter(Boolean))];
        if (entries.length > 80 || entries.some(x => x.length > 150)) throw Error('Use up to 80 phrases of 150 characters each.');
        await api.changed(vault, s => { s.phrases = entries; }); say('Phrases saved.');
      }, 'primary'));
    } else if (key === 'pair') {
      showPairing();
    }
  }
  function lock() { vault = null; sample = null; selected = ''; return go('home'); }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) hiddenSince = Date.now();
    else if ((vault || page === 'excerpt' || page === 'pair') && hiddenSince && Date.now() - hiddenSince > 60000) lock();
  });
  window.addEventListener('pagehide', lock);
  window.addEventListener('pageshow', e => { if (e.persisted) lock(); });
  const routes = {'#connect':'agents', '#mac':'mac', '#pair':'pair'};
  function openRoute() {
    if (location.hash === '#sample') return startSample();
    sample = null;
    return go(routes[location.hash] || 'home', '');
  }
  window.addEventListener('hashchange', () => openRoute().catch(e => say(e.message)));
  openRoute().catch(e => say(e.message));
})();
