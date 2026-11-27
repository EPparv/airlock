'use strict';

const cloudClients = {muse: 'Meta Muse', manus: 'Manus', chatgpt: 'ChatGPT', ironclaw: 'IronClaw', custom: 'Other remote MCP client'};
const hostedSignupVendors = ['muse', 'manus'];

let cloudReceipt;

async function connectRemoteNow(vendor, from = 'connect', id) {
  if (!Object.hasOwn(cloudClients, vendor)) throw Error('Choose an agent from the list.');
  const result = await api('remote-connect', {vendor, approved:true, ...(id ? {id} : {})});
  if (result.state === 'bridge' || result.state === 'choose') {
    return go('remote-create', {vendor, from, quick:true});
  }
  // The one-time credential stays in this render. Browser history only gets the grant ID.
  cloudReceipt = result;
  try {
    await go('remote-handoff', {vendor, id:result.id, from});
  } finally {
    if (cloudReceipt === result) cloudReceipt = null;
  }
}

function cloudValue(host, label, value, type = 'text') {
  const box = field(host, label, type === 'multiline' ? el('textarea') : input(type));
  box.value = value;
  box.readOnly = true;
  box.autocomplete = 'off';
  host.append(button('Copy ' + (type === 'password' ? 'token' : label.toLowerCase()), async () => {
    try {
      await navigator.clipboard.writeText(value);
      flash('Copied.');
    } catch {
      if (type === 'password') box.type = 'text';
      box.focus();
      box.select();
      flash('Press Command-C to copy the selected text.');
      if (type === 'password') box.addEventListener('blur', () => { box.type = 'password'; }, {once:true});
    }
  }));
}

function hostedSignIn(host, vendor, setup, initial) {
  const label = setup ? 'Continue in ' + cloudClients[vendor] : 'Sign in or create an account';
  let fallback;
  function showFallback(result) {
    fallback?.remove();
    if (result.opened) return;
    fallback = el('div');
    action.after(fallback);
    if (result.retry_native) {
      note(fallback, 'Copy the link and paste it into your browser.');
    } else {
      const link = el('a', 'Open ' + cloudClients[vendor] + ' in your browser');
      link.href = result.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      fallback.append(link);
    }
    fallback.append(button('Copy link', () => copyText(result.url)));
  }
  const action = button(label, async () => showFallback(await api('remote-open-hosted', {vendor})),
    setup ? 'primary' : 'secondary');
  host.append(action);
  if (initial?.url) showFallback(initial);
  note(host, setup ? 'If sign-in takes you to the home page, return here and choose ' + label + '.' :
    'After signing in, return to Airlock to finish connecting.');
}

function addTunnelDownload(host) {
  host.append(button('Get tunnel-client', async () => {
    const help = await api('remote-tunnel-helper', {open_download:true});
    if (help.opened || host.querySelector('.tunnel-download')) return;
    const link = el('a', 'Open the official download', 'tunnel-download');
    link.href = help.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    host.append(link);
  }));
}

async function openCloudTunnel(host, id) {
  const result = await api('remote-open-tunnel', {id});
  if (result.opened) {
    flash(result.already_open ? result.message : 'Terminal opened. Enter your dedicated tunnel ID and restricted runtime key there.');
  } else {
    if (host.querySelector('.tunnel-command')) return;
    const fallback = el('div', null, 'tunnel-command');
    host.append(fallback);
    cloudValue(fallback, 'Terminal command', result.command, 'multiline');
    note(fallback, 'Run this command in Terminal on your Mac.');
  }
}

function ironclawHostForm(parent, setup, saved = '') {
  const address = field(parent, 'Your IronClaw address', input('url', saved));
  address.placeholder = 'https://ironclaw.example.com';
  note(parent, 'Use the address of your own instance. A local installation usually runs at http://127.0.0.1:3000.');
  formAction(parent, 'Open my IronClaw', async () => {
    const result = await api('remote-ironclaw-host', {origin:address.value.trim(),setup});
    if (result.opened) flash(result.message);
    else {
      parent.querySelector('.ironclaw-link')?.remove();
      const link = el('a', 'Continue to IronClaw', 'ironclaw-link');
      link.href = result.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      parent.append(link);
    }
  });
}

