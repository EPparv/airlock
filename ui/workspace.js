'use strict';
const $ = id => document.getElementById(id);
const preview = typeof window.airlockExample === 'function';
const personal = !preview && location.pathname.endsWith('/personal');
const tokenKey = personal ? 'private-ai-owner' : 'airlock-test-owner';
const owner = preview ? '' : location.hash.slice(1) || sessionStorage.getItem(tokenKey) || '';
if (owner) sessionStorage.setItem(tokenKey, owner);
if (!preview && location.hash) history.replaceState(history.state, '', location.pathname + location.search);
const names = {
  'claude-desktop': 'Claude Desktop',
  'claude-code': 'Claude Code',
  codex: 'Codex',
  cursor: 'Cursor',
  mcp: 'Custom MCP client',
  dot: 'Dot',
  ironclaw: 'IronClaw'
};
const pages = {};
let page = 'home',
  params = {},
  sequence = 0,
  toastTimer = 0;

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function put(parent, ...children) {
  parent.append(...children);
  return parent;
}

function input(type = 'text', value = '') {
  const node = el('input');
  node.type = type;
  node.value = value;
  return node;
}

function select(options, value) {
  const s = el('select');
  for (const [key, label] of options) {
    const o = el('option', label);
    o.value = key;
    s.append(o);
  }
  if (value !== undefined) s.value = value;
  return s;
}

function field(parent, label, node) {
  const l = el('label', label, 'field');
  put(parent, put(l, node));
  return node;
}

function check(parent, label, checked = false) {
  const cb = input('checkbox');
  cb.checked = Boolean(checked);
  put(parent, put(el('label', null, 'check'), cb, el('span', label)));
  return cb;
}

function group(parent, title) {
  const g = el('fieldset');
  put(parent, put(g, el('legend', title)));
  return g;
}

function note(parent, msg) {
  parent.append(el('p', msg, 'hint'));
}

function empty(parent, msg) {
  parent.append(el('p', msg, 'empty'));
}

function section(parent, title) {
  parent.append(el('h2', title, 'section'));
  const area = el('div', null, 'list');
  parent.append(area);
  return area;
}

function facts(pairs) {
  const dl = el('dl', null, 'facts');
  for (const [k, v] of pairs) put(dl, el('dt', k), el('dd', String(v ?? '')));
  return dl;
}

function details(parent, title, body, open = false) {
  const d = el('details', null, 'details');
  d.open = open;
  const content = el('div');
  put(d, el('summary', title), content);
  parent.append(d);
  if (typeof body === 'function') body(content);
  else if (body) content.append(body);
  return content;
}

function flash(message) {
  clearTimeout(toastTimer);
  const n = $('notice');
  n.hidden = !message;
  n.textContent = message;
  if (message) toastTimer = setTimeout(() => {
    n.hidden = true;
  }, 6500);
}

function errorAt(message) {
  if ($('dialog').open) {
    $('dialog-error').textContent = message;
    $('dialog-error').hidden = false;
  } else flash(message);
}

function run(fn) {
  const handler = async event => {
    const b = event?.currentTarget;
    if (b?.dataset.busy) return;
    const disabled = b?.disabled;
    if (b) {
      b.dataset.busy = '1';
      b.disabled = true;
    }
    try {
      if ($('dialog').open) $('dialog-error').hidden = true;
      await fn(event);
    } catch (e) {
      errorAt(e.message || 'The change could not be saved.');
    } finally {
      if (b) {
        delete b.dataset.busy;
        if (b.isConnected) b.disabled = disabled;
      }
    }
  };
  handler.guarded = true;
  return handler;
}

function button(label, fn, cls = 'secondary') {
  const b = el('button', label, cls);
  b.type = 'button';
  b.addEventListener('click', fn.guarded ? fn : run(fn));
  return b;
}

