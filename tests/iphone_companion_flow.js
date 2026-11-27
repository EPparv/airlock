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
const originalFetch = window.fetch.bind(window);
let exchanges = 0, dropStatus = true;
window.fetch = async (url, options) => {
  if (url === '/phone/pair') {
    exchanges++;
    const reply = await originalFetch(url, options);
    if (!reply.ok) return reply;
    const paired = await reply.json();
    if (paired.count !== 1 || !Number.isFinite(paired.expires)) {
      throw Error('Mac pairing did not return the selected record count.');
    }
    // Simulate the previous Mac release. The one-use code has already been redeemed.
    delete paired.count;
    return new Response(JSON.stringify(paired), {headers:{'Content-Type':'application/json'}});
  }
  if (dropStatus && url === '/phone/status') {
    dropStatus = false;
    throw new TypeError('Failed to fetch');
  }
  return originalFetch(url, options);
};
get('connect').click();
await wait(() => !get('connect').disabled && get('notice').textContent.includes('reach Airlock'));
if (!get('connected').hidden) throw Error('A dropped status response was shown as connected.');
get('connect').click(); await wait(() => !get('connected').hidden);
window.fetch = originalFetch;
if (exchanges !== 1) throw Error('The iPhone retried a single-use pairing exchange.');
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
