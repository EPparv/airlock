"""Make a standalone walkthrough using only the isolated fictional workspace."""
import argparse
import json
from pathlib import Path
import tempfile

from privacy_layer.safe_test import SafeTest
from privacy_layer.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]


def build(target):
    with tempfile.TemporaryDirectory() as directory:
        safe = SafeTest(ROOT,Path(directory)/'test',profile_home=Path(directory)/'fictional')
        workspace = Workspace(safe.g)
        workspace.seed()
        initial = workspace.state()
        email = next(a for a in initial['actions'] if a['kind']=='email')
        view = next(a for a in initial['actions'] if a['kind']=='data')
        data = workspace.try_example(view['id'],view['audience'][0],'read_private_fields')
        states = {}
        # Generate each outcome with the exact same gateway and identifiers.
        original = safe.g.store.path.read_bytes()
        for accept in (False,True):
            safe.g.store.path.write_bytes(original)
            status = workspace.decide(email['id'],email['fingerprint'],accept)['status']
            states[status] = {g:workspace.try_example(email['id'],g,'private_action_status') for g in email['audience']}
        sample = json.dumps(dict(initial=initial,states=states,fields=data),separators=(',',':')).replace('<','\\u003c')
    html = (ROOT/'ui/workspace.html').read_text()
    css = (ROOT/'ui/workspace.css').read_text()
    js = (ROOT/'ui/workspace.js').read_text()
    # This transport accepts only the example interactions. No credentials or network are available.
    adapter = """
const sample = JSON.parse(document.getElementById('example-data').textContent);
let current = structuredClone(sample.initial);
window.airlockExample = (operation, params) => {
  if (operation === 'workspace-state') return structuredClone(current);
  if (operation === 'test-reset') { current = structuredClone(sample.initial); return {}; }
  const row = current.actions.find(a => a.id === params.identifier);
  if (!row) throw new Error('This example action is unavailable.');
  if (operation === 'workspace-decide' && row.state === 'pending' && params.fingerprint === row.fingerprint) {
    row.state = params.approve ? 'sent' : 'declined';
    return {status: row.state};
  }
  if (operation === 'workspace-try' && row.audience.includes(params.agent)) {
    const result = row.kind === 'data' ? sample.fields : sample.states[row.state]?.[params.agent];
    if (!result) throw new Error('This example has no receipt yet.');
    current.receipts.unshift({at:Date.now()/1000,agent:params.agent,tool:params.tool,response:structuredClone(result)});
    return structuredClone(result);
  }
  throw new Error('This action is available in the Mac app.');
};
"""
    policy = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src data:; base-uri 'none'; form-action 'none'\">"
    html = html.replace('<link rel="icon" href="/icon.svg">',policy)
    html = html.replace('<link rel="stylesheet" href="/workspace.css"><script defer src="/workspace.js"></script>', '<style>'+css+'</style>')
    html = html.replace('</body>', '<script type="application/json" id="example-data">'+sample+'</script><script>'+adapter+'</script><script>'+js+'</script></body>')
    target = Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(html)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('target',type=Path)
    build(parser.parse_args().target)
