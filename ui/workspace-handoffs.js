'use strict';

(() => {
  const statusNames = {
    assigned: 'Assigned',
    claimed: 'In progress',
    review: 'Ready for review',
    released: 'Shared',
    withdrawn: 'Withdrawn'
  };
  const displayName = key => names[key] || key;
  const connectionLabel = (name, id) => displayName(name) + ' · ' + id.slice(-6);
  const workerName = v => connectionLabel(v.worker_name, v.worker);
  const recipientName = v => connectionLabel(v.recipient_name, v.recipient);
  const paramsFor = v => ({id: v.id, revision: v.revision});

  async function saved(message) {
    close();
    await refresh();
    flash(message);
  }

  function review(title, caption, text, label, publish) {
    const f = modal(title);
    note(f, caption);
    f.append(el('p', text, 'record-text'));
    formAction(f, label, publish);
  }

  function assign(agents) {
    const f = modal('Assign a task');
    const options = agents.map(a => [a.id, connectionLabel(a.name, a.id) + ' · ' + a.purpose]);
    const worker = field(f, 'Assign to', select(options));
    const recipient = field(f, 'Share reviewed result with', select(options));
    recipient.value = agents[1].id;
    const text = field(f, 'Instruction', el('textarea'));
    text.maxLength = 5000;
    note(f, 'The agent picks this up when it checks Airlock for assignments.');
    formAction(f, 'Review assignment', async () => {
      const args = {worker: worker.value, recipient: recipient.value, instruction: text.value};
      const screened = await api('handoff-check-assignment', args);
      if (screened.blocked) throw Error('This instruction contains protected details. Edit it and check again.');
      const workerLabel = options.find(([id]) => id === args.worker)[1];
      review('Review assignment', 'Visible to ' + workerLabel, screened.text, 'Assign task', async () => {
        await api('handoff-assign', {...args, instruction: screened.text, approval: screened.approval, approved: true});
        await saved('Task assigned.');
      });
    });
  }

  function reviewReport(job) {
    const form = modal('Review report');
    const text = field(form, 'Text for ' + recipientName(job), el('textarea'));
    text.value = job.report;
    text.maxLength = 5000;
    note(form, 'Remove details the recipient should not see.');
    formAction(form, 'Check text', async () => {
      const args = {...paramsFor(job), text: text.value};
      const screened = await api('handoff-check-result', args);
      if (screened.blocked) throw Error('The text contains protected details. Edit it and check again.');
      review('Approve sharing', 'Visible to ' + recipientName(job), screened.text, 'Share result', async () => {
        await api('handoff-release', {...args, text: screened.text, approved: true});
        await saved('Result shared.');
      });
    });
  }

  function showJob(job) {
    const f = modal('Handoff details');
    f.append(facts([['Assigned to', workerName(job)], ['Recipient', recipientName(job)],
      ['Status', statusNames[job.status]], ['Assigned', when(job.created)]]));
    details(f, 'Task instruction', el('p', job.instruction, 'record-text'));
    if (job.report) details(f, 'Original report', el('p', job.report, 'record-text'));
    if (job.released) details(f, 'Approved result', el('p', job.released, 'record-text'), true);
    if (!job.available && job.status !== 'withdrawn') note(f, 'Connection access changed. Withdraw this handoff to close it.');
    if (job.status === 'review' && job.available) {
      formAction(f, 'Review result', () => preview ? nativeOnly('Review result') : reviewReport(job));
    }
    if (job.proposal) {
      const p = job.proposal;
      const detail = details(f, 'Suggested memory');
      detail.append(el('p', p.text, 'record-text'));
      if (p.status === 'pending') {
        note(detail, 'Saving creates a local memory. You choose which connections can read it.');
        for (const [label, accept] of [['Save memory', true], ['Decline memory', false]]) {
          detail.append(button(label, async () => {
            await api('memory-decide', {proposal_id: p.id, accept});
            await saved(accept ? 'Memory saved.' : 'Memory declined.');
          }));
        }
      } else note(detail, 'Memory proposal ' + p.status + '.');
    }
    const remove = job.status === 'withdrawn';
    const label = remove ? 'Remove handoff' : 'Withdraw handoff';
    f.append(button(label, () => {
      if (preview) return nativeOnly(label);
      confirmAction(label + '?', remove ? 'Remove this handoff. Previously shared text stays in disclosure receipts.' :
        'Both agents lose access to this handoff. They may keep a copy of anything they already read.',
        label, async () => {
          await api(remove ? 'handoff-remove' : 'handoff-withdraw', paramsFor(job));
          await saved(remove ? 'Handoff removed.' : 'Handoff withdrawn.');
        }, true);
    }, 'danger'));
  }

  addPage('handoffs', 'Agent handoffs', 'activity', async (host, options, bar) => {
    if (!preview) bar.append(button('Refresh', refresh));
    const example = {
      id: 'example', status: 'review', worker: 'example-codex', recipient: 'example-cursor',
      worker_name: 'codex', recipient_name: 'cursor', available: true,
      instruction: 'Check the release checklist for missing steps.',
      report: 'The rollback step needs an owner.', created: 0
    };
    const {agents, handoffs} = preview ? {agents: [], handoffs: [example]} : await api('handoff-state');
    if (preview) note(host, 'Example handoff. Connect agents in the Mac app to assign work.');
    if (!preview && agents.length < 2) {
      note(host, 'Connect two agents to assign work and share a reviewed result.');
      choose(host, 'Connect agent', 'connect');
    } else host.append(button('Assign a task', () => preview ? nativeOnly('Assign a task') : assign(agents), 'primary'));
    const list = section(host, 'Handoffs');
    if (!handoffs.length) empty(list, 'No handoffs yet.');
    for (const job of handoffs) item(list, job.instruction,
      workerName(job) + ' → ' + recipientName(job) + ' · ' + statusNames[job.status], () => showJob(job));
  });
})();
