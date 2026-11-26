'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const code = fs.readFileSync(path.join(__dirname, '../ui/workspace-transport.js'), 'utf8');
const local = 'http://127.0.0.1:12345/workspace/personal';
function transport(address, fetch, remembered = 'test-key') {
  return vm.runInNewContext(code + '\n({request:workspaceRequest, token:localSessionToken, hash:personalSessionHash})', {
    location:new URL(address), URL, fetch, AbortController, setTimeout, clearTimeout,
    sessionStorage:{getItem() { return remembered; }}
  });
}
const hasKind = kind => error => error.kind === kind;

test('both supported owner origins send only same-origin requests', async () => {
  for (const host of ['127.0.0.1', 'localhost']) {
    const requests = [];
    const page = transport(local.replace('127.0.0.1', host), async (url, options) => {
      requests.push({url, options});
      return Response.json({agents:['codex']});
    });
    const result = await page.request('workspace-launch-options', {}, page.token('key'));
    assert.deepEqual(result.agents, ['codex']);
    assert.equal(requests.length, 1);
    const {url, options} = requests[0];
    assert.equal(url, '/api/workspace-launch-options');
    assert.equal(options.mode, 'same-origin');
    assert.equal(options.referrerPolicy, 'origin');
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, 'Bearer test-key');
    assert.equal(options.credentials, 'omit');
  }
});

test('a public page, file, or lookalike hostname cannot access the owner API', async () => {
  for (const address of ['file:///airlock.html', 'https://example.com/workspace','http://localhost.example:12345/workspace','http://owner@127.0.0.1:12345/workspace']) {
    let calls = 0;
    const page = transport(address + '#example', () => { calls++; });
    assert.equal(page.token('key'), '');
    await assert.rejects(page.request('workspace-quick-connect', {}, 'example'), hasKind('origin'));
    assert.equal(calls, 0);
  }
});

test('missing or expired credentials and version mismatches have distinct recoveries', async () => {
  let calls = 0;
  const page = transport(local, async () => { calls++; return new Response(null, {status:401}); });
  await assert.rejects(page.request('workspace-quick-connect', {}, ''), hasKind('session'));
  assert.equal(calls, 0);
  await assert.rejects(page.request('workspace-quick-connect', {}, 'old'), hasKind('session'));
  assert.equal(calls, 1);
  const outdated = transport(local, async () => new Response(null, {status:404}));
  await assert.rejects(outdated.request('workspace-launch-options', {}, 'key'), hasKind('version'));
});

test('dropped write replies are never replayed, invalid HTML never means success', async () => {
  let writes = 0;
  const page = transport(local, async () => { writes++; throw TypeError('Failed to fetch'); });
  await assert.rejects(page.request('workspace-quick-connect', {agent:'cursor', approved:true}, 'key'), error =>
    error.kind === 'offline' && error.action === 'workspace-quick-connect' && !error.message.includes('Failed to fetch'));
  assert.equal(writes, 1);
  const portal = transport(local, async () => new Response('<!doctype html>', {status:200}));
  await assert.rejects(portal.request('workspace-quick-connect', {}, 'key'), hasKind('response'));
  for (const data of [[], {}, {agents:'codex'}, {agents:[{}]}]) {
    const invalid = transport(local, async () => Response.json(data));
    await assert.rejects(invalid.request('workspace-launch-options', {}, 'key'), hasKind('response'));
  }
  const denied = transport(local, async () => Response.json({error:'Choose a saved connection.'}, {status:400}));
  await assert.rejects(denied.request('workspace-open-client', {}, 'key'), /Choose a saved connection/);
});

test('unlock follows only the current owner port and the explicit personal route', () => {
  const page = transport(local.replace('127.0.0.1','localhost'), () => {});
  assert.equal(page.hash('http://127.0.0.1:12345/personal#fresh'), '#fresh');
  for (const address of ['http://127.0.0.1:12346/personal#fresh','https://other.test/personal#fresh',
    'http://127.0.0.1:12345/other#fresh','http://127.0.0.1:12345/personal', 'garbage']) {
    assert.throws(() => page.hash(address), hasKind('response'));
  }
});
