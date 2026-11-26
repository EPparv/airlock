"""Package the same workspace UI with a network-disabled, disposable example transport."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import tempfile

from privacy_layer.founder_demo import FounderDemo
from privacy_layer.safe_test import SafeTest
from privacy_layer.skills import SkillPackages
from privacy_layer.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]


def sample_data(directory):
    safe = SafeTest(ROOT, directory/'test', profile_home=directory/'fictional')
    work = Workspace(safe.g)
    work.seed()
    initial = work.state()
    view = next(row for row in initial['actions'] if row['kind'] == 'data')
    fields = work.try_example(view['id'], view['audience'][0], 'read_private_fields')
    fixture = safe.status()
    checks = {step:safe.check(step) for step in ('recall','privacy','correction','propose','approve','persistence','revoke')}
    demo = FounderDemo(safe.g)
    demo.reset()
    demo.grant()
    review = demo.review(['meeting-notes'], 'rehearsal')
    result = asyncio.run(demo.send(review['approval_id'], True, review['sha256']))
    return dict(initial=initial, fields=fields, fixture=fixture, checks=checks,
                walk=dict(records=demo.state()['records'],payload=review['payload'],result=result),
                builtin=SkillPackages(safe.g).builtin_preview())


def build(target):
    with tempfile.TemporaryDirectory() as folder:
        sample = json.dumps(sample_data(Path(folder)), separators=(',',':')).replace('<','\\u003c')
    ui = ROOT/'ui'
    html = (ui/'workspace.html').read_text()
    sources = re.findall(r'<script defer src="/([\w.-]+)"></script>',html)
    if not sources or sources[0]!='workspace.js':
        raise ValueError('Workspace entry point missing.')
    policy = """<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src data:; base-uri 'none'; form-action 'none'">"""
    html = html.replace('<link rel="icon" href="/icon.svg">',policy)
    html = html.replace('<link rel="stylesheet" href="/workspace.css">','<style>'+(ui/'workspace.css').read_text()+'</style>')
    html = re.sub(r'<script defer src="/[\w.-]+"></script>\n?', '', html)
    scripts = [(ROOT/'scripts/workspace_preview_adapter.js').read_text()] + [(ui/name).read_text() for name in sources]
    if any('</script' in script.lower() for script in scripts):
        raise ValueError('Unsafe inline script terminator.')
    html = html.replace('</body>', '<script type="application/json" id="example-data">'+sample+'</script>\n' +
                        '\n'.join('<script>'+script+'</script>' for script in scripts)+'\n</body>')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(html)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('target',type=Path)
    build(parser.parse_args().target)
