// Executed in iOS Simulator against the Mac's dedicated HTTPS bridge with fictional records.
const wait = async check => {
  for (let i = 0; i < 150; i++) {
    if (check()) return;
    await new Promise(r => setTimeout(r, 100));
  }
  throw Error('iPhone companion control did not finish: ' + document.getElementById('notice').textContent);
};
const get = id => document.getElementById(id);
if (location.hash) throw Error('Pairing fragment remained in history.');
get('connect').click(); await wait(() => !get('connected').hidden);
if (!get('scope').textContent.includes('1 shared record')) throw Error('Wrong phone scope.');
get('topic').value = 'Cypress'; get('search-form').requestSubmit();
await wait(() => get('records').innerText.includes('Thursday'));
const text=get('records').innerText;
if (text.includes('robin@example.test') || text.includes('Vermilion') || text.includes('device-only stone')) throw Error('Unexpected record or private field.');
get('refresh-actions').click();
await wait(() => get('actions').innerText.includes('Review fictional follow-up'));
get('actions').querySelector('button').click();
await wait(() => get('actions').innerText.includes('pending'));
get('disconnect').click(); await wait(() => get('connected').hidden);
if (get('records').textContent || get('actions').textContent || localStorage.length || sessionStorage.length) throw Error('Phone access persisted after disconnect.');
return true;