addPage('remote-handoff', 'Connect agent', 'connect', async (host, opt, bar) => {
  if (preview || !Object.hasOwn(cloudClients, opt.vendor)) return go('connect');
  const name = cloudClients[opt.vendor];
  const receipt = cloudReceipt?.id === opt.id ? cloudReceipt : null;
  bar.querySelector('h1').textContent = name;
  const setup = receipt?.setup;
  const handoff = receipt?.handoff;
  const headline = el('h2', setup ? 'Finish setup' : receipt ? 'Waiting for ' + name : 'Connection details', 'handoff-status');
  const detail = el('p', handoff?.message || '', 'handoff-detail');
  const surface = el('div', null, 'handoff-result');
  surface.setAttribute('role', 'status');
  surface.append(headline, detail);
  host.append(surface);
  if (handoff?.choose_host) ironclawHostForm(host, !!setup);
  if (setup && hostedSignupVendors.includes(opt.vendor)) {
    hostedSignIn(host, opt.vendor, true, handoff);
  } else if (handoff?.retry_native) {
    host.append(button('Open ' + name, async () => {
      const next = await api('remote-open-provider', {vendor:opt.vendor, setup:!!setup});
      if (!next.opened) throw Error('Could not open ' + name + '. Open ' + next.url + ' in your browser.');
      detail.textContent = next.message;
    }, 'primary'));
  } else if (handoff?.url && !handoff.opened) {
    const link = el('a', 'Open ' + name, 'button');
    link.href = handoff.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    host.append(link);
  }
  if (handoff?.request && (!handoff.prepared || (setup && opt.vendor === 'muse'))) {
    host.append(button('Copy ' + (setup ? 'setup' : 'status') + ' request', () => copyText(handoff.request)));
  }
  if (setup && opt.vendor === 'chatgpt') {
    note(host, 'Install OpenAI’s tunnel-client on your Mac. Use a dedicated tunnel for this connection. In ChatGPT Plugins, add and install that tunnel as a custom MCP server.');
    if (receipt.tunnel_opened) note(host, 'Terminal opened for your tunnel ID and restricted runtime key. Keep the tunnel running while using ChatGPT.');
    else {
      if (receipt.helper_installed === false) addTunnelDownload(host);
      host.append(button('Open tunnel setup', () => openCloudTunnel(host, opt.id), 'primary'));
    }
  } else if (setup) {
    const next = {
      manus:'In Manus, choose Connectors → Create → Add MCP by URL. Enter the server URL and save the bearer token in its authentication settings.',
      muse:'Enter your schema URL in the custom connector setup. Save the bearer token in Muse’s secure credential prompt.',
      ironclaw:'In Extensions → Registry, choose Add MCP server. Enter the Server URL and select Bearer token. Install Airlock and save its token in IronClaw’s setup form.',
      custom:'Add a Streamable HTTP MCP server in your app. Save the token in its bearer authentication settings.'
    };
    note(host, next[opt.vendor]);
    if (receipt.manifest) cloudValue(details(host, 'Extension manifest'), 'Manifest', receipt.manifest, 'multiline');
    if (receipt.url) cloudValue(host, opt.vendor === 'muse' ? 'Schema URL' : 'Server URL', receipt.url, 'url');
    if (receipt.credential) cloudValue(host, 'Bearer token · shown once', receipt.credential, 'password');
  }
  if (receipt) {
    const recovery = {
      chatgpt:'Select the installed Airlock plugin in the correct ChatGPT workspace. Under Connection details you can check the local tunnel and reopen it.',
      muse:'Check that the custom connector has the current schema URL and that Muse saved the bearer token in its credential store.',
      manus:'In Manus Connectors, open your Airlock server and check its URL and bearer authentication.',
      ironclaw:'In your IronClaw instance, check that the Airlock extension is installed and its bearer token is configured.',
      custom:'Check the server URL and bearer authentication settings in your MCP app.'
    };
    watchHandoff(host, {agent:opt.vendor, id:opt.id, opened:!!handoff.opened && !setup,
      recovery:recovery[opt.vendor], previousStatus:receipt.previous}, headline, detail);
  } else {
    const status = await api('client-status', {id:opt.id});
    watchConnection(host, opt.id, status);
    host.append(button('Open ' + name, () => connectRemoteNow(opt.vendor, opt.from, opt.id), 'primary'));
  }
  const help = details(host, 'Connection details');
  if (opt.vendor === 'ironclaw' && !handoff?.choose_host) ironclawHostForm(help, !!setup, handoff?.host || '');
  if (opt.vendor === 'chatgpt') {
    if (receipt?.tunnel_status && !receipt.tunnel_opened) note(help, receipt.tunnel_status.message);
    help.append(button('Check local tunnel', async () => {
      const check = await api('provider-check-state', {id:opt.id});
      flash(check.tunnel_status?.message || check.local);
    }), button('Reopen tunnel', () => openCloudTunnel(help, opt.id)));
    note(help, 'If ChatGPT shows HTTP 429 before a tool responds, follow its Retry-After time and check the workspace quota. Reuse this connection when retrying.');
  }
  help.append(button('Manage access', () => go('agent', {agent:'mcp', id:opt.id})),
    button('Test or recover connection', () => go('provider-check', {id:opt.id})));
  if (setup && receipt?.state === 'existing' && opt.vendor !== 'chatgpt') {
    const status = await api('provider-check-state', {id:opt.id});
    if (status.url) cloudValue(host, opt.vendor === 'muse' ? 'Schema URL' : 'Server URL', status.url, 'url');
    note(host, 'Use the token you saved when this connection was created. If you lost it, open connection recovery.');
  }
});

