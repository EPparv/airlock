// Exercise the shipping picker. The service and its persistent store are real.
// The fixture substitutes the last macOS dispatch, checked separately on signed Macs.
const assert = require('node:assert/strict');

const local = new Map([
  ['Codex','codex'], ['Cursor','cursor'], ['Claude Desktop','claude-desktop'],
  ['Claude Code','claude-code'], ['VS Code · GitHub Copilot','vscode'],
  ['Muse Code','muse-code'], ['Gemini CLI','gemini-cli'], ['OpenClaw','openclaw']
]);
const cloud = new Map([
  ['ChatGPT','chatgpt'], ['Meta Muse','muse'], ['Manus','manus'],
  ['IronClaw','ironclaw'], ['Other remote MCP client','custom']
]);
const generic = 'Custom MCP client';
const choices = [...local.keys(), ...cloud.keys(), generic, 'Dot'];
const hostedSignup = new Map([
  ['Meta Muse', 'https://muse.ai/'],
  ['Manus', 'https://www.manus.im/app?openConnectors=true'],
]);

async function ownerChoices({home,btn,titled,contains,evaluate,until,launched,type,byText,freePort}) {
  async function choose(name) {
    await home(); await btn('Connect agent'); await btn(name);
    await titled(name === 'Dot' ? 'Dot tunnel' : name);
    await until("!document.querySelector('#app [aria-busy]')");
  }
  async function openHosted(label, name, url) {
    await btn(label);
    await contains('Open ' + name + ' in your browser');
    const links = await evaluate("Array.from(document.querySelectorAll('#app a')).filter(a=>a.textContent===" +
      JSON.stringify('Open ' + name + ' in your browser') + ").map(a=>a.href)");
    assert.deepEqual(links, [url]);
  }
  for (const [name,key] of local) {
    const before = launched().length;
    await choose(name);
    assert.deepEqual(launched().slice(before), [key]);
    assert.equal(await evaluate("document.querySelector('.handoff-status')?.textContent"), 'Waiting for '+name);
    await btn('Manage access');
    await contains('Save access');
    const grants = await evaluate("api('workspace-state').then(s=>s.agents.filter(g=>g.name==="+JSON.stringify(key)+"&&!['revoked','expired'].includes(g.status)))");
    assert.equal(grants.length, 1, name);
    if (!['codex','cursor'].includes(key)) assert.deepEqual(grants[0].scope.records, []);
    assert.equal(grants[0].last_call,null);
  }
  await choose(generic);
  await contains('Manual configuration');
  assert.ok((await evaluate("document.querySelector('#app pre')?.textContent"))?.includes('stdio'));
  await choose('Dot'); await contains('Restricted runtime key'); await contains('Connect Dot');
  const tunnelId = 'tunnel_ab12_' + 'c'.repeat(32);
  await type('Tunnel ID', tunnelId, '#app');
  assert.equal(await evaluate("document.querySelector('#app input').value"), tunnelId);
  assert.equal(await evaluate("document.querySelector('#app input').checkValidity()"), true);
  for (const name of [...cloud.keys()].filter(n=>n!=='ChatGPT')) {
    await choose(name); await contains('Start temporary link');
    const signupUrl = hostedSignup.get(name);
    if (signupUrl) {
      const state = await evaluate("api('remote-state')");
      assert.equal(state.enabled, false);
      await openHosted('Sign in or create an account', name, signupUrl);
      assert.deepEqual(await evaluate("api('remote-state')"), state);
    }
  }
  // Bring up a real loopback bridge in the fixture. External reachability has
  // its own independent HTTPS acceptance. No provider credentials are involved.
  await btn('Use my own domain'); await titled('HTTPS bridge');
  await byText('summary','Use my own domain');
  await type('Your HTTPS origin','https://browser-check.example.org','#app');
  await type('Local bridge port',String(await freePort()),'#app');
  await btn('Save and enable'); await titled('Other remote MCP client'); await contains('Bearer token');
  for (const [name,vendor] of cloud) {
    await choose(name); await contains('Connection details');
    const state = await evaluate("api('remote-state').then(s=>s.connections.filter(g=>g.active && g.vendor==="+JSON.stringify(vendor)+"))");
    assert.equal(state.length,1,name);
    assert.equal(state[0].last_call,null,name);
    assert.ok(!(await evaluate("JSON.stringify(history.state).includes('pal_') || location.href.includes('pal_')")));
    if (vendor==='chatgpt') await contains('Open tunnel setup');
    else {
      await contains(vendor==='ironclaw'?'Extension manifest':vendor==='muse'?'Schema URL':'Server URL');
      assert.equal(await evaluate("document.querySelector('.handoff-status')?.textContent"),'Finish setup');
      const signupUrl = hostedSignup.get(name);
      if (signupUrl) {
        if (vendor==='muse') await contains('Copy setup request');
        const before = await evaluate("api('remote-state')");
        await openHosted('Continue in ' + name, name, signupUrl);
        assert.deepEqual(await evaluate("api('remote-state')"), before);
        assert.ok(await evaluate("Boolean(document.querySelector('#app input[type=password]')?.value)"));
        assert.equal(await evaluate("document.querySelector('.handoff-status')?.textContent"), 'Finish setup');
      }
    }
  }
}

async function offlineChoices({home,btn,titled,contains,evaluate,until}) {
  for (const name of choices) {
    await home(); await btn('Connect agent'); await btn('Try sample agents'); await btn(name);
    await titled(name);
    await until("!document.querySelector('#app [aria-busy]')");
    const isCloud = cloud.has(name) && name!=='IronClaw';
    if (isCloud) await contains('Open Airlock on your Mac');
    else if (name==='Dot') await contains('Set up Dot');
    else await contains('Shared records');
    assert.ok(!(await evaluate("!!document.querySelector('dialog[open], #app .handoff-status')")));
  }
  assert.ok(!(await evaluate("performance.getEntriesByType('resource').some(r=>/^https?:/.test(r.name))")));
}

module.exports = { ownerChoices, offlineChoices, choices };
