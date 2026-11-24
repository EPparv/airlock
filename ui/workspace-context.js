'use strict';

addPage('context', 'Context & memory', 'home', host => {
  const m = el('div', null, 'menu');
  host.append(m);
  for (const [label, key] of [
      ['Memories', 'memories'],
      ['Skills', 'skills'],
      ['Import context', 'import'],
      ['Sources & imports', 'sources'],
      ['Proposed changes', 'proposals']
    ]) choose(m, label, key);
}, false);

function addNote(kind) {
  const f = modal(kind === 'skills' ? 'Add skill' : 'Add memory'),
    t = field(f, kind === 'skills' ? 'Instructions' : 'Memory', el('textarea'));
  const local = check(f, 'Keep on this device only');
  formAction(f, 'Save', async () => {
    await api('workspace-note', {
      kind,
      text: t.value,
      private: local.checked
    });
    close();
    await refresh();
    flash('Saved on this device.');
  });
  t.focus();
}

function recordList(host, records, kind) {
  const search = input('search');
  search.className = 'search';
  search.placeholder = kind === 'skills' ? 'Search skills' : 'Search memories';
  search.setAttribute('aria-label', search.placeholder);
  const list = el('div', null, 'list');
  put(host, search, list);

  function paint() {
    list.replaceChildren();
    const q = search.value.trim().toLowerCase(),
      visible = records.filter(r => r.kind === kind && (r.text + ' ' + r.title).toLowerCase().includes(q));
    if (!visible.length) empty(list, q ? 'No matches.' : kind === 'skills' ? 'No saved instructions.' :
      'No memories yet.');
    for (const r of visible) {
      const first = r.text.trim().split('\n')[0];
      const flags = [r.core ? 'Pinned' : '', r.retired ? 'Retired' : r.stale ? 'Source changed' : r.never_share ?
        'Device only' : r.sensitive ? 'Private tasks only' : ''
      ].filter(Boolean);
      item(list, first.length > 108 ? first.slice(0, 108) + '…' : first, flags.join(' · '), () => go('record', {
        ref: r.ref,
        kind
      }));
    }
  }
  search.oninput = paint;
  paint();
}
addPage('memories', 'Memories', 'context', async (host, opt, bar) => {
  bar.append(button('Add memory', () => addNote('memories'), 'primary'));
  recordList(host, (await api('workspace-state')).records, 'memories');
});
addPage('skills', 'Skills', 'context', async (host, opt, bar) => {
  bar.append(button('Add skill', () => addNote('skills'), 'primary'));
  recordList(host, (await api('workspace-state')).records, 'skills');
  const tools = section(host, 'Local skills');
  choose(tools, 'Skill packages', 'packages');
  choose(tools, 'Generated files', 'files');
});
addPage('record', 'Record', 'memories', async (host, opt, bar) => {
  const r = (await api('workspace-state')).records.find(i => i.ref === opt.ref);
  if (!r) throw Error('This record is unavailable.');
  const isSkill = r.kind === 'skills',
    label = isSkill ? 'Skill' : 'Memory';
  bar.querySelector('h1').textContent = label;
  if (isSkill) host.closest('.page').querySelector('.back').replaceWith(button('Skills', () => go('skills'),
    'back'));
  host.append(el('p', r.text, 'record-text'));
  if (r.editable && !r.retired && !r.stale) bar.append(button('Edit', () => {
    const f = modal('Edit ' + label.toLowerCase()),
      t = field(f, isSkill ? 'Instructions' : 'Memory', el('textarea'));
    t.value = r.text;
    formAction(f, 'Save changes', async () => {
      await api('memory-edit', {
        ref: r.ref,
        text: t.value,
        expected_hash: r.text_hash
      });
      close();
      await refresh();
    });
  }));
  const actions = section(host, 'Recall & sharing');
  if (r.core || !r.never_share) row(actions, r.core ? 'Unpin from core profile' : 'Pin to core profile',
  async () => {
      await api('memory-priority', {
        ref: r.ref,
        core: !r.core
      });
      await refresh();
    });
  if (!r.source_device_only && !r.retired && !r.stale) row(actions, r.never_share ? 'Allow agent selection' :
    'Keep on this device only', async () => {
      await api('memory-policy', {
        ref: r.ref,
        never_share: !r.never_share
      });
      await refresh();
    });
  row(actions, r.retired ? 'Restore to recall' : 'Retire from recall', async () => {
    await api('memory-retire', {
      ref: r.ref,
      retired: !r.retired
    });
    await refresh();
  });
  note(host, r.source_device_only ? 'Marked device-only at its source.' : r.retired ?
    'Retired records stay out of agent requests.' : r.stale ?
    'The source changed. Review its original import.' : r.core ?
    'Pinned records are included in requests from agents with access.' :
    'Only agents you select can use this record.');
  if (r.parents?.length) note(host, 'Depends on ' + r.parents.length + ' source records.');
});