function cloudConnectionRow(host, grant) {
  const subtitle = grant.confirmed ? 'Confirmed ' + when(grant.confirmed) :
    grant.last_call ? 'Last tool call ' + when(grant.last_call) : 'Waiting for first call';
  item(host, cloudClients[grant.vendor] + ' · ' + grant.id.slice(-6), subtitle,
    () => go('provider-check', {id: grant.id}));
}

async function startProviderCheck(id) {
  await api('provider-check-start', {id});
  await go('provider-check', {id});
}

addPage('remote-clients', 'Cloud agents', 'privacy', async host => {
  if (preview) {
    note(host, 'Open Airlock on your Mac to connect a cloud agent.');
    return;
  }
  const state = await api('remote-state');
  const list = section(host, 'Connect an agent');
  for (const [vendor, name] of Object.entries(cloudClients)) {
    row(list, name, () => go('remote-create', {vendor}));
  }
  const grants = state.connections.filter(c => c.active);
  if (grants.length) {
    const connected = section(host, 'Your connections');
    for (const grant of grants) cloudConnectionRow(connected, grant);
  }
  if (state.connections.length) choose(host, 'Test a connection', 'provider-checks');
  const area = section(host, 'HTTPS bridge');
  item(area, state.origin || 'Set up bridge', state.enabled && state.listening ? 'Listening on this Mac' :
    'Off', () => go('remote-bridge'));
});

function startTemporaryLink(after) {
  const f = modal('Start temporary link');
  note(f, 'Airlock downloads a verified Cloudflare helper on first use. Cloudflare forwards traffic to this Mac and can see the credentials and data sent through the link.');
  note(f, 'The link expires when you stop it, lock Airlock, or quit. Keep your Mac awake while testing.');
  const device = check(f, 'Verify from another device', false);
  const action = formAction(f, 'Start link', async () => {
    action.textContent = 'Opening link…';
    try {
      await api('remote-quick-start', {approved: true, verification_method: device.checked ? 'device' : 'auto'});
      close();
      await after();
    } finally {
      action.textContent = 'Start link';
    }
  });
}

function temporaryLinkVerification(host, state, after) {
  const check = state.verification;
  if (check && check.expires * 1000 > Date.now()) {
    const form = el('div', null, 'form');
    host.append(form);
    note(form, 'Open this link on another device. If Wi-Fi cannot find it, try cellular. Enter the eight digits it shows.');
    const url = field(form, 'Verification link', input('url', check.url));
    url.readOnly = true;
    form.append(button('Copy verification link', () => copyText(check.url)));
    const code = field(form, 'Verification code', input());
    code.inputMode = 'numeric';
    code.autocomplete = 'one-time-code';
    code.maxLength = 8;
    formAction(form, 'Verify link', async () => {
      if (!/^[0-9]{8}$/.test(code.value.trim())) throw Error('Enter all eight digits from the verification page.');
      await api('remote-quick-confirm', {code: code.value.trim()});
      code.value = '';
      await after();
    });
  }
  host.append(button('Retry on this Mac', async () => {
    const updated = await api('remote-quick-retry');
    await after();
    if (!updated.verified) flash('This Mac could not verify the public link. Use the code from another device.');
  }), button('Stop temporary link', async () => {await api('remote-quick-stop'); await after();}));
}

