'use strict';

addPage('prompt-gateway', 'Filter model requests', 'protection', async host => {
  note(host, 'A compatible client can send text through Airlock before it reaches a model. Choose a destination for each client.');
  if (preview) {
    note(host, 'Open Airlock on your Mac to create a local model connection.');
    return;
  }
  const state = await api('prompt-status');
  host.append(button('Add model connection', () => {
    const f = modal('Add model connection');
    const name = field(f, 'Connection name', input());
    name.placeholder = 'My writing client';
    const provider = field(f, 'Send filtered text to', select([
      ['ollama', 'Local Ollama'],
      ['openai', 'OpenAI']
    ]));
    const model = field(f, 'Model installed in Ollama', input());
    model.placeholder = 'e.g. llama3.2';
    const key = field(f, 'OpenAI API key', input('password'));
    key.autocomplete = 'off';
    const destination = el('p', '', 'hint');
    f.append(destination);
    function updateDestination() {
      const cloud = provider.value === 'openai';
      key.parentElement.hidden = !cloud;
      model.parentElement.firstChild.textContent = cloud ? 'OpenAI model ID' : 'Model installed in Ollama';
      model.value = '';
      model.placeholder = cloud ? 'Your model ID' : 'e.g. llama3.2';
      if (!cloud) key.value = '';
      destination.textContent = cloud
        ? 'Filtered text leaves this device. OpenAI receives the remaining text and can bill your API account.'
        : 'Filtered text goes to Ollama on this Mac.';
    }
    provider.addEventListener('change', updateDestination);
    updateDestination();
    note(f, 'Each key allows up to 100 text requests over 24 hours. Locking Airlock ends access.');
    formAction(f, 'Create connection', async () => {
      const body = {name: name.value.trim(), provider: provider.value, model: model.value.trim(), approved: true};
      if (!body.name || !body.model) throw Error('Enter a connection name and a model.');
      if (body.provider === 'openai') body.api_key = key.value.trim();
      const created = await api('prompt-create', body);
      key.value = '';
      const done = modal('Configure your client');
      note(done, 'In the client’s OpenAI-compatible provider settings, enter these three values. The key is shown once.');
      done.append(facts([['Base URL', created.base_url], ['Model', created.model]]));
      const token = field(done, 'Airlock API key', input('password', created.token));
      token.readOnly = true;
      done.append(button('Copy Airlock API key', () => copyText(created.token)),
        button('Done', async () => { close(); await refresh(); }, 'primary'));
    });
  }, 'primary'));
  const connections = section(host, 'Model connections');
  if (!state.clients.length) empty(connections, 'No model connections.');
  for (const client of state.clients) {
    item(connections, client.name, [client.provider === 'openai' ? 'OpenAI' : 'Ollama', client.model,
      client.calls + '/' + client.limit + ' calls', 'expires ' + when(client.expires_at)].join(' · '),
    () => confirmAction('Revoke model connection?', client.name, 'Revoke', async () => {
      await api('prompt-revoke', {id: client.id});
      await refresh();
    }, true));
  }
});
