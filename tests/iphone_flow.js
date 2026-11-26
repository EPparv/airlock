// WKWebView.callAsyncJavaScript supplies phase as an argument.
const nap = ms => new Promise(done => setTimeout(done, ms));
async function until(fn, description) {
  for (let i = 0; i < 180; i++) { const value = fn(); if (value) return value; await nap(40); }
  throw Error(description + ' — ' + document.body.innerText.slice(0, 250));
}
const findButton = label => [...document.querySelectorAll('button')].find(b => b.textContent === label && !b.disabled);
async function press(label) {
  const b = await until(() => findButton(label), 'Button ' + label);
  b.click(); await nap(100);
}
function write(label, text) {
  const field = [...document.querySelectorAll('label')].find(l => l.firstChild.textContent === label);
  if (!field) throw Error('Missing field ' + label); field.querySelector('input,textarea').value = text;
}
const title = name => until(() => document.querySelector('h1')?.textContent === name, 'Heading ' + name);
const seen = text => until(() => document.querySelector('main').innerText.includes(text), text);
const message = 'Cypress pilot contact sam@example.com';
const hidden = 'Confidential fixture';
const suggested = 'Draft every second Friday';
if (!isSecureContext || location.protocol !== 'https:' || document.documentElement.scrollWidth > innerWidth + 1) {
  throw Error('Phone viewport or HTTPS is unavailable.');
}
await title('Airlock');
await press('Try a sample'); await title('Sample workspace');
await seen('two-paragraph'); await seen('[email-');
if (document.querySelector('main').innerText.includes('editor@example.com')) throw Error('Unfiltered sample email.');
await press('Planning agent'); await seen('Friday at 10 am');
if (document.querySelector('main').innerText.includes('two-paragraph')) throw Error('Planning session read the writing memory.');
await press('Revoke access'); await seen('Access revoked.');
await press('Writing agent'); await seen('two-paragraph');
await press('Connect my agent'); await title('Connect agent');
const actions = () => [...document.querySelectorAll('main button:not(.back), main a')].map(n => n.textContent);
if (JSON.stringify(actions()) !== JSON.stringify(['Set up on Mac'])) throw Error('Expected one iPhone connection action.');
let handedOff;
Object.defineProperty(navigator, 'share', {configurable:true, value:async data => { handedOff = data.url; }});
await press('Set up on Mac');
delete navigator.share;
if (handedOff !== 'https://try-airlock.parv223885.chatgpt.site/#mac') throw Error('Incorrect Mac handoff.');
location.hash = '#mac'; await title('Mac setup');
if (document.querySelector('a').href !== 'https://try-airlock.parv223885.chatgpt.site/Airlock-Mac.zip') throw Error('Missing direct Mac download.');
location.hash = '#connect'; await title('Connect agent');
await press('‹ Airlock'); await press('Privacy & connections'); await press('Pair this iPhone');
write('Pairing link from your Mac','https://example.com/wrong#pair=bad'); await press('Check link');
await until(() => document.querySelector('#notice').textContent.includes('complete one-time'), 'Invalid pairing link rejected');
const fakePair = 'https://test-mac.example.org/phone#pair=' + 'A'.repeat(43);
write('Pairing link from your Mac',fakePair); await press('Check link');
if (document.querySelector('a')?.href !== fakePair || document.querySelector('input').value) throw Error('Pairing link handoff failed.');
await press('‹ Privacy & connections'); await press('‹ Airlock'); await press('Context & memory'); await press('Share an excerpt');
if (phase === 1) {
  await title('Share an excerpt'); write('Text to share','Send the draft to editor@example.org');
  await press('Review excerpt'); const approved = document.querySelectorAll('textarea')[1];
  if (!approved?.readOnly || !approved.value.includes('[email-') || approved.value.includes('example.org')) throw Error('One-time excerpt leaked raw email.');
} else {
  await until(() => findButton('Unlock vault'), 'saved privacy settings require unlocking before one-time sharing');
}
await press('‹ Context & memory'); await press('‹ Airlock'); await title('Airlock');
history.replaceState(null,'',location.pathname+location.search);
if (phase === 2) {
  await press('Context & memory'); await press('Memories'); await until(() => findButton('Unlock vault'), 'existing vault');
  write('Passphrase','incorrect phrase'); await press('Unlock vault');
  await until(() => document.querySelector('#notice')?.textContent.includes('could not be opened'), 'wrong passphrase blocked');
  write('Passphrase','Local iPhone fixture 42'); await press('Unlock vault');
  await seen(message); await seen(suggested); await seen(hidden);
  return true;
}
await press('Context & memory'); await press('Memories'); await until(() => findButton('Create vault'), 'new vault');
write('Passphrase','Local iPhone fixture 42'); write('Confirm passphrase','Local iPhone fixture 42');
await press('Create vault');
await press('Add memory'); write('Memory', message); await press('Save memory');
await press('Add memory'); write('Memory', hidden);
document.querySelector('input[type=checkbox]').checked = true; await press('Save memory');
await press('‹ Context & memory'); await press('‹ Airlock'); await press('Privacy & connections'); await press('Local test sessions');
async function create(name) {
  await press('New test session'); write('Session name',name); await press('Create session'); await title(name);
}
async function share() {
  await press('Shared records'); await title('Shared records');
  const rows = [...document.querySelectorAll('label.check')];
  if (rows.length !== 1 || rows[0].textContent !== message) throw Error('Private record appeared in scope editor.');
  rows[0].querySelector('input').checked = true; await press('Save access'); await press('Try session');
  await press('Read shared memory');
  const text = await until(() => document.querySelector('.result')?.textContent, 'filtered record');
  if (!text.includes('Cypress pilot') || text.includes('sam@example.com') || !text.includes('[email-')) throw Error('Email was not filtered.');
  return text;
}
await create('Atlas'); const fromAtlas = await share();
write('Propose a memory',suggested); await press('Send for review');
await press('‹ Agent access'); await press('‹ Local test sessions');
await create('Ember'); await press('Try session'); await press('Read shared memory'); await seen('No shared records.');
await press('‹ Agent access'); const fromEmber = await share();
if (fromAtlas === fromEmber) throw Error('Two sessions share an email token.');
await press('‹ Agent access'); await press('‹ Local test sessions'); await press('Atlas');
await press('Revoke session'); await press('Revoke access'); await title('Local test sessions');
if (findButton('Atlas')) throw Error('Revoked session survived.');
await press('Ember'); await press('Try session'); write('Propose a memory',suggested); await press('Send for review');
await press('‹ Agent access'); await press('‹ Local test sessions'); await press('‹ Privacy & connections'); await press('‹ Airlock');
await press('Context & memory'); await press('Proposed changes'); await seen(suggested); await press('Approve');
await seen('No changes waiting'); await press('‹ Context & memory'); await press('Memories'); await seen(suggested);
const envelope = await new Promise((resolve,reject) => {
  const open = indexedDB.open('airlock-iphone-v1');
  open.onsuccess = () => { const db = open.result, r = db.transaction('vault').objectStore('vault').get('device');
    r.onsuccess = () => { const value = r.result; db.close(); resolve(value); }; r.onerror = () => reject(Error('read')); };
});
if (!envelope.ciphertext || [message,hidden,suggested].some(t => JSON.stringify(envelope).includes(t))) throw Error('Vault must persist as ciphertext.');
const stale = await PhoneVault.open('Local iPhone fixture 42', false);
const current = await PhoneVault.open('Local iPhone fixture 42', false);
const ember = current.state.agents.find(a => a.name === 'Ember').id;
await PhoneVault.changed(current, s => PhoneVault.revoke(s, ember));
try { await PhoneVault.read(stale, ember); throw Error('A stale browser session released a revoked record.'); }
catch (error) { if (!error.message.includes('changed in another tab')) throw error; }
try { await PhoneVault.changed(stale, s => PhoneVault.addRecord(s, 'Outdated tab')); throw Error('An outdated tab replaced the current grant.'); }
catch (error) { if (!error.message.includes('changed in another tab')) throw error; }

return true;