addPage('remote-bridge', 'HTTPS bridge', 'remote-clients', async (host, opt) => {
  if (preview) return nativeOnly('HTTPS bridge');
  const state = await api('remote-state');
  if (state.mode === 'temporary' && state.enabled) {
    host.append(facts([['Temporary link', state.origin], ['Status', state.verified ? 'Verified over HTTPS' : 'Connecting']]));
    if (!state.verified) {
      temporaryLinkVerification(host, state, refresh);
      return;
    }
    note(host, 'Stopping this link ends the connections created for it.');
    host.append(button('Stop temporary link', () => confirmAction('Stop temporary link?',
      'Agents using this link will need a new connection.', 'Stop link', async () => {
        await api('remote-quick-stop'); await refresh();
      }, true)));
    return;
  }
  if (!state.enabled) {
    note(host, 'Create a temporary Cloudflare link to test from another device or a cloud agent.');
    host.append(button('Start temporary link', () => startTemporaryLink(refresh), 'primary'));
  }
  const manual = state.enabled ? host : details(host, 'Use my own domain');
  note(manual, 'Forward your HTTPS domain to the agent bridge on this Mac.');
  manual.append(facts([['Forward to', state.upstream]]));
  const form = el('div', null, 'form');
  manual.append(form);
  const origin = field(form, 'Your HTTPS origin', input('url', state.origin));
  origin.placeholder = 'https://airlock.yourdomain.com';
  const port = field(form, 'Local bridge port', input('number', String(state.port)));
  port.min = '1024';
  port.max = '65535';
  note(form, 'The proxy can see released results and credentials. Forward only the bridge port.');
  formAction(form, 'Save and enable', async () => {
    await api('remote-configure', {origin: origin.value.trim(), port: Number(port.value), enabled: true});
    if (opt.resume) await connectRemoteNow(opt.resume);
    else await go('remote-clients');
  });
  if (state.enabled) form.append(button('Pause HTTPS access', async () => {
    await api('remote-configure', {origin: state.origin, port: state.port, enabled: false});
    await go('remote-clients');
  }));
});

