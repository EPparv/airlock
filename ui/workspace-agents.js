'use strict';
const localAgents = ['codex', 'cursor', 'claude-desktop', 'claude-code', 'vscode', 'gemini-cli', 'muse-code', 'openclaw'];
const cloudAgents = ['chatgpt', 'muse', 'manus', 'ironclaw', 'custom'];
const knownAgent = agent => localAgents.includes(agent) || cloudAgents.includes(agent) || agent === 'dot' || agent === 'mcp';
const labelForAgent = agent => names[agent] || cloudClients[agent];
const pickerAction = agent => agent === 'mcp' || agent === 'custom' ? 'Set up' : 'Connect';
let launchableAgents;

async function launchOptions() {
  if (preview) return [];
  if (!launchableAgents) {
    const result = await (personal ? api : testAPI)('workspace-launch-options');
    launchableAgents = result.agents;
  }
  return launchableAgents;
}

async function drawAgentPicker(host) {
  const available = await launchOptions();
  note(host, preview ? 'Try a sample connection with fictional data.' :
    'Choose an agent to open it. New connections share no memories. Existing permissions carry over.');
  const search = input('search');
  search.className = 'search agent-search';
  search.placeholder = 'Find an agent';
  search.setAttribute('aria-label', 'Find an agent');
  host.append(search);
  const sections = [];
  const groups = [
    ['On this Mac', [...localAgents, 'mcp']],
    ['Online', ['chatgpt', 'muse', 'manus', 'dot', 'ironclaw', 'custom']]
  ];
  for (const [label, agents] of groups) {
    const section = el('section', null, 'agent-group');
    section.append(el('h2', label, 'section'));
    const list = el('div', null, 'agent-list');
    section.append(list);
    host.append(section);
    const rows = agents.map(agent => {
      const name = labelForAgent(agent);
      const row = button('', () => selectAgent(agent), 'agent-option');
      row.setAttribute('aria-label', name);
      row.dataset.agent = agent;
      row.append(el('span', name), el('span', preview ? 'Try' : pickerAction(agent), 'agent-option-action'));
      list.append(row);
      return row;
    });
    sections.push({section,rows});
  }
  const none = el('p', 'No matching agents.', 'empty');
  none.hidden = true;
  host.append(none);
  search.oninput = () => {
    const query = search.value.trim().toLowerCase();
    let any = false;
    for (const {section, rows} of sections) {
      for (const row of rows) row.hidden = !row.getAttribute('aria-label').toLowerCase().includes(query);
      section.hidden = rows.every(row => row.hidden);
      any ||= !section.hidden;
    }
    none.hidden = any;
  };
  if (available.length) {
    const setup = details(host, 'Advanced setup');
    const profile = field(setup, 'Choose an app', select(localAgents.map(key => [key,names[key]])));
    setup.append(button('Configure access or profile', () => go('agent', {agent:profile.value, from:'connect'})));
  }
}
addPage('connect', 'Connect agent', 'home', drawAgentPicker, false);
// Older bookmarks still open the full directory.
addPage('other-agents', 'Connect agent', 'home', drawAgentPicker, false);

function useDirectoryBack(host, options) {
  if (options.from === 'connect' || options.from === 'other-agents') {
    host.closest('.page').querySelector('.back').replaceWith(button('Connect agent', () => go('connect'), 'back'));
  }
}

async function selectAgent(agent) {
  if (!knownAgent(agent)) throw Error('Choose an agent in the list.');
  if (preview) {
    if (cloudAgents.includes(agent) && agent !== 'ironclaw') return go('remote-create', {vendor:agent, from:'connect'});
    return go('agent', {agent, from:'connect'});
  }
  if (!personal) return enterPersonal('connect', {}, agent);
  return startAgentConnection(agent);
}

function linkStatus(status) {
  if (status.status === 'revoked') return 'Access revoked.';
  if (status.status === 'expired') return 'This connection has expired or reached its request limit.';
  if (status.last_context_read != null) return 'Context requested ' + when(status.last_context_read) + '.';
  if (status.last_call != null) return 'Airlock answered this connection’s tool call ' + when(status.last_call) + '.';
  if (status.last_discovery != null) return 'Agent found Airlock’s tools. Waiting for its first tool call.';
  return 'Waiting for the agent’s first tool call.';
}

