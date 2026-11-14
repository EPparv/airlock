import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import zipfile

import pytest

from privacy_layer import updater as u


def manifest(data=b'zip'):
    return dict(schema=1, version='0.6.0-alpha.8', build=68, commit='a' * 40,
                archive=u.ARCHIVE, sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                minimum_macos='12.0.0', notes='A tested update.')


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, body, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            z.writestr(info, body)
    return out.getvalue()


def app(path, build=67):
    (path / 'Contents/Resources/payload').mkdir(parents=True)
    (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': u.APP_ID, 'CFBundleVersion': str(build)}))
    (path / 'Contents/Resources/payload/release.json').write_text(json.dumps({'version': f'0.6.0-alpha.{build-60}', 'build': build, 'commit': 'a'*40}))
    return path


@pytest.mark.parametrize('change', [
    {'archive': '../malicious.zip'}, {'archive': 'https://other.invalid/app.zip'}, {'size': True},
    {'size': u.MAX_ARCHIVE+1}, {'build': True}, {'build': 0}, {'commit': 'main'},
    {'sha256': 'z'*64}, {'schema': 2}, {'version': 'latest'}, {'minimum_macos': 'unknown'},
    {'notes': 'a'*2001}, {'extra': 'ignored field'},
])
def test_invalid_release_metadata(change):
    with pytest.raises(u.UpdateError):
        u.validate_manifest(manifest() | change)


def test_signature_required():
    with pytest.raises(Exception):
        u.verify_manifest(json.dumps(manifest()).encode(), b'{}')


@pytest.mark.parametrize('name,mode', [
    ('/Airlock/Airlock.app/Contents/escape', stat.S_IFREG),
    ('Airlock/Airlock.app/Contents/../../escape', stat.S_IFREG),
    ('Airlock/Airlock.app/Contents//escape', stat.S_IFREG),
    ('Airlock/Airlock.app/Contents/./escape', stat.S_IFREG),
    ('Airlock/Airlock.app/Contents/link', stat.S_IFLNK),
    ('Airlock/Airlock.app/Contents/pipe', stat.S_IFIFO),
    ('Airlock/Airlock.app/Contents/Resources/payload/.private/secrets', stat.S_IFREG),
    ('Airlock/Airlock.app/Contents/a\\b', stat.S_IFREG),
    ('Other.app/Contents/MacOS/Other', stat.S_IFREG),
])
def test_unsafe_archives_rejected(tmp_path, name, mode):
    data = archive([(name, b'unsafe', mode | 0o644)])
    with pytest.raises(u.UpdateError):
        u.extract_archive(data, manifest(data), tmp_path)
    assert not list(tmp_path.rglob('*'))


def test_digest_checked_before_extraction(tmp_path):
    data = archive([('Airlock/Airlock.app/Contents/data', b'test', 0o100644)])
    with pytest.raises(u.UpdateError, match='checksum'):
        u.extract_archive(data, manifest(data) | {'sha256': '0'*64}, tmp_path)
    assert not list(tmp_path.iterdir())


def test_duplicate_case_names_rejected(tmp_path):
    data = archive([(f'Airlock/Airlock.app/Contents/{n}', b'test', 0o100644) for n in ('file', 'FILE')])
    with pytest.raises(u.UpdateError):
        u.extract_archive(data, manifest(data), tmp_path)


def test_bounded_extraction(tmp_path, monkeypatch):
    data = archive([('Airlock/Airlock.app/Contents/large', b'x'*100, 0o100644)])
    monkeypatch.setattr(u, 'MAX_UNPACKED', 50)
    with pytest.raises(u.UpdateError, match='limit'):
        u.extract_archive(data, manifest(data), tmp_path)


def test_archive_permissions(tmp_path):
    data = archive([(f'Airlock/Airlock.app/Contents/{n}', b'test', 0o100777)
                    for n in ('MacOS/Airlock', 'Resources/bootstrap.sh', 'Resources/payload/ui.html')])
    root = u.extract_archive(data, manifest(data), tmp_path)
    assert stat.S_IMODE((root/'Contents/MacOS/Airlock').stat().st_mode) == 0o755
    assert stat.S_IMODE((root/'Contents/Resources/payload/ui.html').stat().st_mode) == 0o644


def test_app_identity_must_match(tmp_path, monkeypatch):
    root = app(tmp_path/'Airlock.app', build=68)
    calls = []
    monkeypatch.setattr(u.subprocess, 'run', lambda *a, **kw: calls.append(a))
    u.validate_app(root, manifest())
    assert calls[0][0][:2] == ['/usr/bin/codesign', '--verify']
    with pytest.raises(u.UpdateError, match='signed release'):
        u.validate_app(root, manifest() | {'commit': 'b'*40})
    (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'other', 'CFBundleVersion': '68'}))
    with pytest.raises(u.UpdateError):
        u.app_release(root)