addPage('remote-create', 'Connect cloud agent', 'remote-clients', async (host, opt, bar) => {
  useDirectoryBack(host, opt);
  const name = cloudClients[opt.vendor];
  if (!name) return go('remote-clients');
  bar.querySelector('h1').textContent = name;
  if (preview) {
    note(host, 'Open Airlock on your Mac to connect ' + name + '.');
    host.append(previewSetupLink());
    return;
  }
  const state = await api('remote-state');
  const existing = state.connections.filter(c => c.vendor === opt.vendor && c.active);
  const waitingForBridge = !state.enabled || !state.listening || (state.mode === 'temporary' && !state.verified);
  if (hostedSignupVendors.includes(opt.vendor) && (waitingForBridge || !opt.quick)) {
    hostedSignIn(host, opt.vendor, false);
  }
  if (opt.quick) {
    const resume = () => connectRemoteNow(opt.vendor, opt.from);
    if (opt.vendor !== 'chatgpt' && state.mode === 'temporary' && state.enabled && !state.verified) {
      temporaryLinkVerification(host, state, resume);
    } else if (opt.vendor !== 'chatgpt' && !(state.enabled && state.listening)) {
      note(host, name + ' needs an HTTPS link to reach your Mac.');
      if (state.origin && state.mode !== 'temporary') {
        host.append(button('Resume saved bridge', async () => {
          await api('remote-configure', {origin:state.origin, port:state.port, enabled:true});
          await resume();
        }, 'primary'));
      } else if (!state.enabled) {
        note(host, 'Cloudflare handles traffic through this temporary link and can see credentials and shared data. Keep your Mac awake. Locking Airlock ends access.');
        const progress = el('p', '', 'hint');
        progress.setAttribute('role', 'status');
        const stop = button('Cancel', async () => {
          await api('remote-quick-stop');
          if (host.isConnected) await refresh();
        });
        stop.hidden = !state.starting;
        const start = button('Start temporary link', async () => {
          start.textContent = 'Starting link…';
          progress.textContent = 'Preparing the helper and checking the public link.';
          stop.hidden = false;
          try {
            await api('remote-quick-start', {approved:true, verification_method:'auto'});
            if (host.isConnected) await resume();
          } catch (error) {
            if (host.isConnected) throw error;
          } finally {
            if (host.isConnected) {
              start.textContent = 'Start temporary link';
              stop.hidden = true;
              progress.textContent = '';
            }
          }
        }, 'primary');
        if (state.starting) {
          progress.textContent = 'A link is starting on this Mac.';
          host.append(button('Check link', resume, 'primary'));
        } else host.append(start);
        host.append(progress, stop);
      }
      host.append(button(state.enabled ? 'Restore bridge' : 'Use my own domain', () => go('remote-bridge', {resume:opt.vendor})));
    } else if (existing.length > 1) {
      const list = section(host, 'Choose a connection');
      for (const grant of existing) item(list, 'Connection ' + grant.id.slice(-6), 'Expires ' + when(grant.expires),
        () => connectRemoteNow(opt.vendor, opt.from, grant.id));
    } else {
      host.append(button('Open ' + name, resume, 'primary'));
    }
    return;
  }
  if (existing.length && !opt.newConnection) {
    const list = section(host, 'Your connections');
    for (const grant of existing) cloudConnectionRow(list, grant);
    host.append(button('Add another connection', () => go('remote-create', {...opt, newConnection:true})));
    return;
  }
  if (opt.vendor !== 'chatgpt' && state.mode === 'temporary' && state.enabled && !state.verified) {
    temporaryLinkVerification(host, state, refresh);
    return;
  }
  if (opt.vendor !== 'chatgpt' && !(state.enabled && state.listening)) {
    note(host, name + ' needs an HTTPS bridge to reach your Mac.');
    if (!state.enabled) host.append(button('Start temporary link', () => startTemporaryLink(refresh), 'primary'));
    host.append(button('Bridge settings', () => go('remote-bridge')));
    return;
  }
  const form = el('div', null, 'form');
  host.append(form);
  note(form, opt.vendor === 'chatgpt' ?
    'You need a dedicated OpenAI Secure MCP Tunnel linked to your ChatGPT workspace. Everyone with access to that tunnel shares its Airlock permissions.' :
    'Airlock will give you an address and a token for ' + name + '.');
  note(form, 'Start with zero shared records. You can choose what to share after the first call.');
  const getLimits = limits(details(form, 'Connection limits'));
  formAction(form, 'Create connection', async () => {
    const result = await api('remote-create', {vendor: opt.vendor, ...getLimits()});
    const destination = go('provider-check', {id: result.id});
    const f = modal('Connect ' + name);
    if (opt.vendor === 'chatgpt') {
      note(f, 'Install OpenAI’s tunnel-client on your Mac. Run this command in Terminal, enter your dedicated tunnel ID and restricted runtime key, and leave the process running.');
      const cmd = field(f, 'Terminal command', el('textarea'));
      cmd.value = result.command;
      cmd.readOnly = true;
      f.append(button('Copy command', () => copyText(result.command)));
      note(f, 'In ChatGPT on the web, open Plugins → + → Add custom MCP server. Choose Tunnel, select the same tunnel and choose No authentication. Create and install the plugin.');
    } else {
      if (hostedSignupVendors.includes(opt.vendor)) hostedSignIn(f, opt.vendor, true);
      note(f, opt.vendor === 'muse' ?
        'Paste the setup request into Muse. When Muse opens its secure credential prompt, enter the token there.' :
        opt.vendor === 'manus' ? 'In Manus, choose Connectors → Create → Add MCP by URL. Save the token in its authentication settings.' :
        opt.vendor === 'ironclaw' ? 'In your IronClaw instance, open Extensions → Registry → Add MCP server. Choose bearer authentication, install the extension, then enter the token in its setup form.' :
        'Add this URL as a Streamable HTTP MCP server. Set Authorization to Bearer followed by the token in the client’s secret settings.');
      if (result.manifest) {
        const file = field(f, 'IronClaw extension manifest', el('textarea'));
        file.value = result.manifest;
        file.readOnly = true;
        f.append(button('Copy manifest', () => copyText(result.manifest)));
      }
      const url = field(f, opt.vendor === 'muse' ? 'OpenAPI schema URL' : 'MCP server URL', input('url', result.url));
      url.readOnly = true;
      if (opt.vendor === 'muse') {
        f.append(button('Copy setup request for Muse', () => copyText(
          'Create a private Airlock connector. Ask me for its OpenAPI URL and use your secure credential prompt for the bearer token. Then call privacy_status once without reading records.'
        )));
      }
      f.append(button(opt.vendor === 'muse' ? 'Copy schema URL' : 'Copy server URL', () => copyText(result.url)));
      const secret = field(f, 'Bearer token · shown once', input('password', result.credential));
      secret.autocomplete = 'off';
      secret.readOnly = true;
      f.append(button('Copy token', () => copyText(result.credential)));
    }
    formAction(f, 'Test this connection', () => startProviderCheck(result.id));
    await destination;
  });
});