function row(parent, label, fn, tail = '', icon = '') {
  const b = button('', fn, 'menu-row');
  if (icon) {
    const i = el('span', null, 'home-icon icon-' + icon);
    i.setAttribute('aria-hidden', 'true');
    b.append(i);
  }
  b.append(el('span', label));
  if (tail) b.append(el('span', tail, 'count'));
  const arrow = el('span', null, 'chevron');
  arrow.setAttribute('aria-hidden', 'true');
  b.append(arrow);
  parent.append(b);
  return b;
}

function item(parent, title, subtitle, fn) {
  const copy = el('span', null, 'item-copy');
  copy.append(el('span', title, 'item-title'));
  if (subtitle) copy.append(el('span', subtitle, 'row-sub'));
  const node = fn ? button('', fn, 'item-button') : el('div', null, 'entry');
  node.append(copy);
  if (fn) node.append(el('span', null, 'chevron'));
  parent.append(node);
  return node;
}

function modal(title) {
  const d = $('dialog');
  $('dialog-title').textContent = title;
  $('dialog-error').hidden = true;
  const f = el('div', null, 'form');
  $('dialog-content').replaceChildren(f);
  if (!d.open) {
    if (d.showModal) d.showModal();
    else d.setAttribute('open', '');
  }
  return f;
}

function close() {
  const d = $('dialog');
  if (d.open) {
    if (d.close) d.close();
    else d.removeAttribute('open');
  }
}
$('close').onclick = close;

function confirmAction(title, detail, label, fn, danger = false) {
  const f = modal(title);
  if (detail) note(f, detail);
  f.append(button(label, async () => {
    await fn();
    if (f.isConnected) close();
  }, danger ? 'danger' : 'primary'));
}

function formAction(form, label, fn) {
  const b = button(label, fn, 'primary');
  form.append(b);
  return b;
}

function nativeOnly(feature) {
  const f = modal(feature);
  note(f, 'Open the Mac app to use this with your device.');
  f.append(button('Close', close));
}
async function api(action, body = {}, override) {
  if (preview) return window.airlockExample(action, body);
  const token = override ?? owner;
  if (!token) throw Error('Open Airlock.app to reconnect.');
  const r = await fetch('/api/' + action, {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + token,
      'Content-Type': 'application/json'
    },
    cache: 'no-store',
    body: JSON.stringify(body)
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(data.error || (r.status === 401 ? 'Access has closed. Reopen Airlock.' :
    'Airlock could not complete this request.'));
  return data;
}

function testToken() {
  return preview ? '' : sessionStorage.getItem('airlock-test-owner') || (!personal ? owner : '');
}

function testAPI(action, body = {}) {
  return api(action, body, testToken());
}
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    flash('Copied.');
  } catch {
    const f = modal('Copy text');
    const box = field(f, 'Text', el('textarea'));
    box.value = text;
    box.readOnly = true;
    box.select();
  }
}
async function upload(file, limit = 4 * 1024 * 1024) {
  if (!file || file.size > limit) throw Error('Choose a file up to ' + Math.round(limit / 1024 / 1024) + ' MB.');
  return new Promise((ok, no) => {
    const r = new FileReader();
    r.onload = () => ok({
      name: file.name,
      data: r.result.split(',')[1]
    });
    r.onerror = () => no(Error('This file could not be read.'));
    r.readAsDataURL(file);
  });
}
const when = t => t ? new Date(t * 1000).toLocaleString(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit'
}) : '';
const agentName = (id, ws) => names[ws?.agents.find(a => a.id === id)?.name] || names[id] || 'Agent';
const active = g => !['expired', 'revoked'].includes(g.status);

function addPage(key, title, parent, draw, requiresPersonal = true) {
  pages[key] = {
    title,
    parent,
    draw,
    requiresPersonal
  };
}

function unlock(target, options = {}) {
  const f = modal('Unlock your workspace');
  note(f, 'This opens your local library and resumes the connections you previously approved.');
  formAction(f, 'Unlock workspace', async () => {
    const result = await testAPI('open-personal', {
      approved: true
    });
    sessionStorage.setItem('airlock-next-view', JSON.stringify({
      target,
      options
    }));
    location.replace('/workspace/personal' + new URL(result.url).hash);
  });
}