function watchConnection(host, id, initial) {
  const result = el('p', linkStatus(initial), 'hint');
  result.setAttribute('role', 'status');
  host.append(result);
  const visible = () => result.isConnected && (!result.closest('dialog') || result.closest('dialog').open);
  async function update() {
    const status = await api('client-status', {id});
    if (visible()) result.textContent = linkStatus(status);
    return status.status === 'waiting' && status.last_call == null;
  }
  // A newly opened client can call back while Airlock is behind its window.
  let attempts = 0;
  async function poll() {
    if (!visible()) return;
    try {
      if (await update() && visible() && ++attempts < 24) setTimeout(poll, 5000);
    } catch {
      if (visible()) result.textContent = 'Could not check this connection. Open Airlock to try again.';
    }
  }
  if (!initial.last_call && !initial.last_context_read && !['expired','revoked'].includes(initial.status)) {
    setTimeout(poll, 2500);
  }
  return update;
}

function configuration(host, response) {
  const value = response.client_config || response.config;
  if (!value) return;
  const box = details(host, 'Manual configuration', null, true);
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  put(box, el('pre', text), button('Copy configuration', () => copyText(text)));
}

async function finishLocalConnection(agent, response) {
  if (preview) {
    await go('connections');
    const f = modal('Connection added to preview');
    note(f, 'These permissions apply to this preview.');
    f.append(button('Close', close, 'primary'));
    return;
  }
  if (response.installed && (await launchOptions()).includes(agent)) {
    return openSavedAgent(agent, response.id);
  }
  return showHandoff(agent, {id:response.id, method:'manual', message:response.message});
}

async function showHandoff(agent, result) {
  if (result.needsReview && agent === 'dot' && result.method === 'setup') return go('dot');
  // History contains only display data and a grant id; credentials and configuration stay in the owner API.
  return go('agent-handoff', {agent, id:result.id || '', opened:result.opened === true,
    method:result.needsReview ? 'review' : result.method, message:result.message,
    previousStatus:result.previousStatus || null});
}

async function openSavedAgent(agent, id) {
  const result = await api('workspace-open-client', {agent, id, approved:true});
  return showHandoff(agent, result);
}

async function startAgentConnection(agent) {
  if (connectingAgent) return;
  connectingAgent = true;
  const row = document.querySelector('.agent-option[data-agent="' + agent + '"]');
  if (row) {
    row.querySelector('.agent-option-action').textContent = pickerAction(agent) === 'Set up' ? 'Preparing…' : 'Opening…';
    row.setAttribute('aria-busy', 'true');
  }
  try {
    if (cloudAgents.includes(agent)) return await connectRemoteNow(agent);
    if (!(await launchOptions()).includes(agent)) {
      return await showHandoff(agent, {method:'mac', message:'Open Airlock on your Mac to connect ' + names[agent] + '.'});
    }
    const result = await api('workspace-quick-connect', {agent, approved:true});
    return await showHandoff(agent, result);
  } catch (error) {
    return await showHandoff(agent, {method:'retry', message:error.message || 'The app could not open.'});
  } finally {
    connectingAgent = false;
    if (row?.isConnected) {
      row.querySelector('.agent-option-action').textContent = pickerAction(agent);
      row.removeAttribute('aria-busy');
    }
  }
}