function reviewImport(result) {
  const f = modal('Review import'),
    checks = [];
  if (result.scope) note(f, result.scope);
  const rows = group(f, 'Records to add');
  rows.className = 'checklist';
  result.items.forEach((r, i) => checks.push([i, check(rows, (r.chat_source ? r.chat_source + ' · ' : r.kind === 'skills' ? 'Skill · ' : '') + r.text + (r
    .device_only ? ' · device only' : ''), !r.chat_source)]));
  formAction(f, 'Add selected records', async () => {
    const indices = checks.filter(([, c]) => c.checked).map(([i]) => i);
    if (!indices.length) throw Error('Select at least one record.');
    const saved = await api('context-commit', {
      id: result.id,
      indices
    });
    const d = modal('Import saved');
    note(d, saved.added + ' added · ' + saved.skipped + ' already in your library.');
    if (saved.batch_id) d.append(button('Undo import', async () => {
      await api('context-remove', {
        id: saved.batch_id
      });
      close();
      await refresh();
      flash('Import removed.');
    }));
    d.append(button('View memories', () => go('memories'), 'primary'));
  });
}
addPage('import', 'Import context', 'context', async host => {
  const f = el('div', null, 'form');
  host.append(f);
  const text = field(f, 'Paste context', el('textarea'));
  text.placeholder = 'Memories, instructions, or an exported conversation';
  const file = field(f, 'Or choose a file', input('file'));
  file.accept = '.md,.txt,.json,.zip,.skill,.mdc';
  const mode = field(f, 'Import as', select([
    ['auto', 'Detect automatically'],
    ['memories', 'Memories'],
    ['skills', 'Skills'],
    ['chat', 'ChatGPT or Claude conversation']
  ]));
  formAction(f, 'Review import', async () => {
    if (!file.files[0] && !text.value.trim()) throw Error('Paste some text or choose a file.');
    const source = file.files[0] || new File([text.value], 'Pasted context.md', {type: 'text/plain'});
    async function review(selected, kind) {
      const data = await upload(selected);
      reviewImport(await api('context-preview', {name: data.name, content: data.data, kind}));
    }
    if (source.size <= 4 * 1024 * 1024 && mode.value !== 'chat') return review(source, mode.value);
    if (/\.zip$/i.test(source.name)) {
      if (source.size > 4 * 1024 * 1024) throw Error('Unzip this export and choose its conversations JSON file.');
      return review(source, mode.value);
    }
    if (mode.value !== 'chat' && (mode.value !== 'auto' || !/\.json$/i.test(source.name))) {
      return review(source, mode.value);
    }
    if (source.size > 64 * 1024 * 1024) throw Error('Choose a conversations JSON file up to 64 MB, or paste one conversation.');
    let data;
    try { data = JSON.parse(await source.text()); }
    catch { throw Error('Choose a complete ChatGPT or Claude conversation JSON file.'); }
    const conversations = (Array.isArray(data) ? data : Array.isArray(data?.conversations) ? data.conversations : [data])
      .filter(c => c && (c.mapping || Array.isArray(c.chat_messages)));
    if (!conversations.length) throw Error('No ChatGPT or Claude conversations found in this file.');
    async function reviewConversation(c) {
      const conversation = new File([JSON.stringify(c)], 'conversation.json', {type: 'application/json'});
      if (conversation.size > 4 * 1024 * 1024) throw Error('This conversation exceeds 4 MB. Paste the individual excerpts you want to keep.');
      return review(conversation, 'chat');
    }
    if (conversations.length === 1) return reviewConversation(conversations[0]);
    const chooser = modal('Choose a conversation');
    const chosen = field(chooser, 'Conversation', select(conversations.map((c, i) =>
      [String(i), String(c.title || c.name || 'Conversation ' + (i + 1)).slice(0, 160)])));
    formAction(chooser, 'Review messages', () => reviewConversation(conversations[Number(chosen.value)]));
  });
  const transfer = details(host, 'Bring context from another agent');
  note(transfer,
    'Copy the request into the agent that already has your context. Review its reply before saving.');
  const result = el('div');
  transfer.append(button('Get transfer request', async () => {
    const v = await api('context-transfer-start');
    result.replaceChildren();
    put(result, el('pre', v.prompt), button('Copy request', () => copyText(v.prompt)));
  }), button('Check incoming transfer', async () => {
    const r = await api('context-transfer-status');
    if (r.preview) reviewImport(r.preview);
    else flash(r.waiting ? 'Waiting for the agent to send its context.' : r.saved ?
      'Previous transfer saved.' : 'No incoming transfer.');
  }), result);
  const pending = await api('context-transfer-status');
  if (pending.preview) transfer.append(button('Review incoming records', () => reviewImport(pending
  .preview)));
});
addPage('sources', 'Sources & imports', 'context', async host => {
  const s = await api('context-status'),
    linked = section(host, 'Linked sources');
  if (preview && !s.sources.length) empty(linked, 'Open the Mac app to link files from your agents.');
  for (const x of s.sources) {
    const l = el('div', null, 'entry');
    linked.append(l);
    const info = el('div');
    put(info, el('h3', x.label), el('p', x.error || (x.connected ? 'Connected' : x.files ? x.files +
      ' files available' : 'No supported files found'), 'muted'));
    const b = button(x.connected ? 'Disconnect' : 'Connect', async () => {
      await api('context-source', {
        source: x.id,
        enabled: !x.connected
      });
      await refresh();
    });
    b.disabled = !x.files && !x.connected;
    put(l, put(el('div', null, 'line'), info, b));
  }
  const imported = section(host, 'Previous imports');
  if (!s.imports.length) empty(imported, 'No imports yet.');
  for (const v of s.imports) item(imported, v.label, v.count + ' records · ' + when(v.at), () =>
    confirmAction('Remove this import?', v.label, 'Remove import', async () => {
      await api('context-remove', {
        id: v.id
      });
      await refresh();
    }, true));
  choose(host, 'Shared note history', 'history');
});
addPage('proposals', 'Proposed changes', 'context', async host => {
  const s = await api('memory-state'),
    pending = s.proposals.filter(p => p.status === 'pending'),
    list = el('div', null, 'list');
  host.append(list);
  if (!pending.length) empty(list, 'No changes waiting for review.');
  for (const p of pending) item(list, p.text || 'Remove a saved record', (names[p.agent] || p.agent) + ' · ' +
    p.operation, () => {
      const f = modal('Review change');
      note(f, (names[p.agent] || p.agent) + ' · ' + p.operation);
      f.append(el('p', p.text || 'Remove this record.', 'record-text'));
      for (const [name, accept] of [
          ['Accept change', true],
          ['Decline', false]
        ]) f.append(button(name, async () => {
        await api('memory-decide', {
          proposal_id: p.id,
          accept
        });
        close();
        await refresh();
      }, accept ? 'primary' : 'secondary'));
    });
  choose(host, 'Shared note history', 'history');
});
addPage('history', 'Shared note history', 'context', async host => {
  const data = (await api('workbench')).shared;

  function undo(h) {
    confirmAction('Undo this change?', h.text || 'Restore the previous revision.', 'Undo change',
async () => {
      await api('shared-undo', {
        reference: h.reference,
        expected_revision: h.revision
      });
      await refresh();
    });
  }
  const box = el('div', null, 'list');
  host.append(box);
  if (!data.items.length && !data.history.length) empty(box, 'No shared notes yet.');
  for (const n of data.items) {
    const available = data.history.some(h => h.reference === n.reference && h.revision === n.revision);
    item(box, n.text, (names[n.agent] || n.agent) + ' · revision ' + n.revision, available ? () => undo(n) :
      null);
  }
  for (const h of data.history.filter(h => h.operation === 'delete' && !data.items.some(n => n.reference === h
      .reference))) item(box, 'Deleted note', 'Undo deletion', () => undo(h));
});

