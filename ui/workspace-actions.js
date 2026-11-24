'use strict';
const actionTypes = {
  email: 'Email',
  event: 'Calendar event',
  data: 'File or database',
  api: 'API endpoint',
  api_write: 'API write',
  live_data: 'Live file or database',
  file_append: 'Append text to a file'
};
const actionStates = {
  ready: 'Ready',
  pending: 'Needs approval',
  submitting: 'Check destination',
  unconfirmed: 'Check destination',
  sent: 'Sent to Mail',
  submitted: 'Accepted by endpoint',
  appended: 'Appended to file',
  created: 'Event created',
  declined: 'Declined'
};
async function actionPage(host, opt, bar, kind) {
  const call = opt.fixture ? testAPI : api;
  const ws = await call('workspace-state'),
    visible = ws.actions.filter(a => !kind || a.kind === kind ||
      (kind === 'data' && ['live_data', 'file_append'].includes(a.kind)) || (kind === 'api' && a.kind === 'api_write'));
  if (!opt.fixture) bar.append(button(kind ? {
    email: 'New email',
    event: 'New event',
    data: 'New view',
    api: 'Add endpoint'
  } [kind] : 'New action', () => prepareAction(kind || 'email'), 'primary'));
  const list = el('div', null, 'list');
  host.append(list);
  if (!visible.length) empty(list, kind === 'data' ? 'No file or database views.' : kind === 'api' ?
    'No API endpoints.' : 'No actions.');
  const sorted = visible.slice().sort((a, b) => Number(b.state === 'pending') - Number(a.state === 'pending'));
  for (const a of sorted) {
    const status = ws.example && ['created', 'sent'].includes(a.state) ? 'Simulated' : actionStates[a.state] || a
      .state;
    item(list, a.label, (a.applicant ? agentName(a.applicant, ws) + ' · ' : '') + status, () => showAction(ws, a,
      call, Boolean(opt.fixture)));
  }
  if (kind === 'data') note(host, 'Share selected fields from a live file or a saved snapshot.');
  if (kind === 'api') note(host, 'Share selected fields or prepare a request to approve before sending.');
}
for (const [pageName, title, kind] of [
    ['actions', 'Device actions', ''],
    ['mail', 'Apple Mail', 'email'],
    ['calendar', 'Apple Calendar', 'event'],
    ['views', 'Files & databases', 'data'],
    ['apis', 'JSON APIs', 'api']
  ])
  addPage(pageName, title, pageName === 'actions' ? 'activity' : 'apps', (host, opt, bar) => actionPage(host, opt,
    bar, kind));

addPage('examples', 'Example actions', 'checks', (host, opt, bar) => actionPage(host, {
  fixture: true
}, bar, ''), false);