function watchHandoff(host, opt, headline, detail) {
  let calls = 0;
  const before = opt.previousStatus || {};
  const name = labelForAgent(opt.agent);
  const waitingTitle = headline.textContent;
  const started = Date.now();
  let recovery, discovered = false;
  function clearRecovery() {
    recovery?.remove();
    recovery = null;
  }
  function showRecovery() {
    if (recovery) return;
    const guidance = {
      cursor:'If Cursor asks, enable Airlock in MCP settings, then send the prepared request.',
      codex:'In Codex settings, check that the Airlock MCP server is enabled, then send the prepared request.',
      'claude-desktop':'If Airlock is missing from Claude’s developer settings, quit Claude Desktop with ⌘Q, then reopen it here.',
      vscode:'In VS Code, start Airlock in the MCP server list, then choose Run in Chat in the open prompt file.',
      'muse-code':'If Terminal is waiting, press Return to send the prepared status request.',
      dot:'Open the Dot that uses your Airlock tunnel and allow its status request.'
    };
    const hint = opt.method === 'check' ? 'Review the connection check in Terminal. Start a session in ' + name + ' to use Airlock.' : guidance[opt.agent];
    if (!hint) return;
    recovery = el('div');
    note(recovery, hint);
    if (opt.agent === 'claude-desktop') {
      recovery.append(button('Open Claude Desktop again', () => openSavedAgent(opt.agent, opt.id), 'plain'));
    }
    detail.parentElement.after(recovery);
  }
  async function poll() {
    if (!host.isConnected) return;
    try {
      const status = await api('client-status', {id:opt.id});
      if (!host.isConnected) return;
      if (['expired','revoked'].includes(status.status)) {
        clearRecovery();
        headline.textContent = 'Access ended';
        detail.textContent = linkStatus(status);
        return;
      }
      if (status.last_call != null && status.last_call !== before.last_call) {
        clearRecovery();
        headline.textContent = 'Connected';
        detail.textContent = name + ' called an Airlock tool.';
        return;
      }
      if (status.last_discovery != null && status.last_discovery !== before.last_discovery) {
        clearRecovery();
        discovered = true;
        headline.textContent = 'Connected';
        detail.textContent = name + ' found Airlock’s tools.';
      } else if (!discovered) {
        const quiet = opt.opened && Date.now() - started >= 20000;
        headline.textContent = quiet ? 'No response yet' : waitingTitle;
        if (quiet) showRecovery();
      }
    } catch {
      if (host.isConnected && !discovered) {
        clearRecovery();
        headline.textContent = 'Connection status unavailable';
      }
    }
    calls++;
    if (host.isConnected) setTimeout(poll, calls < 8 ? 1000 : calls < 25 ? 5000 : 15000);
  }
  poll();
}

addPage('agent-handoff', 'Connection', 'connect', async (host, opt, bar) => {
  if (!knownAgent(opt.agent) || preview) return go('connect');
  const name = labelForAgent(opt.agent);
  bar.querySelector('h1').textContent = name;
  const headline = el('h2', opt.opened ? 'Waiting for ' + name :
    opt.method === 'manual' || opt.method === 'review' || opt.method === 'mac' ? 'Finish setup' : 'Couldn’t open ' + name, 'handoff-status');
  const detail = el('p', opt.message || '', 'handoff-detail');
  const surface = el('div', null, 'handoff-result');
  surface.setAttribute('role', 'status');
  surface.append(headline, detail);
  host.append(surface);
  if (opt.method === 'manual' && opt.id) {
    const result = await api('workspace-manual-config', {id:opt.id});
    configuration(host, result);
  } else if (opt.method === 'review') {
    host.append(button('Review connection', () => go('agent', {agent:opt.agent, id:opt.id, openHelp:true}), 'primary'));
    return;
  } else if (opt.method === 'mac') {
    host.append(previewSetupLink());
  } else if (!opt.opened) {
    const actions = el('div', null, 'buttons');
    actions.append(button('Try again', () => opt.id ? openSavedAgent(opt.agent, opt.id) : selectAgent(opt.agent), 'primary'));
    if (opt.method === 'unavailable' && localAgents.includes(opt.agent)) {
      actions.append(button('Setup help', async () => {
        const result = await api('workspace-agent-help', {agent:opt.agent, approved:true});
        if (!result.opened) throw Error(result.message || 'Setup help could not open.');
      }));
    }
    host.append(actions);
  }
  if (opt.opened && opt.id) watchHandoff(host, opt, headline, detail);
  if (opt.id) host.append(button('Manage access', () => go('agent', {agent:opt.agent,id:opt.id}), 'plain handoff-manage'));
});

addPage('connections', 'Connected agents', 'privacy', async (host, options, bar) => {
  bar.append(button('Connect agent', () => go('connect')));
  const ws = await api('workspace-state');
  const current = ws.agents.filter(active),
    past = ws.agents.filter(a => !active(a));
  const list = el('div', null, 'menu');
  host.append(list);
  if (!current.length) empty(list, 'No agents connected.');
  for (const a of current) item(list, connectionName(a), a.scope ? (a.scope.records.length +
      ' selected · ' + (a.last_read ? 'Last read ' + when(a.last_read) : a.last_call != null ? 'Tool call received' : a.last_discovery != null ? 'Tools discovered' : 'Awaiting first call')) :
    'Existing ' + a.mode + ' connection', () => go('agent', {
      id: a.id,
      agent: a.name
    }));
  if (past.length) {
    const last = details(host, 'Past connections');
    for (const a of past) item(last, connectionName(a), a.status === 'expired' ? 'Expired' : 'Revoked',
      () => go('agent', {
        id: a.id,
        agent: a.name
      }));
  }
});