function go(key, options = {}, push = true) {
  if (!pages[key]) key = 'home';
  if (pages[key].requiresPersonal && !preview && !personal) {
    unlock(key, options);
    return;
  }
  close();
  page = key;
  params = options;
  flash('');
  if (push && !preview) {
    const dest = location.pathname + (key === 'home' ? '' : '?view=' + encodeURIComponent(key));
    history.pushState({
      view: key,
      options
    }, '', dest);
  } else if (push && preview) {
    try {
      history.pushState({
        view: key,
        options
      }, '');
    } catch {}
  }
  return render();
}

function refresh() {
  return render(false);
}

function head(host, title, parent) {
  host.append(button(parent === 'home' ? 'Airlock' : pages[parent].title, () => go(parent), 'back'));
  const bar = el('div', null, 'page-head');
  const h = el('h1', title);
  h.tabIndex = -1;
  put(host, put(bar, h));
  return bar;
}
async function render(navigated = true) {
  const id = ++sequence,
    key = page,
    targetParams = {
      ...params
    },
    cfg = pages[key],
    root = $('app');
  root.className = key === 'home' ? 'home' : '';
  const shell = el('div', null, key === 'home' ? 'home-inner' : 'page');
  const bar = key === 'home' ? null : head(shell, cfg.title, cfg.parent);
  const body = el('div');
  shell.append(body);
  root.replaceChildren(shell);
  if (navigated) {
    window.scrollTo(0, 0);
    if (key !== 'home') shell.querySelector('h1')?.focus({
      preventScroll: true
    });
  }
  document.title = key === 'home' ? 'Airlock' : cfg.title + ' · Airlock';
  body.setAttribute('aria-busy', 'true');
  try {
    await cfg.draw(body, targetParams, bar);
  } catch (e) {
    if (id === sequence) {
      empty(body, e.message);
      body.append(button('Try again', refresh));
    }
  } finally {
    body.removeAttribute('aria-busy');
  }
}

function choose(host, label, key, tail) {
  return row(host, label, () => go(key), tail);
}
addPage('home', 'Airlock', null, host => {
  const brand = el('div', null, 'home-brand'),
    mark = el('span', null, 'brand-symbol');
  mark.setAttribute('aria-hidden', 'true');
  put(host, put(brand, mark, el('h1', 'Airlock')));
  const menu = el('nav', null, 'home-menu');
  menu.setAttribute('aria-label', 'Airlock');
  host.append(menu);
  row(menu, 'Connect agent', () => go('connect'), '', 'connect');
  row(menu, 'Context & memory', () => go('context'), '', 'context');
  row(menu, 'Privacy & connections', () => go('privacy'), '', 'privacy');
  if (preview) host.append(el('p', 'Interactive preview', 'preview-note'));
}, false);

function lockWorkspace() {
  confirmAction('Lock workspace?', 'New personal requests will be blocked until you unlock Airlock.',
    'Lock workspace', async () => {
      await testAPI('close-personal');
      if (preview) {
        go('home');
        flash('Preview workspace locked.');
        return;
      }
      sessionStorage.removeItem('private-ai-owner');
      sessionStorage.removeItem('airlock-next-view');
      location.replace('/workspace');
    });
}
document.addEventListener('DOMContentLoaded', () => {
  let key = 'home',
    data = {};
  if (!preview) {
    const intent = personal && sessionStorage.getItem('airlock-next-view');
    if (intent) {
      sessionStorage.removeItem('airlock-next-view');
      try {
        const v = JSON.parse(intent);
        key = v.target;
        data = v.options || {};
      } catch {}
    } else {
      key = new URLSearchParams(location.search).get('view') || 'home';
      data = history.state?.options || {};
    }
    if (!pages[key] || (!personal && pages[key].requiresPersonal)) key = 'home';
    history.replaceState({
      view: key,
      options: data
    }, '', location.pathname + (key === 'home' ? '' : '?view=' + encodeURIComponent(key)));
  }
  go(key, data, false);
});
window.addEventListener('popstate', e => {
  go(e.state?.view || 'home', e.state?.options || {}, false);
});