function showAction(ws, a, call, fixture) {
  const f = modal(a.label),
    p = a.payload;
  const fields = [
    ['Action', actionTypes[a.kind]],
    ['Access', a.audience.map(id => agentName(id, ws)).join(', ')]
  ];
  if (a.kind === 'email') {
    fields.push(['To', p.recipients.join(', ')], ['Subject', p.subject]);
    if (p.attachment) fields.push(['Attachment', p.attachment.name + ' · ' + p.attachment.size + ' bytes']);
  }
  if (a.kind === 'event') fields.push(['Calendar', p.calendar], ['Title', p.title], ['Start', new Date(p.start)
    .toLocaleString()
  ], ['End', new Date(p.end).toLocaleString()]);
  if (a.kind === 'data') fields.push(['File', p.name], ['Visible fields', p.fields.join(', ')], ['Rows', p.count]);
  if (a.kind === 'live_data') {
    fields.push(['File', p.path], ['Visible fields', p.fields.join(', ')]);
    if (p.table) fields.push(['Table', p.table]);
  }
  if (a.kind === 'file_append') fields.push(['File', p.path]);
  if (a.kind === 'api_write') fields.push(['Method', p.method], ['Endpoint', p.url]);
  if (a.kind === 'api') fields.push(['Endpoint', p.url], ['Visible fields', p.fields.join(', ')]);
  f.append(facts(fields));
  if (a.kind === 'file_append') f.append(el('pre', p.text));
  if (a.kind === 'api_write') f.append(el('pre', p.body));
  if (a.kind === 'email') f.append(el('p', p.body, 'message'));
  const receipt = ws.receipts.find(r => r.response?.reference && r.response.reference === a.handles?.[r.agent]);
  if (receipt) details(f, 'Returned to ' + agentName(receipt.agent, ws), el('pre', JSON.stringify(receipt.response,
    null, 2)));
  if (a.state === 'pending') {
    const decide = async approve => {
      const r = await call('workspace-decide', {
        identifier: a.id,
        fingerprint: a.fingerprint,
        approve
      });
      close();
      await refresh();
      flash(r.status === 'unconfirmed' ? 'Check the destination app before trying again.' : !approve ?
        'Declined.' : ws.example ? 'Example approved.' : a.kind === 'event' ? 'Event created.' :
        a.kind === 'file_append' ? 'Text appended.' : a.kind === 'api_write' ? 'Request accepted by endpoint.' : 'Submitted to Mail.');
    };
    f.append(button(ws.example ? 'Approve example' : a.kind === 'event' ? 'Approve and create event' :
      a.kind === 'file_append' ? 'Approve append' : a.kind === 'api_write' ? 'Approve API request' : 'Approve and send', () => decide(true), 'primary'), button('Decline', () => decide(false)));
  }
  if (ws.example && a.state !== 'pending') {
    const clients = field(f, 'Example agent', select(ws.agents.filter(x => a.audience.includes(x.id)).map(x => [x
      .id, connectionName(x)
    ])));
    const read = ['data', 'api', 'live_data'].includes(a.kind),
      tool = read ? 'read_private_fields' : a.state === 'ready' ? 'request_private_action' :
      'private_action_status';
    f.append(button(read ? 'Read filtered fields' : a.state === 'ready' ? 'Request action' : 'Check receipt',
    async () => {
        const result = await call('workspace-try', {
          identifier: a.id,
          agent: clients.value,
          tool
        });
        await refresh();
        const v = modal('Returned to ' + agentName(clients.value, ws));
        v.append(el('pre', JSON.stringify(result, null, 2)));
      }));
  }
  if (['submitting', 'unconfirmed'].includes(a.state)) note(f,
    'Check the destination app. Automatic retries are disabled.');
  if (!fixture && a.state !== 'submitting') f.append(button('Remove action', () => confirmAction('Remove action?', a
    .label, 'Remove action', async () => {
      await api('workspace-remove', {
        identifier: a.id
      });
      await refresh();
    }, true), 'plain'));
}
async function prepareAction(initialKind) {
  const state = await api('workspace-state');
  const allowed = a => active(a) && a.scope != null;
  const person = id => agentName(id, state);
  if (!state.agents.some(allowed)) {
    const f = modal('Connect an agent first');
    note(f, 'This action needs an agent with scoped access.');
    f.append(button('Connect agent', () => go('connect'), 'primary'));
    return;
  }
  const f = modal('Prepare a private action');
  const type = field(f, 'Action', select([
    ['email', 'Send an email'],
    ['event', 'Create a calendar event'],
    ['data', 'Share fields from a snapshot'],
    ['live_data', 'Share fields from a live file or database'],
    ['file_append', 'Append text to a file'],
    ['api', 'Share fields from an API'],
    ['api_write', 'Send a JSON API request']
  ]));
  type.value = initialKind;
  const name = field(f, 'Label visible to the agent', input());
  name.placeholder = 'Investor follow-up';
  const area = el('div', null, 'form');
  f.append(area);
  let getValues;

  function filePicker(container, path, selected) {
    if (!state.local_file_picker) return;
    container.append(button('Choose file…', run(async () => {
      const result = await api('workspace-select-file', {});
      path.value = result.path;
      if (selected) await selected();
    })));
  }

  function fieldsFor() {
    area.replaceChildren();
    const native = preview && ['api', 'api_write', 'live_data', 'file_append'].includes(type.value);
    name.parentElement.hidden = native;
    fs.hidden = native;
    save.hidden = native;
    if (native) {
      note(area, 'Open the Mac app to connect a live data source or approve device writes.');
      return;
    }
    if (type.value === 'email') {
      const to = field(area, 'Recipients', input());
      const source = select([
        ['mail', 'Selected message in Mail'],
        ['calendar', 'Recent meetings in Calendar']
      ]);
      source.setAttribute('aria-label', 'Local source');
      const opts = el('div', null, 'form');
      put(area, put(el('div', null, 'split'), source, button('Read from Mac', run(async () => {
        const r = await api('workspace-sources', {
          source: source.value
        });
        opts.replaceChildren();
        if (!r.items.length) {
          note(opts, 'Select an email in Mail or choose a meeting with attendees.');
          return;
        }
        for (const item of r.items) opts.append(button(item.title || 'Selected message', () => {
          to.value = item.recipient || (item.recipients || []).join(', ');
          opts.replaceChildren();
        }));
      }))), opts);
      const subject = field(area, 'Subject', input());
      const body = field(area, 'Message', el('textarea'));
      const file = field(area, 'Attachment (optional)', input('file'));
      getValues = async () => ({
        recipients: to.value,
        subject: subject.value,
        body: body.value,
        attachment: file.files[0] ? await upload(file.files[0]) : null
      });
    } else if (type.value === 'event') {
      const title = field(area, 'Event title', input()),
        calendar = field(area, 'Writable calendar name', input()),
        start = field(area, 'Start', input('datetime-local')),
        end = field(area, 'End', input('datetime-local'));
      getValues = async () => {
        if (!start.value || !end.value) throw Error('Choose a start and end time.');
        return {
          title: title.value,
          calendar: calendar.value,
          start: new Date(start.value).toISOString(),
          end: new Date(end.value).toISOString()
        };
      };
    } else if (type.value === 'file_append') {
      const path = field(area, 'Full local file path', input()),
        text = field(area, 'Text to append', el('textarea'));
      path.placeholder = '/Users/you/Documents/notes.txt';
      filePicker(area, path);
      note(area, 'Use an existing .txt, .md, or .log file. You review the exact text before it is appended.');
      getValues = async () => ({path: path.value.trim(), text: text.value});
    } else if (type.value === 'api_write') {
      const method = field(area, 'Method', select(['POST', 'PUT', 'PATCH'].map(x => [x, x]))),
        url = field(area, 'JSON endpoint', input('url')),
        credential = field(area, 'Bearer token (optional)', input('password')),
        body = field(area, 'JSON body', el('textarea'));
      url.placeholder = 'https://api.example.com/tasks';
      credential.autocomplete = 'off';
      body.placeholder = '{"status": "complete"}';
      note(area, 'You review this exact request before Airlock sends it. The agent receives a receipt.');
      getValues = async () => ({method: method.value, url: url.value.trim(), credential: credential.value, body: body.value});
    } else if (type.value === 'live_data') {
      const path = field(area, 'Full local file path', input()),
        choices = el('div', null, 'form');
      path.placeholder = '/Users/you/Documents/projects.sqlite';
      note(area, 'CSV and JSON up to 1 MB, SQLite up to 32 MB. Airlock reads the file on each request.');
      let table = '', identity = null, checked = [], version = 0;
      function clear() {
        version++;
        choices.replaceChildren();
        checked = [];
      }
      function reset() {
        clear();
        table = '';
        identity = null;
      }
      path.oninput = reset;
      async function inspect() {
        clear();
        const current = version;
        const result = await api('workspace-live-fields', {path: path.value.trim(), table, identity});
        if (current !== version) return;
        identity = result.identity;
        if (result.tables.length) {
          const source = field(choices, 'Table', select([['', 'Choose a table'], ...result.tables.map(t => [t, t])]));
          source.value = table;
          source.onchange = run(async () => { table = source.value; await inspect(); });
        }
        if (result.fields.length) {
          const fs = group(choices, 'Fields visible to the agent');
          checked = result.fields.map(k => [k, check(fs, k)]);
        }
      }
      const load = async () => { reset(); await inspect(); };
      filePicker(area, path, load);
      put(area, button('Load fields', run(load)), choices);
      getValues = async () => {
        const fields = checked.filter(([, c]) => c.checked).map(([k]) => k);
        if (!identity || !fields.length) throw Error('Load fields and choose at least one.');
        return {path: path.value.trim(), table, identity, fields};
      };
    } else if (type.value === 'api') {
      const url = field(area, 'JSON endpoint', input('url')),
        credential = field(area, 'Bearer token (optional)', input('password')),
        key = field(area, 'Array field (optional)', input());
      url.placeholder = 'https://api.example.com/projects';
      credential.autocomplete = 'off';
      const picker = el('div', null, 'form');
      let checked = [],
        verified = '';
      const settings = () => ({
        url: url.value.trim(),
        credential: credential.value,
        array_key: key.value.trim()
      });
      const invalidate = () => {
        checked = [];
        verified = '';
        picker.replaceChildren();
      };
      [url, credential, key].forEach(x => x.oninput = invalidate);
      put(area, button('Load fields', run(async () => {
        invalidate();
        const current = settings(),
          r = await api('workspace-api-fields', current);
        if (JSON.stringify(current) !== JSON.stringify(settings())) return;
        verified = JSON.stringify(current);
        const fs = group(picker, 'Fields visible to the agent');
        checked = r.fields.map(k => [k, check(fs, k)]);
        note(fs, 'Airlock reads up to 100 rows per request.');
      })), picker);
      getValues = async () => {
        const v = settings(),
          fields = checked.filter(([, c]) => c.checked).map(([k]) => k);
        if (!fields.length || verified !== JSON.stringify(v)) throw Error(
          'Load fields and choose at least one.');
        return {
          ...v,
          fields
        };
      };
    } else {
      const source = field(area, 'CSV, JSON or SQLite snapshot', input('file'));
      source.accept = '.csv,.json,.sqlite,.sqlite3,.db';
      const fieldArea = el('div', null, 'form');
      area.append(fieldArea);
      let data = null,
        table = '',
        boxes = [];
      async function inspect() {
        const r = await api('workspace-fields', {
          ...data,
          table
        });
        fieldArea.replaceChildren();
        boxes = [];
        if (r.tables.length) {
          const sel = field(fieldArea, 'Table', select([
            ['', 'Choose a table'], ...r.tables.map(x => [x, x])
          ]));
          sel.value = table;
          sel.onchange = run(async () => {
            table = sel.value;
            await inspect();
          });
        }
        if (r.fields.length) {
          const fs = group(fieldArea, 'Fields visible to the agent');
          for (const value of r.fields) boxes.push([value, check(fs, value)]);
          note(fs, 'First ' + r.count + ' rows. Direct identifiers are filtered at retrieval.');
        }
      }
      source.onchange = run(async () => {
        data = null;
        table = '';
        boxes = [];
        fieldArea.replaceChildren();
        if (!source.files[0]) return;
        data = await upload(source.files[0], 1024 * 1024);
        await inspect();
      });
      getValues = async () => {
        if (!data || !boxes.some(([, c]) => c.checked)) throw Error(
          'Choose a file and at least one visible field.');
        return {
          ...data,
          table,
          fields: boxes.filter(([, c]) => c.checked).map(([k]) => k)
        };
      };
    }
  }
  const fs = group(f, 'Agents with access'),
    checks = state.agents.filter(allowed).map(a => [a.id, check(fs, person(a.id))]);
  const save = formAction(f, 'Save action', async () => {
    await api('workspace-create', {
      kind: type.value,
      label: name.value,
      audience: checks.filter(([, c]) => c.checked).map(([id]) => id),
      values: await getValues()
    });
    close();
    await refresh();
    flash('Saved.');
  });
  type.onchange = fieldsFor;
  fieldsFor();
}