function packageReview(p) {
  const f = modal(p.name);
  note(f, p.description);
  details(f, 'Included files', el('pre', p.files.join('\n')));
  const exec = check(f, 'Allow this package to run its local scripts', false);
  formAction(f, 'Install package', async () => {
    await api('skill-install', {
      preview: p.preview,
      enabled: exec.checked
    });
    close();
    await refresh();
  });
}
addPage('packages', 'Skill packages', 'skills', async (host, opt, bar) => {
  const data = await api('workbench');
  const list = el('div', null, 'list');
  host.append(list);
  if (!data.packages.length) empty(list, 'No packages installed.');
  for (const p of data.packages) item(list, p.name, p.enabled ? 'Execution enabled' : 'Execution paused',
  () => {
      const f = modal(p.name);
      note(f, p.description);
      details(f, 'Scripts and dependencies', el('pre', [...p.scripts, ...p.dependencies].map(x =>
        typeof x === 'string' ? x : JSON.stringify(x)).join('\n') || 'None'));
      f.append(button(p.enabled ? 'Pause execution' : 'Enable execution', async () => {
        await api('skill-enable', {
          skill_id: p.skill_id,
          enabled: !p.enabled
        });
        close();
        await refresh();
      }));
      f.append(button('Remove package', () => confirmAction('Remove package?', p.name, 'Remove',
  async () => {
        await api('skill-remove', {
          skill_id: p.skill_id
        });
        await refresh();
      }, true), 'danger'));
    });
  bar.append(button('Import ZIP', () => {
    const f = modal('Import skill package');
    const file = field(f, 'Package ZIP', input('file'));
    file.accept = '.zip,.skill';
    formAction(f, 'Review package', async () => {
      if (preview) return nativeOnly('Import a skill package');
      const value = await upload(file.files[0], 16 * 1024 * 1024);
      packageReview(await api('skill-preview', {
        content: value.data
      }));
    });
  }));
  if (!data.packages.some(p => p.name === 'prepare-local-brief')) host.append(button('Add briefing skill',
    async () => packageReview(await api('skill-builtin'))));
});
async function saveOutput(a, file) {
  const result = await api('artifact-read', {
    reference: a.reference,
    index: file.index
  });
  const native = window.webkit?.messageHandlers?.airlockSettings;
  if (native) {
    await native.postMessage({
      action: 'save-file',
      name: result.name.split('/').pop(),
      content: result.content
    });
    return;
  }
  const bytes = Uint8Array.from(atob(result.content), v => v.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {
    type: 'application/octet-stream'
  }));
  const link = el('a');
  link.download = result.name.split('/').pop();
  link.href = url;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
addPage('files', 'Generated files', 'skills', async host => {
  const data = await api('workbench');
  const list = el('div', null, 'list');
  host.append(list);
  if (!data.artifacts.length) empty(list, 'Files from local skill runs appear here.');
  for (const a of data.artifacts) {
    const f = details(list, (names[a.agent] || a.agent) + ' · ' + when(a.at));
    note(f, a.status);
    for (const v of a.files) f.append(button(v.name, () => saveOutput(a, v)));
    f.append(button('Delete output', () => confirmAction('Delete this output?',
      'This removes the generated files from Airlock.', 'Delete output', async () => {
        await api('artifact-remove', {
          reference: a.reference
        });
        await refresh();
      }, true), 'danger'));
  }
});