function limits(form) {
  const l = field(form, 'Expires in', select([
    ['3600', '1 hour'],
    ['86400', '1 day'],
    ['604800', '7 days'],
    ['2592000', '30 days']
  ], '86400'));
  const c = field(form, 'Request limit', input('number', '100'));
  c.min = '1';
  c.max = '1000';
  return () => ({
    lifetime: Number(l.value),
    max_calls: Number(c.value)
  });
}

function revokeAgent(a) {
  confirmAction('Revoke ' + (connectionName(a)) + '?', 'This connection will lose access immediately.',
    'Revoke connection', async () => {
      await api('revoke', {
        id: a.id
      });
      await go('connections');
    }, true);
}
addPage('agent', 'Agent access', 'connect', async (host, opt, bar) => {
  const agent = opt.agent;
  useDirectoryBack(host, opt);
  if (!names[agent]) {
    empty(host, 'Choose an agent first.');
    host.append(button('Choose agent', () => go('connect')));
    return;
  }
  bar.querySelector('h1').textContent = names[agent];
  const [ws, available] = await Promise.all([api('workspace-state'), launchOptions()]);
  const previous = ws.agents.filter(a => a.name === agent && active(a));
  let existing = opt.id && ws.agents.find(a => a.id === opt.id && a.name === agent);
  if (!opt.id && !opt.createNew && localAgents.includes(agent) && previous.length) {
    if (previous.length === 1) existing = previous[0];
    else {
      const list = section(host, 'Existing connections');
      for (const a of previous) item(list, names[agent] + ' · ' + a.id.slice(-6),
        'Expires ' + when(a.expires), () => go('agent', {agent, id:a.id}));
      host.append(button('Create another connection', () => go('agent', {agent, from:opt.from, createNew:true})));
      return;
    }
  }
  if (opt.id && !existing) throw Error('This connection no longer exists.');
  if (existing) {
    bar.querySelector('h1').textContent = connectionName(existing);
    host.closest('.page').querySelector('.back').replaceWith(button('Connected agents', () => go(
      'connections'), 'back'));
    if (!preview && active(existing) && (localAgents.includes(agent) || agent === 'mcp' || agent === 'dot')) {
      if (available.includes(agent) && existing.installed === true) {
        host.append(button('Open ' + names[agent], () => openSavedAgent(agent, existing.id), 'primary'));
      }
      watchConnection(host, existing.id, {...existing, last_context_read:existing.last_read});
      const help = details(host, 'Connection help', null, !!opt.openHelp || existing.installed === false);
      if (existing.installed === false) help.append(button('Show configuration', async () => {
        const result = await api('workspace-manual-config', {id:existing.id});
        configuration(help, result);
      }));
      if (localAgents.includes(agent)) help.append(button('Repair setup', async () => {
        const result = await api('workspace-reconnect', {id:existing.id});
        await finishLocalConnection(agent, result);
      }));
    }
    const accessFacts = [
      ['Requests left', existing.remaining],
      ['Expires', when(existing.expires) || '—']
    ];
    if (preview || !localAgents.includes(agent) || !active(existing)) {
      accessFacts.unshift(['Status', active(existing) ? linkStatus({...existing,last_context_read:existing.last_read}) : existing.status]);
    }
    host.append(facts(accessFacts));
    if (!active(existing)) {
      host.append(button('Create new connection', () => go('agent', {
        agent, createNew:true
      })));
      return;
    }
  }
  if (agent === 'dot' && !existing) {
    const d = await api('saved-dot');
    if (!d.configured) {
      note(host, 'Dot needs a private MCP tunnel on this Mac.');
      host.append(button('Set up Dot', () => go('dot')));
      return;
    }
  }
  const form = el('div', null, 'form');
  host.append(form);
  const context = await api('client-context');
  const records = context.records || [],
    scope = existing?.scope;
  if (!existing) note(form, 'You can connect now and choose what to share later.');
  const choices = details(form, 'Shared records'),
    summary = choices.parentElement.querySelector('summary'),
    checks = [];
  if (!records.length) {
    note(choices, 'Your library is empty.');
    choices.append(button('Add a memory', () => addNote('memories')));
  } else {
    note(choices, 'Filtered excerpts let the agent read text. For a private task, you review the result before the agent receives it.');
  }
  const allowed = scope?.disclose_records ?? scope?.records ?? [];
  for (const r of records) {
    const selected = scope?.records?.includes(r.ref);
    const opts = [
      ['off', 'No access']
    ];
    if (!r.sensitive) opts.push(['excerpt', 'Filtered excerpt']);
    opts.push(['private', 'Private task only']);
    const value = selected ? (scope.disclose && allowed.includes(r.ref) && !r.sensitive ? 'excerpt' : scope
      .compute ? 'private' : 'off') : 'off';
    const control = field(choices, r.text.length > 180 ? r.text.slice(0, 180) + '…' : r.text, select(opts,
      value));
    checks.push([r, control]);
  }
  const count = () => {
    const n = checks.filter(([, c]) => c.value !== 'off').length;
    summary.textContent = 'Shared records · ' + n + ' selected';
  };
  for (const [, c] of checks) c.onchange = count;
  count();
  const advanced = details(form, 'More settings');
  const devices = advanced;
  const mail = check(devices, 'Request a follow-up to the selected email', existing?.device?.mail);
  const calendar = check(devices, 'Request a follow-up to recent meeting attendees', existing?.device
    ?.calendar);
  const proposals = check(devices, 'Propose memory updates', existing?.proposals);
  const compute = check(devices, 'Allow private tasks on selected records', scope?.compute);
  note(devices, 'Sending mail and releasing a private task result each require your approval.');
  const readLimits = existing ? null : limits(details(advanced, 'Connection limits',
    el('p', 'Access ends when either limit is reached.', 'hint')));
  let install;
  if (!existing && !preview && localAgents.includes(agent)) {
    const setup = details(advanced, 'Client settings');
    install = check(setup, 'Save to the default profile on this Mac', true);
    note(setup, 'For a custom profile, turn this off and copy the configuration after connecting.');
  }
  if (existing && !existing.scope) {
    note(form, 'Saving assigns the selected records to this existing connection.');
    const mode = existing.mode === 'automatic',
      modeName = mode ? 'Use reviewed excerpts only' : 'Use automatic context';
    form.append(button(modeName, () => confirmAction(modeName + '?', mode ?
      'Only previously reviewed excerpts will be available.' :
      'This gives the agent automatic filtered access to your whole shareable library and connected read-only Gmail.',
      modeName, async () => {
        await api('automatic', {
          identifier: existing.id,
          enabled: !mode,
          approved: true
        });
        await refresh();
      })));
    if (mode) {
      const legacy = details(form, 'Existing tool permissions');
      const exec = check(legacy, 'Run enabled local skill packages', existing.capabilities?.skill_execution);
      const updates = check(legacy, 'Allow shared note updates', existing.capabilities?.context_updates);
      legacy.append(button('Save tool permissions', async () => {
        await api('capabilities', {
          identifier: existing.id,
          skill_execution: exec.checked,
          context_updates: updates.checked
        });
        await refresh();
        flash('Tool permissions saved.');
      }));
    }
  }
  const connectLabel = () => (available.includes(agent) && install?.checked ? 'Connect & open ' : 'Connect ') + names[agent];
  const submit = formAction(form, existing ? 'Save access' : connectLabel(), async () => {
    const selected = checks.filter(([, c]) => c.value !== 'off');
    const response = await api('workspace-connect', {
      agent,
      identifier: existing?.id || '',
      selection: Object.fromEntries(selected.map(([r]) => [r.ref, r.text_hash])),
      excerpt_selection: selected.filter(([, c]) => c.value === 'excerpt').map(([r]) => r.ref),
      compute: compute.checked || selected.some(([, c]) => c.value === 'private'),
      proposals: proposals.checked,
      mail: mail.checked,
      calendar: calendar.checked,
      ...(install ? {install: install.checked} : {}),
      ...(readLimits ? readLimits() : {})
    });
    if (existing) {
      await go('connections');
      flash('Access saved.');
      return;
    }
    await finishLocalConnection(agent, response);
  });
  if (install) install.onchange = () => { submit.textContent = connectLabel(); };
  if (existing) form.append(button('Revoke connection', () => revokeAgent(existing), 'danger'));
});

