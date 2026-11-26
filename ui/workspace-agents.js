'use strict';
const desktopApps = ['codex', 'cursor'];
const localAgents = [...desktopApps, 'claude-desktop', 'claude-code', 'muse-code', 'gemini-cli', 'vscode', 'openclaw'];
const nativeLauncher = () => window.webkit?.messageHandlers?.airlockSettings;
const canOpen = agent => !preview && desktopApps.includes(agent) && !!nativeLauncher();
addPage('connect', 'Connect agent', 'home', host => {
  note(host, 'New connections share no memories. Reconnecting keeps the access you approved.');
  const list = el('div', null, 'menu');
  host.append(list);
  for (const agent of desktopApps) {
    if (canOpen(agent)) row(list, 'Connect & open ' + names[agent], () => connectDesktopNow(agent));
    else row(list, names[agent], () => go('agent', {agent}));
  }
  choose(list, 'Other agents', 'other-agents');
}, false);

addPage('other-agents', 'Other agents', 'connect', host => {
  const local = section(host, 'On this Mac');
  const online = section(host, 'Online');
  function entry(list, label, description, page, options) {
    const button = item(list, label, description, () => go(page, {...options, from:'other-agents'}));
    const subtitle = button.querySelector('.row-sub');
    subtitle.id = 'about-' + (options.agent || options.vendor);
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-describedby', subtitle.id);
  }
  for (const [agent, description] of [
    ['claude-desktop', 'Claude’s Mac app.'],
    ['claude-code', 'Claude in your terminal.'],
    ['gemini-cli', 'Gemini in your terminal.'],
    ['muse-code', 'Meta’s coding agent in your terminal.'],
    ['openclaw', 'An OpenClaw gateway running on this Mac.'],
    ['vscode', 'Local Copilot sessions in VS Code.'],
    ['mcp', 'Another app that accepts a local MCP command.']
  ]) entry(local, names[agent], description, 'agent', {agent});
  for (const [vendor, description] of [
    ['chatgpt', 'Connect through your ChatGPT workspace’s private tunnel.'],
    ['muse', 'Connect the Muse app using a custom connector.'],
    ['manus', 'Add Airlock in Manus integrations.'],
    ['ironclaw', 'Install Airlock as an HTTPS extension.'],
    ['custom', 'Another service that accepts an MCP server URL.']
  ]) {
    if (vendor === 'ironclaw' && preview) entry(online, cloudClients[vendor], description, 'agent', {agent:vendor});
    else entry(online, cloudClients[vendor], description, 'remote-create', {vendor});
  }
  entry(online, names.dot, 'Use your existing private Dot tunnel.', 'agent', {agent:'dot'});
  if (canOpen('codex')) {
    const more = details(host, 'Advanced setup');
    note(more, 'Choose records or a custom profile before connecting.');
    for (const agent of desktopApps) row(more, 'Configure ' + names[agent], () => go('agent', {agent, from:'other-agents'}));
  }
}, false);

