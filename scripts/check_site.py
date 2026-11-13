"""Check the built public download and its linked local assets."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import json
import sys
import zipfile
from build_site import ROOT, sources

out = ROOT / 'dist'
meta = json.loads((out / 'release.json').read_text())
archive = out / meta['archive']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == meta['sha256']
assert '{{' not in (out / 'index.html').read_text()
with zipfile.ZipFile(archive) as z:
    expected = {'Airlock/' + p.relative_to(ROOT).as_posix() for p in sources()}
    assert set(z.namelist()) == expected, 'Unexpected archive content'
    assert z.testzip() is None
    assert z.getinfo('Airlock/Run-Airlock.command').external_attr >> 16 & 0o111
    for name in z.namelist():
        assert z.read(name) == (ROOT / name.removeprefix('Airlock/')).read_bytes()

class Links(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('href', 'src') and value:
                link = urlsplit(value)
                if not link.scheme and not link.netloc and link.path:
                    assert not link.path.startswith('/'), 'Use relative links for subpath hosting'
                    assert (out / link.path).resolve().is_relative_to(out.resolve())
                    assert (out / link.path).is_file(), f'Missing asset: {value}'

Links().feed((out / 'index.html').read_text())
if meta.get('mac'):
    mac=out/meta['mac']['archive']
    assert hashlib.sha256(mac.read_bytes()).hexdigest()==meta['mac']['sha256']
    with zipfile.ZipFile(mac) as z:
        assert z.testzip() is None
        prefix='Airlock/Airlock.app/Contents/'
        assert z.getinfo(prefix+'MacOS/Airlock').external_attr>>16 & 0o111
        assert json.loads(z.read(prefix+'Resources/payload/release.json'))['version']==meta['version']
        sys.path.insert(0,str(ROOT))
        from macos.package import entries
        expected_payload=entries()
        payload=prefix+'Resources/payload/'
        assert {n.removeprefix(payload) for n in z.namelist() if n.startswith(payload)}==set(expected_payload)
        for name,data in expected_payload.items():
            assert z.read(payload+name)==data,f'Mac payload differs from source: {name}'
print(f'Validated website links, checksum and {len(expected)} source files.')