addPage('dot', 'Dot tunnel', 'connect', async host => {
  const status = await api('saved-dot');
  note(host, status.configured ? 'A tunnel configuration is saved on this Mac.' :
    'Use the tunnel ID and runtime key from your private Dot connection.');
  const f = el('div', null, 'form');
  host.append(f);
  const id = field(f, 'Tunnel ID', input()),
    key = field(f, 'Runtime key', input('password')),
    token = field(f, 'Agent credential', input('password'));
  key.autocomplete = token.autocomplete = 'off';
  formAction(f, 'Save tunnel configuration', async () => {
    if (preview) return nativeOnly('Dot tunnel');
    await api('install-dot', {
      token: token.value,
      tunnel_id: id.value,
      runtime_key: key.value
    });
    await refresh();
    flash('Tunnel saved.');
  });
  f.append(button('Check tunnel', async () => {
    if (preview) return nativeOnly('Check tunnel');
    const r = await api('dot-status');
    note(f, r.message || r.status || 'Status checked.');
  }));
  if (status.configured) f.append(button('Reconnect saved setup', async () => {
    if (preview) return nativeOnly('Reconnect Dot');
    const r = await api('restore-dot');
    flash(r.message || 'Reconnected.');
  }));
});

addPage('excerpts', 'Reviewed excerpts', 'context', async host => {
  const form = el('div', null, 'form');
  host.append(form);
  const agent = field(form, 'Agent', select(Object.entries(names).map(([k, v]) => [k, v])));
  const purpose = field(form, 'Purpose', input());
  const source = field(form, 'Source', select([
    ['library', 'Local library'],
    ['gmail', 'Gmail']
  ]));
  const query = field(form, 'Search source', input('search')),
    matches = el('div'),
    selected = new Map();
  const chosen = el('div'),
    rules = limits(details(form, 'Connection limits'));

  function show() {
    chosen.replaceChildren();
    for (const [k, v] of selected) {
      const part = el('div', null, 'detail-block');
      chosen.append(part);
      const title = field(part, 'Shared title', input('text', v.title)),
        text = field(part, 'Exact text to share', el('textarea'));
      text.value = v.text;
      title.oninput = () => v.title = title.value;
      text.oninput = () => v.text = text.value;
      part.append(button('Remove', () => {
        selected.delete(k);
        show();
      }, 'plain'));
    }
  }
  form.append(button('Find records', async () => {
    if (!query.value.trim()) throw Error('Enter a search term.');
    const data = source.value === 'gmail' ? await api('gmail', {
      query: query.value
    }) : await api('library');
    matches.replaceChildren();
    const allowed = source.value === 'library' ? new Set((await api('client-context')).records.map(
      r => r.ref)) : null;
    const found = data.items.filter(r => !r.device_only && (!allowed || ((allowed.has(r.kind + ':' + r
      .source_id) || allowed.has(r.ref)) && r.text.toLowerCase().includes(query.value
      .toLowerCase()))));
    if (!found.length) empty(matches, 'No matching records.');
    for (const r of found.slice(0, 50)) item(matches, r.title || r.text.slice(0, 75), r.kind, () => {
      selected.set(r.kind + ':' + r.source_id, {
        kind: r.kind,
        source_id: r.source_id,
        title: r.title || r.kind,
        text: r.suggested || ''
      });
      show();
    });
  }), matches, chosen);
  formAction(form, 'Review connection', () => {
    if (!selected.size || !purpose.value.trim()) throw Error(
      'Enter a purpose and select at least one excerpt.');
    const views = Array.from(selected.values(), v => ({
        ...v
      })),
      body = {
        agent: agent.value,
        purpose: purpose.value,
        views,
        approved: true,
        ...rules()
      };
    const f = modal('Share these excerpts?');
    for (const v of views) put(f, el('h3', v.title), el('pre', v.text));
    formAction(f, 'Create reviewed connection', async () => {
      const r = await api('create', body);
      const next = modal('Connection credential');
      note(next, 'Use this credential in the agent’s connection settings.');
      const t = field(next, 'Credential', input('password', r.token));
      t.readOnly = true;
      next.append(button('Copy credential', () => copyText(r.token)));
      if (body.agent === 'claude-code') next.append(button('Install for Claude Code', async () => {
        if (preview) return nativeOnly('Install on this Mac');
        await api('install-claude', {
          token: r.token
        });
        flash('Installed.');
      }));
      if (body.agent === 'dot') next.append(button('Use saved Dot tunnel', async () => {
        if (preview) return nativeOnly('Dot tunnel');
        await api('restore-dot', {
          token: r.token
        });
        flash('Connected.');
      }));
    });
  });
});
