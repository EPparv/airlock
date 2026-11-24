'use strict';

const cloudClients = {muse: 'Meta Muse', manus: 'Manus', chatgpt: 'ChatGPT', ironclaw: 'IronClaw', custom: 'Other remote MCP client'};

addPage('remote-clients', 'Cloud agents', 'connect', async host => {
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
    for (const grant of grants) {
      item(connected, cloudClients[grant.vendor] + ' · ' + grant.id.slice(-6), grant.last_call ? 'Last tool call ' + when(grant.last_call) :
        'Expires ' + when(grant.expires), () => go('agent', {id: grant.id, agent: 'mcp'}));
    }
  }
  const area = section(host, 'HTTPS bridge');
  item(area, state.origin || 'Set up bridge', state.enabled && state.listening ? 'Listening on this Mac' :
    'Off', () => go('remote-bridge'));
});

addPage('remote-bridge', 'HTTPS bridge', 'remote-clients', async host => {
  if (preview) return nativeOnly('HTTPS bridge');
  const state = await api('remote-state');
  note(host, 'Point a reverse proxy on this Mac at the local address below. Use a dedicated HTTPS domain your cloud agent can reach.');
  host.append(facts([['Forward to', state.upstream]]));
  const form = el('div', null, 'form');
  host.append(form);
  const origin = field(form, 'Your HTTPS origin', input('url', state.origin));
  origin.placeholder = 'https://airlock.yourdomain.com';
  const port = field(form, 'Local bridge port', input('number', String(state.port)));
  port.min = '1024';
  port.max = '65535';
  note(form, 'The proxy can see released results and the agent credential. Forward only to the bridge port. Keep the owner window and local MCP port private.');
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
  if (preview) return nativeOnly('Cloud agents');
  const name = cloudClients[opt.vendor];
  if (!name) return go('remote-clients');
  bar.querySelector('h1').textContent = name;
  const state = await api('remote-state');
  if (opt.vendor !== 'chatgpt' && !(state.enabled && state.listening)) {
    note(host, name + ' needs an HTTPS bridge to reach your Mac.');
    host.append(button('Set up bridge', () => go('remote-bridge'), 'primary'));
    return;
  }
  const form = el('div', null, 'form');
  host.append(form);
  note(form, opt.vendor === 'chatgpt' ?
    'Use a dedicated OpenAI Secure MCP Tunnel linked to your ChatGPT workspace. Each person allowed to use this tunnel shares its Airlock grant.' :
    'Create a credential for ' + name + ' alone. Enter it in the connector’s credential settings.');
  note(form, 'The connection starts with zero shared records. Choose its permissions after setup.');
  const getLimits = limits(form);
  formAction(form, 'Create connection', async () => {
    const result = await api('remote-create', {vendor: opt.vendor, ...getLimits()});
    const f = modal('Connect ' + name);
    if (opt.vendor === 'chatgpt') {
      note(f, 'Install OpenAI’s tunnel-client on your Mac. Run this command in Terminal, enter your dedicated tunnel ID and restricted runtime key, and leave the process running.');
      const cmd = field(f, 'Terminal command', el('textarea'));
      cmd.value = result.command;
      cmd.readOnly = true;
      f.append(button('Copy command', () => copyText(result.command)));
      note(f, 'In ChatGPT, open Plugins → Add custom MCP server → Tunnel. Choose the same tunnel and No authentication. Install privately and ask ChatGPT to call privacy_status.');
    } else {
      note(f, opt.vendor === 'muse' ?
        'Ask Muse to create a custom connector from this API schema. Set HTTP Bearer authentication in the secure credential prompt.' :
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
      const secret = field(f, 'Bearer token · shown once', input('password', result.credential));
      secret.autocomplete = 'off';
      secret.readOnly = true;
      f.append(button('Copy token', () => copyText(result.credential)));
      note(f, 'Ask the agent to call privacy_status. A successful response confirms it can reach your Mac.');
    }
    formAction(f, 'Choose permissions', () => go('agent', {agent: 'mcp', id: result.id}));
  });
});
