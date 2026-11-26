'use strict';

const cloudClients = {muse: 'Meta Muse', manus: 'Manus', chatgpt: 'ChatGPT', ironclaw: 'IronClaw', custom: 'Other remote MCP client'};

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
    if (!updated.verified) flash('This Mac still cannot resolve the link. Use the code from another device.');
  }), button('Stop temporary link', async () => {await api('remote-quick-stop'); await after();}));
}

addPage('remote-bridge', 'HTTPS bridge', 'remote-clients', async host => {
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
    await go('remote-clients');
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
      note(f, opt.vendor === 'muse' ?
        'Paste the setup request into Muse. When Muse opens its secure credential prompt, enter the token there.' :
        opt.vendor === 'manus' ? 'In Manus, open Settings → Integrations → Custom MCP Servers. Add this URL and select Bearer token.' :
        opt.vendor === 'ironclaw' ? 'Review the manifest and install it in IronClaw. Save the token under airlock_scoped_token in its secret settings.' :
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
          'Create a private Airlock connector using this OpenAPI schema: ' + result.url +
          '. Use HTTP bearer authentication and ask me for the token through the secure credential store.'
        )));
      } else {
        f.append(button('Copy server URL', () => copyText(result.url)));
      }
      const secret = field(f, 'Bearer token · shown once', input('password', result.credential));
      secret.autocomplete = 'off';
      secret.readOnly = true;
      f.append(button('Copy token', () => copyText(result.credential)));
    }
    formAction(f, 'Test this connection', () => startProviderCheck(result.id));
    await destination;
  });
});
