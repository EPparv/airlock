// All mutable state exists only in this tab. No agent or device adapter runs here.
(() => {
  const sample = JSON.parse(document.getElementById('example-data').textContent);
  const copy = v => JSON.parse(JSON.stringify(v)),
    now = () => Math.floor(Date.now() / 1000);
  const unique = () => crypto.getRandomValues(new Uint32Array(4)).join('-');
  const refuse = text => {
    throw Error(text);
  };
  const onMac = () => refuse('Open Airlock on your Mac to use this feature with your device.');
  const readText = content => new TextDecoder().decode(Uint8Array.from(atob(content), c => c.charCodeAt(0)));
  let ws, phrases, audit, imports, previews, packages, checks, walk, rows;

  function reset() {
    ws = copy(sample.initial);
    phrases = [];
    audit = [];
    imports = [];
    previews = new Map();
    packages = [];
    checks = {};
    walk = {
      loaded: false,
      records: {},
      grant: null,
      result: null
    };
    rows = new Map();
    for (const g of ws.agents) g.expires = now() + 86400;
  }
  reset();
  const record = ref => ws.records.find(r => r.ref === ref) || refuse('Select an existing record.');
  const grant = id => ws.agents.find(g => g.id === id) || refuse('Select an existing connection.');
  const available = r => !r.never_share && !r.retired && !r.stale;
  const usable = id => {
    const g = grant(id);
    if (g.status === 'revoked' || g.expires <= now()) refuse('This connection has expired or was revoked.');
    return g;
  };

  function insert(kind, text, isPrivate = false) {
    text = String(text || '').trim();
    if (!text || text.length > 12000) refuse('Enter up to 12,000 characters.');
    const r = {
      ref: kind + ':preview:' + unique(),
      text_hash: unique(),
      text,
      kind,
      title: 'Saved record',
      source_device_only: isPrivate,
      never_share: isPrivate,
      sensitive: /\b(medical|salary|passport|diagnosis|tax return|bank balance)\b/i.test(text),
      retired: false,
      stale: false,
      core: false,
      editable: true,
      parents: []
    };
    ws.records.push(r);
    return r;
  }

  function redact(value) {
    let text = String(value ?? '').replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi, '[email withheld]')
      .replace(/\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b/g, '[phone withheld]')
      .replace(/\b(?:sk-[\w-]{8,}|Bearer\s+[\w.+/=-]+)\b/gi, '[credential withheld]');
    for (const phrase of phrases) {
      const re = phrase.replace(/[.*+?^\x24{}()|[\]\\]/g, '\\$&');
      text = text.replace(new RegExp(re, 'gi'), '[withheld]');
    }
    return text;
  }
  const tokenMaps = new Map();

  function tokenFor(agent, type, value) {
    const key = JSON.stringify([agent, type, String(value).toLowerCase()]);
    if (!tokenMaps.has(key)) tokenMaps.set(key, '[' + type + '-' + unique().split('-')[0] + ']');
    return tokenMaps.get(key);
  }

  function screenCell(name, v, agent) {
    if (v == null) return null;
    if (typeof v === 'object') refuse('Choose fields containing individual values.');
    if (/password|secret|api.?key|token|credential|private.?note/i.test(name)) return '[withheld]';
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(v))) return tokenFor(agent, 'email', v);
    if (/^(?:full.?name|name|person|organization|company)$/i.test(name)) return tokenFor(agent, 'identity', v);
    return redact(v);
  }

  function importRows(p) {
    const text = readText(p.content);
    const items = [];
    const add = (value, kind = 'memories') => {
      const obj = typeof value === 'string' ? {
        text: value
      } : value;
      if (obj && typeof obj.text === 'string' && obj.text.trim()) items.push({
        kind: p.kind === 'auto' ? kind : p.kind || kind,
        text: obj.text.trim(),
        device_only: obj.device_only === true
      });
    };
    if (/\.(zip|skill)$/i.test(p.name)) return onMac();
    if (/\.json$/i.test(p.name)) {
      let obj;
      try {
        obj = JSON.parse(text);
      } catch {
        refuse('Choose a valid JSON file.');
      }
      if (Array.isArray(obj)) obj.forEach(v => add(v));
      else
        for (const key of ['memories', 'skills'])(obj[key] || []).forEach(v => add(v, key));
    } else {
      let kind = 'memories';
      for (const line of text.split(/\r?\n/)) {
        if (/^#+\s*(memories|skills|instructions)\s*$/i.test(line)) {
          kind = /memories/i.test(line) ? 'memories' : 'skills';
          continue;
        }
        if (line.trim()) add(line.replace(/^\s*[-*]\s+/, '').trim(), kind);
      }
    }
    if (!items.length) refuse('No supported records found. Try pasting plain text.');
    const id = unique();
    previews.set(id, {
      name: p.name,
      items
    });
    return {
      id,
      items,
      scope: 'Select the records to add to this preview.'
    };
  }

  function csv(text) {
    const result = [],
      row = [];
    let part = '',
      quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') {
        if (quoted && text[i + 1] === '"') {
          part += '"';
          i++;
        } else quoted = !quoted;
      } else if (!quoted && (c === ',' || c === '\n')) {
        row.push(part.replace(/\r$/, ''));
        part = '';
        if (c === '\n') {
          result.push(row.splice(0));
        }
      } else part += c;
    }
    if (quoted) refuse('Choose a valid CSV file.');
    if (part || row.length) {
      row.push(part.replace(/\r$/, ''));
      result.push(row);
    }
    const labels = result.shift() || [];
    return result.filter(r => r.some(Boolean)).map(r => Object.fromEntries(labels.map((k, i) => [k, r[i] ??
    ''])));
  }

  function fileRows(p) {
    if (!/\.(csv|json)$/i.test(p.name)) return onMac();
    const text = readText(p.data);
    if (/\.csv$/i.test(p.name)) return csv(text);
    const obj = JSON.parse(text),
      data = Array.isArray(obj) ? obj : [obj];
    if (data.some(r => !r || typeof r !== 'object' || Array.isArray(r))) refuse(
      'Choose an array of JSON objects.');
    return data;
  }

  function newAction(p) {
    if (!p.label?.trim() || !p.audience?.length) refuse('Enter a label and choose an agent.');
    p.audience.forEach(usable);
    const id = unique(),
      val = p.values,
      kind = p.kind;
    let payload;
    if (kind === 'email') {
      const recipients = val.recipients.split(',').map(x => x.trim());
      if (!val.subject.trim() || !val.body.trim() || recipients.some(r => !/^.+@.+\..+$/.test(r))) refuse(
        'Enter valid recipients, a subject and a message.');
      payload = {
        recipients,
        subject: val.subject,
        body: val.body
      };
      if (val.attachment) payload.attachment = {
        name: val.attachment.name,
        size: atob(val.attachment.data).length
      };
    } else if (kind === 'event') {
      if (!val.title || !val.calendar || Date.parse(val.end) <= Date.parse(val.start)) refuse(
        'Enter the event details and a later end time.');
      payload = {
        ...val
      };
    } else if (kind === 'data') {
      const list = fileRows(val).slice(0, 100);
      payload = {
        name: val.name,
        fields: val.fields,
        count: list.length
      };
      rows.set(id, list.map(r => Object.fromEntries(val.fields.map(k => [k, r[k] ?? null]))));
    } else return onMac();
    ws.actions.unshift({
      id,
      fingerprint: unique(),
      kind,
      label: p.label,
      state: 'ready',
      audience: p.audience,
      payload,
      handles: Object.fromEntries(p.audience.map(id => [id, 'preview-' + unique()]))
    });
    return {
      id
    };
  }

  function actions(op, p) {
    const a = ws.actions.find(x => x.id === p.identifier) || refuse('This action is unavailable.');
    if (op === 'workspace-remove') {
      ws.actions = ws.actions.filter(r => r !== a);
      rows.delete(a.id);
      return {};
    }
    if (op === 'workspace-decide') {
      if (a.state !== 'pending' || a.fingerprint !== p.fingerprint) refuse('The request has changed.');
      if (p.approve) usable(a.applicant);
      a.state = p.approve ? (a.kind === 'event' ? 'created' : 'sent') : 'declined';
      return {
        status: a.state
      };
    }
    const g = usable(p.agent);
    if (!a.audience.includes(g.id)) refuse('Outside this connection’s scope.');
    let result;
    if (p.tool === 'read_private_fields') {
      const source = rows.get(a.id);
      result = source ? {
        fields: a.payload.fields,
        rows: source.map(r => a.payload.fields.map(k => screenCell(k, r[k], g.id))),
        limited_to_100_rows: false
      } : copy(sample.fields);
    } else {
      if (p.tool === 'request_private_action' && a.state === 'ready') {
        a.state = 'pending';
        a.applicant = g.id;
      }
      result = {
        reference: a.handles[g.id],
        kind: a.kind,
        label: a.label,
        status: a.state
      };
      if (a.state === 'sent' || a.state === 'created') result.simulated = true;
    }
    ws.receipts.unshift({
      agent: g.id,
      at: now(),
      tool: p.tool,
      response: copy(result)
    });
    g.remaining = Math.max(0, g.remaining - 1);
    audit.push({
      at: now(),
      agent: g.id,
      tool: p.tool,
      status: 'released'
    });
    return result;
  }

  function handle(op, p) {
    switch (op) {
      case 'preview-reset':
        reset();
        tokenMaps.clear();
        return {};
      case 'workspace-state':
        return ws;
      case 'client-context':
        return {
          records: ws.records.filter(available)
        };
      case 'workspace-note':
        insert(p.kind, p.text, p.private);
        return {};
      case 'memory-edit': {
        const r = record(p.ref);
        if (!p.text.trim() || p.expected_hash !== r.text_hash) refuse('Check this correction.');
        r.text = p.text.trim();
        r.text_hash = unique();
        return {};
      }
      case 'memory-retire':
        record(p.ref).retired = p.retired;
        return {};
      case 'memory-priority':
        record(p.ref).core = p.core;
        return {};
      case 'memory-policy': {
        const r = record(p.ref);
        if (r.source_device_only && !p.never_share) refuse('The source is device-only.');
        r.never_share = p.never_share;
        return {};
      }
      case 'memory-state':
        return {
          records: ws.records, proposals: ws.proposals, tasks: []
        };
      case 'memory-decide': {
        const a = ws.proposals.find(v => v.id === p.proposal_id) || refuse('No pending change.');
        if (p.accept) insert(a.kind || 'memories', a.text);
        ws.proposals = ws.proposals.filter(x => x !== a);
        return {};
      }
      case 'context-preview':
        return importRows(p);
      case 'context-commit': {
        const batch = previews.get(p.id) || refuse('Review this import again.');
        const refs = [];
        let skipped = 0;
        for (const index of p.indices) {
          const v = batch.items[index];
          if (ws.records.some(r => r.text === v.text && r.kind === v.kind)) {
            skipped++;
            continue;
          }
          refs.push(insert(v.kind, v.text, v.device_only).ref);
        }
        previews.delete(p.id);
        imports.unshift({
          id: p.id,
          label: batch.name,
          count: refs.length,
          refs,
          at: now()
        });
        return {
          added: refs.length,
          skipped,
          batch_id: p.id
        };
      }
      case 'context-status':
        return {
          sources: [], imports
        };
      case 'context-remove': {
        const batch = imports.find(x => x.id === p.id) || refuse('This import is unavailable.');
        ws.records = ws.records.filter(r => !batch.refs.includes(r.ref));
        imports = imports.filter(x => x !== batch);
        return {};
      }
      case 'context-transfer-status':
        return {
          waiting: false
        };
      case 'context-transfer-start':
        return {
          prompt:
            'Export the memories, preferences and reusable instructions you can see about me. Group them under Memories and Skills so I can review and paste them into Airlock.'
        };
      case 'library':
        return {
          items: ws.records.filter(available).map(r => ({
            ...r,
            source_id: r.ref,
            suggested: redact(r.text)
          }))
        };
      case 'workspace-connect': {
        const g = p.identifier ? usable(p.identifier) : {
          id: unique(),
          name: p.agent,
          mode: 'automatic',
          status: 'configured',
          remaining: p.max_calls,
          expires: now() + p.lifetime
        };
        const ids = Object.keys(p.selection);
        for (const ref of ids) {
          const r = record(ref);
          if (!available(r) || p.selection[ref] !== r.text_hash) refuse('A selected record changed.');
        }
        g.scope = {
          records: ids,
          disclose_records: p.excerpt_selection,
          disclose: !!p.excerpt_selection.length,
          compute: p.compute
        };
        g.device = {
          mail: p.mail,
          calendar: p.calendar
        };
        g.proposals = p.proposals;
        if (!p.identifier) ws.agents.push(g);
        return {
          id: g.id
        };
      }
      case 'client-status':
        return {
          status: grant(p.id).last_read ? 'verified' : 'waiting'
        };
      case 'revoke':
        grant(p.id).status = 'revoked';
        return {};
      case 'create': {
        const id = unique();
        ws.agents.push({
          id,
          name: p.agent,
          scope: null,
          mode: 'reviewed',
          status: 'configured',
          remaining: p.max_calls,
          expires: now() + p.lifetime,
          capabilities: {}
        });
        return {
          id,
          token: 'preview-only-' + id
        };
      }
      case 'automatic':
        grant(p.identifier).mode = p.enabled ? 'automatic' : 'reviewed';
        return {};
      case 'capabilities':
        grant(p.identifier).capabilities = {
          skill_execution: p.skill_execution,
          context_updates: p.context_updates
        };
        return {};
      case 'saved-dot':
        return {
          configured: false
        };
      case 'private-phrases':
        if (p.phrases) {
          if (p.phrases.some(v => v.length < 2 || v.length > 300)) refuse(
            'Each phrase needs 2 to 300 characters.');
          phrases = p.phrases;
        }
        return {
          phrases
        };
      case 'workspace-screen': {
        if (!p.text.trim()) refuse('Enter a sample.');
        if (p.kind === 'text') return {
          result: redact(p.text)
        };
        const v = JSON.parse(p.text);
        if (!v || typeof v !== 'object' || Array.isArray(v)) refuse('Enter one JSON object.');
        return {
          result: Object.fromEntries(Object.entries(v).map(([k, x]) => [k, screenCell(k, x, p.identifier ||
            'temporary')]))
        };
      }
      case 'workspace-sources':
        return {
          items: p.source === 'calendar' ? [{
            title: 'Cypress review · fictional',
            recipients: ['jon@example.com']
          }] : [{
            title: 'Pilot follow-up · fictional',
            recipient: 'mara@example.com'
          }]
        };
      case 'workspace-fields': {
        const data = fileRows(p);
        return {
          tables: [],
          fields: Array.from(new Set(data.slice(0, 100).flatMap(Object.keys))),
          count: Math.min(data.length, 100)
        };
      }
      case 'workspace-create':
        return newAction(p);
      case 'workspace-decide':
      case 'workspace-remove':
      case 'workspace-try':
        return actions(op, p);
      case 'gmail-state':
        return {
          account: '', configured: false, sign_in: 'not_connected'
        };
      case 'audit':
        return {
          events: audit
        };
      case 'workbench':
        return {
          packages, artifacts: [], shared: {
            items: [],
            history: []
          }
        };
      case 'skill-builtin':
        return sample.builtin;
      case 'skill-install':
        packages = [{
          ...sample.builtin,
          skill_id: 'example-brief',
          enabled: p.enabled
        }];
        return {};
      case 'skill-enable': {
        const pkg = packages.find(v => v.skill_id === p.skill_id) || refuse('Select a package.');
        pkg.enabled = p.enabled;
        return {};
      }
      case 'skill-remove':
        packages = packages.filter(v => v.skill_id !== p.skill_id);
        return {};
      case 'test-state':
        return {
          ...sample.fixture, checks
        };
      case 'test-check': {
        if (!sample.checks[p.step]) refuse('Unknown check.');
        if (p.step === 'approve' && !checks.propose) refuse('Try the proposal first.');
        return checks[p.step] = sample.checks[p.step];
      }
      case 'test-reset':
        checks = {};
        return {};
      case 'near-state':
        return walk;
      case 'near-reset':
        walk = {
          loaded: true,
          records: sample.walk.records,
          result: null,
          grant: null
        };
        return walk;
      case 'near-grant':
        walk.grant = {
          expires: now() + 600,
          revoked: false
        };
        return walk;
      case 'near-revoke':
        walk.grant = null;
        walk.pending = null;
        return walk;
      case 'near-review': {
        walk.pending = null;
        if (p.mode !== 'rehearsal') return onMac();
        if (!walk.grant || p.ids.includes('financial-note')) return {
          blocked: true,
          reason: 'The selected record must stay on this device.'
        };
        walk.pending = unique();
        return {
          destination: 'Scripted preview',
          payload: sample.walk.payload,
          approval_id: walk.pending,
          sha256: walk.pending
        };
      }
      case 'near-send':
        if (!walk.pending || p.approval_id !== walk.pending) refuse('Review this request first.');
        walk.pending = null;
        walk.result = sample.walk.result;
        return walk.result;
      case 'near-setup-status':
        return {
          model: 'NEAR AI Cloud', sdk: {
            ready: false,
            message: 'Available in the Mac app'
          }, key_present: false, deployment_approved: false
        };
      case 'evaluation':
      case 'prepared-review':
        return {
          message: 'Run device verification in the Mac app.'
        };
      case 'close-personal':
        return {};
      default:
        return onMac();
    }
  }
  window.airlockExample = (op, params) => copy(handle(op, params || {}));
})();
