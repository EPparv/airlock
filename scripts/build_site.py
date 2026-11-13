"""Build public assets from an explicit source allowlist. No app state is read."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.6.0-alpha.3'
ARCHIVE = 'Airlock_Source_Latest.zip'
MAC_ARCHIVE = 'Airlock_Mac_Latest.zip'
SOURCE_DIRS = ('privacy_layer', 'ui', 'builtin', 'integrations', 'tests', 'macos', 'scripts', 'web', '.github', 'docs', 'vendor/private_ai')
SOURCE_FILES = ('README.md', 'PUBLISHING.md', 'SHARED_MEMORY.md', 'LICENSE', 'pyproject.toml',
                'requirements.lock', 'requirements-near.txt', 'Run-Airlock.command',
                'Run-NEAR-Demo.command', '.gitignore', 'netlify.toml', 'vendor/README.md')
ALLOWED_SUFFIXES = {'.py', '.js', '.cjs', '.mjs', '.html', '.css', '.svg', '.md', '.toml',
                    '.example', '.lock', '.swift', '.m', '.sh', '.yml', '.yaml', '.patch'}
IGNORED_PARTS = {'__pycache__', '.pytest_cache', 'node_modules', '.venv', '.private', '.agent-demo', '.near-demo', '.git'}

def sources():
    paths = [ROOT / name for name in SOURCE_FILES]
    for name in SOURCE_DIRS:
        paths.extend(p for p in (ROOT / name).rglob('*')
                     if p.is_file() and not IGNORED_PARTS.intersection(p.relative_to(ROOT).parts)
                     and p.suffix in ALLOWED_SUFFIXES)
    for p in sorted(set(paths)):
        if p.is_symlink() or not p.is_file():
            raise ValueError(f'Unsafe or missing release input: {p.relative_to(ROOT)}')
        yield p

def build(mac_archive=None):
    selected = list(sources())
    fingerprint = hashlib.sha256()
    for p in selected:
        fingerprint.update(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes() + b'\0')
    source_hash = fingerprint.hexdigest()
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, True
    out = ROOT / 'dist'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    for p in (ROOT / 'web').iterdir():
        if not p.is_file() or p.is_symlink():
            raise ValueError('Web assets must be regular files')
        shutil.copy2(p, out / p.name)
    with zipfile.ZipFile(out / ARCHIVE, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in selected:
            rel = p.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo('Airlock/' + rel, date_time=(2026, 11, 12, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if rel.endswith(('.command', '.sh')) else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    archive_hash = hashlib.sha256((out / ARCHIVE).read_bytes()).hexdigest()
    metadata = dict(version=VERSION, kind='source-preview', commit=commit, dirty=dirty,
                    source_sha256=source_hash, archive=ARCHIVE, sha256=archive_hash,
                    python='>=3.12', hosted_runtime='static-download-page', vault='local-only')
    (out / 'release.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(f'{archive_hash}  {ARCHIVE}\n')
    if mac_archive:
        mac_archive=Path(mac_archive).resolve()
        with zipfile.ZipFile(mac_archive) as package:
            release=json.loads(package.read('Airlock/Airlock.app/Contents/Resources/payload/release.json'))
            if release.get('version') != VERSION:
                raise ValueError('Mac and source versions must match')
        shutil.copy2(mac_archive,out/MAC_ARCHIVE)
        mac_hash=hashlib.sha256((out/MAC_ARCHIVE).read_bytes()).hexdigest()
        metadata.update(kind='mac-app-and-source',mac=dict(archive=MAC_ARCHIVE,sha256=mac_hash,notarized=False,runtime='installed-automatically-on-first-open'))
        (out/'release.json').write_text(json.dumps(metadata,indent=2)+'\n')
        with (out/'SHA256SUMS').open('a') as sums:sums.write(f'{mac_hash}  {MAC_ARCHIVE}\n')
    page = out / 'index.html'
    page.write_text(page.read_text().replace('{{VERSION}}', html.escape(VERSION))
                    .replace('{{REVISION}}', html.escape((commit[:8] if commit else source_hash[:8]) + (' (local)' if dirty else '')))
                    .replace('{{MAC_DOWNLOAD}}',MAC_ARCHIVE if mac_archive else 'https://epparv.github.io/airlock/'+MAC_ARCHIVE))
    print(json.dumps(metadata))

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mac-archive',type=Path);args=parser.parse_args();build(args.mac_archive)
