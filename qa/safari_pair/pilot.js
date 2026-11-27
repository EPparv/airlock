// Disposable simulator-only pilot. The shipping phone script owns all Airlock requests.
'use strict';
(async () => {
  const get = id => document.getElementById(id);
  const stages = new Set(['boot','connect','scoped_read','scope_isolation','pending_mac_approval','disconnect','done']);
  const notices = new Set(['none','missing_control','closed','offline','invalid_response','unavailable',
    'rate_limit','pending','empty','unexpected_view','timeout','query_result','private_field',
    'unexpected_record','storage','other']);
  let stage = 'boot';

  async function report(ok, notice = 'none') {
    if (!stages.has(stage) || !notices.has(notice)) return;
    const reply = await fetch('/qa/evidence', {
      method: 'POST', body: JSON.stringify({stage, ok, notice}),
      headers: {'Content-Type':'application/json'}, credentials:'omit', mode:'same-origin',
      referrerPolicy:'no-referrer', cache:'no-store', redirect:'error', signal:AbortSignal.timeout(4500)
    });
    if (!reply.ok) throw new Error('other');
  }
  function require(ok, code) { if (!ok) throw new Error(code); }
  function currentNotice(fallback) {
    const text = (get('notice')?.textContent || '').toLowerCase();
    if (/closed|pair again|new link/.test(text)) return 'closed';
    if (/couldn.t reach|timed out/.test(text)) return 'offline';
    if (/incomplete|didn.t return|did not return/.test(text)) return 'invalid_response';
    if (/unavailable|didn.t confirm/.test(text)) return 'unavailable';
    if (/too many requests/.test(text)) return 'rate_limit';
    if (/waiting for approval/.test(text)) return 'pending';
    if (/no matching|no actions assigned/.test(text)) return 'empty';
    return fallback;
  }
  async function wait(done) {
    const deadline = Date.now() + 19500;
    while (!done()) {
      if (Date.now() > deadline) throw new Error(currentNotice('timeout'));
      await new Promise(resolve => setTimeout(resolve, 80));
    }
  }
  async function search(term) {
    const form = get('search-form');
    const submit = form.querySelector('button');
    get('topic').value = term;
    form.requestSubmit();
    // The production handler empties its result list synchronously before the
    // first network await and reenables the submit button after rendering.
    require(submit.disabled, 'missing_control');
    await wait(() => !submit.disabled);
    require(get('records').children.length > 0, currentNotice('query_result'));
    return get('records').textContent || '';
  }

  try {
    require(['connect','connected','welcome','search-form','records','topic','refresh-actions',
      'actions','scope','notice','disconnect'].every(id => !!get(id)), 'missing_control');
    require(!location.hash && get('connect').onclick && !get('connect').hidden &&
       !get('welcome').hidden && get('connected').hidden, 'unexpected_view');
    await report(true);

    stage = 'connect';
    get('connect').click();
    await wait(() => !get('connect').disabled);
    require(!get('connected').hidden && get('scope').textContent.includes('1 shared record'), currentNotice('unexpected_view'));
    await report(true);

    stage = 'scoped_read';
    const found = await search('Cypress');
    require(found.includes('Thursday'), 'query_result');
    require(!found.includes('robin@example.test'), 'private_field');
    await report(true);

    stage = 'scope_isolation';
    const all = await search('');
    require(all.includes('Thursday') && get('records').children.length === 1 && get('more').hidden, 'unexpected_record');
    require(!/Vermilion|device-only stone/i.test(all), 'unexpected_record');
    require(!all.includes('robin@example.test'), 'private_field');
    await report(true);

    stage = 'pending_mac_approval';
    get('refresh-actions').click();
    await wait(() => !get('refresh-actions').disabled);
    const request = get('actions').querySelector('button');
    require(request && request.textContent === 'Request Mac approval' &&
      get('actions').textContent.includes('Review fictional follow-up'), currentNotice('missing_control'));
    request.click();
    await wait(() => get('actions').textContent.includes('pending') || !request.disabled);
    require(get('actions').textContent.includes('pending') &&
      get('notice').textContent.includes('Waiting for approval'), currentNotice('unexpected_view'));
    await report(true);

    stage = 'disconnect';
    get('disconnect').click();
    await wait(() => !get('disconnect').disabled);
    require(get('connected').hidden && get('notice').textContent === 'Disconnected.' &&
      !get('records').children.length && !get('actions').children.length && get('topic').value === '' &&
      get('scope').textContent === '' && get('connect').hidden, currentNotice('unexpected_view'));
    require(localStorage.length === 0 && sessionStorage.length === 0, 'storage');
    await report(true);

    stage = 'done';
    await report(true);
  } catch (error) {
    const code = notices.has(error.message) ? error.message : 'other';
    await report(false, code).catch(() => {});
  }
})();
