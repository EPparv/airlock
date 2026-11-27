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
  // Use an in-memory clipboard for this disposable workspace. No provider or
  // operating-system clipboard is touched by either copy path.
  async function testClipboard() {
    await evaluate(`window.manusClipboard = {writes:0, value:'', denied:false};
      Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{
        async writeText(text) {
          if (manusClipboard.denied) throw new DOMException('Clipboard denied', 'NotAllowedError');
          manusClipboard.writes++; manusClipboard.value = text;
        }
      }})`);
  }
  async function verifyManusImport(area) {
    const label = 'Copy Manus configuration';
    const matches = `(() => {
      const token = document.querySelector(${JSON.stringify(area)}).querySelector('input[type=password]').value;
      const surfaces = [document.body.textContent, document.body.innerHTML, location.href,
        JSON.stringify(history.state), JSON.stringify(localStorage), JSON.stringify(sessionStorage),
        ...Array.from(document.querySelectorAll('input:not([type=password]),textarea'), e => e.value)];
      if (!/^pal_[A-Za-z0-9_-]{43}$/.test(token) || surfaces.some(text => text.includes(token))) {
        throw Error('The bearer token was missing or exposed outside its masked field');
      }
      return JSON.parse(manusClipboard.value.replaceAll(token, 'test-token'));
    })()`;
    const expected = {mcpServers:{Airlock:{type:'streamableHttp', url:'https://browser-check.example.org/mcp',
      headers:{Authorization:'Bearer test-token'}}}};
    assert.equal(await evaluate('manusClipboard.writes'), 0);
    await byText(area+' button', label);
    await until('manusClipboard.writes === 1');
    assert.deepEqual(await evaluate(matches), expected);
    await evaluate("manusClipboard.denied = true; manusClipboard.value = ''");
    await byText(area+' button', label);
    await until("document.activeElement?.labels?.[0]?.textContent.includes('Manual copy')");
    assert.equal(await evaluate(`(() => {
      const field = document.activeElement;
      if (!field.readOnly || field.value !== 'Airlock configuration') return false;
      const transfer = new DataTransfer();
      const copy = new ClipboardEvent('copy', {clipboardData:transfer, bubbles:true, cancelable:true});
      field.dispatchEvent(copy);
      manusClipboard.value = transfer.getData('text/plain');
      return copy.defaultPrevented;
    })()`), true);
    assert.deepEqual(await evaluate(matches), expected);
    await evaluate('delete navigator.clipboard; delete window.manusClipboard');
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
    if (vendor==='manus') await testClipboard();
    await choose(name); await contains('Connection details');
    const state = await evaluate("api('remote-state').then(s=>s.connections.filter(g=>g.active && g.vendor==="+JSON.stringify(vendor)+"))");
    assert.equal(state.length,1,name);
    assert.equal(state[0].last_call,null,name);
    assert.ok(!(await evaluate("JSON.stringify(history.state).includes('pal_') || location.href.includes('pal_')")));
    if (vendor==='chatgpt') await contains('Open tunnel setup');
    else {
      await contains(vendor==='ironclaw'?'Extension manifest':vendor==='muse'?'Schema URL':
        vendor==='manus'?'Copy Manus configuration':'Server URL');
      assert.equal(await evaluate("document.querySelector('.handoff-status')?.textContent"),'Finish setup');
      const signupUrl = hostedSignup.get(name);
      if (signupUrl) {
        if (vendor==='muse') await contains('Copy setup request');
        const before = await evaluate("api('remote-state')");
        await openHosted('Continue in ' + name, name, signupUrl);
        assert.deepEqual(await evaluate("api('remote-state')"), before);
        assert.ok(await evaluate("Boolean(document.querySelector('#app input[type=password]')?.value)"));
        assert.equal(await evaluate("document.querySelector('.handoff-status')?.textContent"), 'Finish setup');
        if (vendor==='manus') await verifyManusImport('#app');
      }
    }
  }
  await choose('Manus'); await contains('Connection details');
  assert.ok(!(await evaluate("Array.from(document.querySelectorAll('#app button')).some(b=>b.textContent==='Copy Manus configuration')")));
  await byText('summary','Connection details'); await contains('Test or recover connection');
  await btn('Test or recover connection'); await byText('summary','Connection help'); await contains('Lost the token?');
  await home(); await btn('Privacy & connections'); await btn('Cloud agents'); await btn('Manus');
  await btn('Add another connection'); await testClipboard();
  await btn('Create connection');
  await verifyManusImport('dialog[open]');
  await byText('dialog[open] button','Test this connection'); await contains('Waiting for a status call');
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