function useDirectoryBack(host, options) {
  if (options.from === 'other-agents') {
    host.closest('.page').querySelector('.back').replaceWith(button('Other agents', () => go('other-agents'), 'back'));
  }
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

const firstRequest = 'Call the Airlock privacy_status tool and tell me if it responds.';

function configuration(host, response) {
  const value = response.client_config || response.config;
  if (!value) return;
  const box = details(host, 'Connection configuration', null, response.installed === false);
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  put(box, el('pre', text), button('Copy configuration', () => copyText(text)));
}

async function openClient(agent) {
  const reply = await nativeLauncher().postMessage({action: 'open-client', agent});
  if (!reply?.opened) throw Error(reply?.message || 'Could not open ' + names[agent] + '. Open it from Applications, then start a new chat.');
  return reply;
}

async function finishLocalConnection(agent, response) {
  if (response.installed && canOpen(agent)) {
    let message, failed = false;
    try {
      const reply = await openClient(agent);
      message = reply.message || (reply.wasRunning ? names[agent] + ' is open.' :
        names[agent] + ' opened.');
    } catch (error) {
      failed = true;
      message = 'Settings saved. ' + error.message;
    }
    await go('agent', {agent, id:response.id, openHelp:failed, launchNotice:message});
    return;
  }
  await go('connections');
  const f = modal(preview ? 'Connection added to preview' : response.installed ? 'Settings saved' : 'Finish in your agent');
  note(f, preview ? 'These permissions apply to this preview.' : response.message || 'Restart your agent and enable Airlock.');
  if (!preview) {
    configuration(f, response);
    note(f, 'In a fresh chat, ask: ' + firstRequest);
    const update = watchConnection(f, response.id, {status:'waiting'});
    f.append(button('Copy test request', () => copyText(firstRequest)), button('Check connection', update));
  }
  f.append(button('Close', close, 'primary'));
}

async function finishDefaultDesktopConnection(agent) {
  if (!personal || !canOpen(agent)) throw Error('Open Airlock.app on this Mac to finish connecting.');
  const ws = await api('workspace-state');
  const current = ws.agents.filter(a => a.name === agent && active(a));
  if (current.length) {
    if (current.length !== 1 || !current[0].scope || current[0].installed !== true) {
      await go('agent', {agent, openHelp:true});
      flash('Review the existing setup for ' + names[agent] + '.');
      return;
    }
    await finishLocalConnection(agent, await api('workspace-reconnect', {id:current[0].id}));
    return;
  }
  const result = await api('workspace-connect', {
    agent, identifier:'', selection:{}, excerpt_selection:[], compute:false, proposals:false,
    mail:false, calendar:false, install:true
  });
  await finishLocalConnection(agent, result);
}

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
  const ws = await api('workspace-state');
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
    if (opt.launchNotice) note(host, opt.launchNotice);
    if (!preview && active(existing) && localAgents.includes(agent)) {
      if (canOpen(agent) && existing.installed === true && (!opt.launchNotice || opt.openHelp)) host.append(button('Open ' + names[agent], async () => {
        const reply = await openClient(agent);
        flash(reply.message || names[agent] + ' opened.');
      }, 'primary'));
      const update = watchConnection(host, existing.id, {...existing, last_context_read:existing.last_read});
      if (opt.launchNotice) {
        const selected = existing.scope?.records?.length;
        if (selected != null) note(host, selected === 0 ? 'No records shared.' :
          selected + (selected === 1 ? ' record selected for this agent.' : ' records selected for this agent.'));
        host.append(button('Manage access', () => go('agent', {id:existing.id, agent})));
      }
      const help = details(host, 'Connection help', null, !!opt.openHelp || existing.installed === false);
      note(help, 'In a fresh chat, ask: ' + firstRequest);
      help.append(button('Copy test request', () => copyText(firstRequest)), button('Check connection', update));
      if (existing.installed === false) help.append(button('Show configuration', async () => {
        const result = await api('workspace-manual-config', {id:existing.id});
        const f = modal('Finish in ' + names[agent]); note(f, result.message);
        configuration(f, {...result, installed:false});
      }));
      help.append(button('Repair setup', async () => {
        const result = await api('workspace-reconnect', {id:existing.id});
        if (!result.installed) {
          const f = modal('Finish in ' + names[agent]); note(f, result.message); configuration(f, result);
        } else if (canOpen(agent)) {
          await finishLocalConnection(agent, result);
        } else {
          await refresh(); flash('Agent settings restored.');
        }
      }));
    }
    if (opt.launchNotice && active(existing)) return;
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
  const connectLabel = () => (canOpen(agent) && install?.checked ? 'Connect & open ' : 'Connect ') + names[agent];
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

addPage('dot', 'Dot tunnel', 'other-agents', async host => {
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
