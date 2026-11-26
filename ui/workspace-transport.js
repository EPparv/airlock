'use strict';

function localWorkspaceOrigin() {
  const url = new URL(location.href);
  return url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname) &&
    !!url.port && !url.username && !url.password;
}

function localSessionToken(key) {
  return localWorkspaceOrigin() ? location.hash.slice(1) || sessionStorage.getItem(key) || '' : '';
}

function personalSessionHash(raw) {
  let url;
  try { url = new URL(raw); } catch {}
  if (!url || !localWorkspaceOrigin() || url.protocol !== 'http:' || !['127.0.0.1','localhost'].includes(url.hostname) ||
      url.port !== location.port || url.username || url.password || url.search || !url.hash.slice(1) ||
      !['/personal','/workspace/personal'].includes(url.pathname)) {
    throw new WorkspaceConnectionError('response', 'open-personal', 'Airlock did not return a fresh local workspace. Open Airlock again on your Mac.');
  }
  return url.hash;
}

class WorkspaceConnectionError extends Error {
  constructor(kind, action, message) {
    super(message);
    this.kind = kind;
    this.action = action;
  }
}

function validWorkspaceReply(action, body, data) {
  if (!data || typeof data !== 'object') return false;
  switch (action) {
    case 'workspace-launch-options':
      return Array.isArray(data.agents) && data.agents.every(agent => typeof agent === 'string');
    case 'workspace-quick-connect':
    case 'workspace-open-client':
      return data.agent === body.agent && typeof data.opened === 'boolean' && typeof data.method === 'string' &&
        typeof data.message === 'string' && typeof data.id === 'string' && (!data.opened || !!data.id);
    case 'remote-connect':
      return ['bridge','choose'].includes(data.state) || (['created','existing'].includes(data.state) &&
        typeof data.id === 'string' && !!data.id && typeof data.handoff?.opened === 'boolean');
    case 'client-status':
      return typeof data.status === 'string';
    case 'open-personal':
      return typeof data.url === 'string';
    default:
      return true;
  }
}

async function workspaceRequest(action, body, token) {
  if (!localWorkspaceOrigin()) {
    throw new WorkspaceConnectionError('origin', action, 'Open Airlock on your Mac to use the live workspace.');
  }
  if (!token) throw new WorkspaceConnectionError('session', action, 'This tab has no active workspace key. Reopen Airlock from the Dock.');
  // Read-only status checks can time out. A lost reply to a mutation must never replay it.
  const controller = new AbortController();
  const timer = ['workspace-launch-options','client-status'].includes(action) ? setTimeout(() => controller.abort(), 10000) : null;
  let response, data;
  try {
    response = await fetch('/api/' + action, {
      method:'POST', mode:'same-origin', credentials:'omit', redirect:'error', cache:'no-store',
      headers:{Authorization:'Bearer ' + token, 'Content-Type':'application/json'},
      body:JSON.stringify(body), signal:controller.signal
    });
    if (response.status === 401) throw new WorkspaceConnectionError('session', action,
      'Airlock no longer accepts this tab’s workspace key. Reopen Airlock from the Dock.');
    if (response.status === 404) throw new WorkspaceConnectionError('version', action,
      'The running service does not have this feature. Open the latest version of Airlock on your Mac.');
    try {
      data = await response.json();
    } catch (error) {
      if (error instanceof SyntaxError || error.name === 'SyntaxError') {
        if (response.status === 403) throw new WorkspaceConnectionError('origin', action,
          'This workspace address was rejected. Reopen the workspace from Airlock on your Mac.');
        throw new WorkspaceConnectionError('response', action,
          'This address returned an unreadable reply (HTTP ' + response.status + '). Open the workspace from Airlock on your Mac.');
      }
      throw error;
    }
  } catch (error) {
    if (error instanceof WorkspaceConnectionError) throw error;
    throw new WorkspaceConnectionError('offline', action,
      'This tab lost contact with Airlock on your Mac. Reopen Airlock from the Dock if it quit or restarted.');
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
  if (!response.ok) throw Error(data?.error || 'Airlock could not complete the request (HTTP ' + response.status + ').');
  if (!validWorkspaceReply(action, body, data)) throw new WorkspaceConnectionError('response', action,
    'This address returned an unexpected reply. Open the workspace from Airlock on your Mac.');
  return data;
}