def test_updater_never_installs_older_release(tmp_path, monkeypatch):
    root = app(tmp_path/'Airlock.app', u.BUILD)
    base = tmp_path/'support';base.mkdir()
    monkeypatch.setattr(u, 'latest', lambda: manifest() | {'build': u.BUILD-1})
    with pytest.raises(u.UpdateError, match='available version changed'):
        u.install(root, base, u.BUILD-1, os.getppid(), base/'status.json')
    assert u.app_release(root)['build'] == u.BUILD


def mock_swap(first, second):
    # Tests on Linux exercise the transaction; macOS tests exercise renamex_np.
    temp = first.with_name('swap-temp')
    first.rename(temp);second.rename(first);temp.rename(second)


@pytest.mark.parametrize('healthy', [True, False])
def test_update_recovery_preserves_vault_and_connections(tmp_path, monkeypatch, healthy):
    installed=app(tmp_path/'Airlock.app', 67);staged=app(tmp_path/'new.app', 68)
    base=tmp_path/'support';(base/'app/.private').mkdir(parents=True)
    vault=base/'app/.private/connections.enc';vault.write_bytes(b'ENCRYPTED_FIXTURE_CANARY')
    config=tmp_path/'config.toml';config.write_bytes(b'EXISTING_AI_CONNECTIONS')
    starts=[]
    monkeypatch.setattr(u, 'swap_apps', mock_swap)
    monkeypatch.setattr(u, 'launch_app', lambda *a, **kw: starts.append((u.app_release(a[0])['build'], kw)))
    monkeypatch.setattr(u, 'wait_ready', lambda *a: healthy)
    if healthy:
        u.replace_and_restart(installed, staged, base, manifest())
        assert u.app_release(installed)['build'] == 68
        assert u.app_release(staged)['build'] == 67
        assert json.loads((base/'previous-app.json').read_text())['path'] == str(staged)
    else:
        with pytest.raises(u.UpdateError, match='previous app was restored'):
            u.replace_and_restart(installed, staged, base, manifest())
        assert u.app_release(installed)['build'] == 67
        assert starts[-1] == (67, {'restored': True})
    assert vault.read_bytes() == b'ENCRYPTED_FIXTURE_CANARY'
    assert config.read_bytes() == b'EXISTING_AI_CONNECTIONS'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS atomic bundle exchange')
def test_real_atomic_swap(tmp_path):
    installed=app(tmp_path/'Airlock.app', 67);staged=app(tmp_path/'new.app', 68)
    u.swap_apps(installed, staged)
    assert u.app_release(installed)['build'] == 68
    assert u.app_release(staged)['build'] == 67
    u.swap_apps(installed, staged)
    assert u.app_release(installed)['build'] == 67


def test_update_urls_are_fixed():
    with pytest.raises(u.UpdateError):
        u.fetch('https://untrusted.invalid/app.zip', 100)


def test_newer_macos_is_not_installed(monkeypatch):
    import platform
    monkeypatch.setattr(platform, 'mac_ver', lambda: ('13.6', '', ''))
    assert u.compatible(manifest())
    assert not u.compatible(manifest() | {'minimum_macos': '14.0.0'})
