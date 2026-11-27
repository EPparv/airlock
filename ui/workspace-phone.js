'use strict';

async function phoneQR(host, action, url, label) {
  const native = window.webkit?.messageHandlers?.airlockSettings;
  if (!native) return;
  try {
    const png = await native.postMessage({action, url});
    const img = el('img'); img.alt = label; img.className = 'pair-code';
    img.src = 'data:image/png;base64,' + png;
    host.append(img);
  } catch { note(host, 'Use the copy button below to open the link in Safari.'); }
}

addPage('pair-iphone', 'Pair iPhone', 'privacy', async host => {
  if (preview) {
    note(host, 'Open Airlock on your Mac to pair an iPhone.');
    return;
  }
  const [bridge, state, ws] = await Promise.all([api('remote-state'),api('phone-state'),api('workspace-state')]);
  if (!bridge.enabled || !bridge.listening) {
    note(host, 'Enable the HTTPS bridge so Safari on your iPhone can reach this Mac.');
    host.append(button('Start temporary link', () => startTemporaryLink(() => go('pair-iphone')), 'primary'),
      button('Use my HTTPS domain', () => go('remote-bridge')));
  } else if (bridge.mode === 'temporary' && !bridge.verified) {
    if (bridge.verification?.url) {
      note(host, 'Scan the link with your iPhone. Enter the code it shows here on your Mac.');
      await phoneQR(host, 'phone-proof-qr', bridge.verification.url, 'Scan to check this Mac’s temporary link.');
    }
    temporaryLinkVerification(host, bridge, refresh);
  } else {
    const form = el('div', null, 'form');host.append(form);
    note(form, 'Choose what this iPhone can read. A connection lasts one hour or 100 calls. Requested writes need approval on your Mac.');
    const records = details(form, 'Shared records');
    const choices = ws.records.filter(r => !r.never_share && !r.stale && !r.retired && !r.sensitive)
      .map(r => [r,check(records, r.text.slice(0,180))]);
    if (!choices.length) note(records, 'Add a shareable memory or skill in Context & memory.');
    note(form, 'The HTTPS proxy handles the connection and can see shared data. Anyone with an unused pairing link can claim it.');
    formAction(form, 'Create pairing link', async () => {
      const selection = Object.fromEntries(choices.filter(([,box]) => box.checked).map(([r]) => [r.ref,r.text_hash]));
      const result = await api('phone-create',{selection, approved:true});
      const f = modal('Connect your iPhone');
      note(f, 'Scan with Camera or copy the link to Safari. Tap Connect to Mac within five minutes.');
      await phoneQR(f, 'phone-qr', result.url, 'Scan this one-time iPhone pairing code.');
      f.append(button('Copy one-time link', () => copyText(result.url)));
      formAction(f, 'Done', async () => { close(); await refresh(); });
    });
  }
  const paired = section(host, 'iPhone connections');
  if (!state.devices.length) empty(paired, 'No active iPhone connections.');
  for (const peer of state.devices) {
    const label = 'iPhone · ' + peer.id.slice(-6);
    item(paired, label, (peer.state === 'paired' ? 'Paired' : 'Awaiting pairing') + ' · Expires ' + when(peer.expires), () => {
      const f = modal(label);
      f.append(button('Manage shared records and assigned access', () => go('agent',{id:peer.id, agent:'mcp'})));
      f.append(button('Revoke connection', async () => {
        await api('phone-revoke',{id:peer.id}); close(); await refresh();
      },'danger'));
    });
  }
});
