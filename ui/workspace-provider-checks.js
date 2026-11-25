'use strict';

addPage('provider-checks', 'Test a connection', 'remote-clients', async host => {
  if (preview) return nativeOnly('Test a connection');
  const remote = await api('remote-state');
  const list = el('div', null, 'menu');
  host.append(list);
  if (!remote.connections.length) empty(list, 'Create a cloud connection first.');
  for (const grant of remote.connections) {
    row(list, cloudClients[grant.vendor] + ' · ' + grant.id.slice(-6),
      () => go('provider-check', {id: grant.id}));
  }
});

addPage('provider-check', 'Connection test', 'provider-checks', async (host, options) => {
  if (preview) return nativeOnly('Connection test');
  const id = options.id;
  const status = await api('provider-check-state', {id});
  const name = cloudClients[status.vendor];
  const expected = status.expires ? (status.received ? 'Code sent to caller' : 'Waiting for a status call') :
    status.confirmed ? 'Confirmed' : 'Unconfirmed';
  host.append(facts([['Connection', name + ' · ' + id.slice(-6)], ['On this Mac', status.local],
    ['Current test', expected], ['Last code confirmed', status.confirmed ? when(status.confirmed) : 'Never']]));
  const form = el('div', null, 'form');
  host.append(form);
  if (!status.active) {
    note(form, 'This connection has expired or was revoked. Create a new connection to test again.');
    form.append(button('Create new connection', () => go('remote-create', {vendor:status.vendor, newConnection:true})));
    return;
  }
  if (!status.expires) {
    note(form, 'Check that this agent can reach your Mac. The status call uses one request and returns a short code.');
    if (status.can_start) formAction(form, 'Start test', async () => {
      await api('provider-check-start', {id});
      await refresh();
    });
    else note(form, status.remaining ? 'Restore the local setup to start a test.' : 'The request allowance is used up. Renew the connection to test it.');
  } else {
    const text = 'Use the Airlock connector and call privacy_status once. Reply with the connection_check code from that tool. Do not read any records.';
    const request = field(form, 'Send in ' + name, el('textarea'));
    request.value = text;
    request.readOnly = true;
    form.append(button('Copy request', () => copyText(text)));
    note(form, 'Enter the code shown in the agent by ' + when(status.expires) + '.');
    const code = field(form, 'Code from the agent', input());
    code.autocomplete = 'off';
    code.autocapitalize = 'characters';
    code.spellcheck = false;
    code.maxLength = 8;
    formAction(form, 'Confirm code', async () => {
      await api('provider-check-confirm', {id, code: code.value.trim()});
      await refresh();
      flash('Code confirmed.');
    });
    form.append(button('Refresh status', refresh), button('End test', async () => {
      await api('provider-check-cancel', {id});
      await refresh();
    }));
  }
  form.append(button('Choose permissions', () => go('agent', {agent:'mcp', id})));
  const help = details(host, 'Connection help');
  if (status.vendor === 'chatgpt') {
    note(help, 'Open the personal workspace and keep the tunnel command running. Select the same tunnel in your ChatGPT workspace. Enable the privacy_status tool and invoke your installed plugin in the chat.');
    note(help, 'If ChatGPT shows HTTP 429, check its error details. For a rate limit, wait for Retry-After when supplied before trying once more. For a quota or organization limit, resolve it with the workspace admin. A new Airlock credential does not clear a provider limit.');
    if (status.tunnel_command) {
      const command = field(help, 'Tunnel setup command', el('textarea'));
      command.value = status.tunnel_command;
      command.readOnly = true;
      help.append(button('Copy tunnel command', () => copyText(status.tunnel_command)));
      note(help, 'Run this command in Terminal to check the profile and start the tunnel. It prompts for the runtime key there.');
    }
  } else if (status.vendor === 'muse') {
    note(help, 'Ask Muse to use your personal custom connector. Verify the current HTTPS schema URL ends in /openapi.json and the Airlock credential was saved in the connector’s secure authentication settings.');
  } else {
    note(help, 'Check your current HTTPS address ends in /mcp. Use this connection’s bearer token in the client’s authentication settings and refresh its tools.');
    if (status.vendor === 'manus') note(help, 'In Manus, open Settings → Integrations → Custom MCP Servers and test the server before requesting the code.');
  }
  if (status.url) {
    const url = field(help, 'Configured endpoint', input('url', status.url));
    url.readOnly = true;
    help.append(button('Copy endpoint', () => copyText(status.url)));
  }
  if (status.vendor !== 'chatgpt') {
    help.append(button('Lost the token?', () => confirmAction('Replace this connection?',
      'This revokes the old token. Create a new connection and choose its shared records again.',
      'Revoke and start again', async () => {
        await api('revoke', {id});
        await go('remote-create', {vendor:status.vendor, newConnection:true});
      }, true)));
  }
  note(help, 'A local setup check runs only on the Mac. A returned code means someone used that connection’s credential. Confirm it here after you see it in the intended agent.');
});
