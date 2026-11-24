"""Temporary, owner-started Cloudflare transport for the agent-only listener."""
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

# Asset SHA-256 from github.com/cloudflare/cloudflared/releases/tag/2026.11.2.
VERSION = '2026.11.2'
PACKAGES = {
    'arm64': ('arm64', '111085fc547a158401376582c342da9f1abd80e7e9eebe76770e1b9ed1f69a03'),
    'x86_64': ('amd64', 'ff0b005a556b5d3f8c247677bb5486bb5689888a2dd8da71815654462716df4a'),
}
QUICK_ORIGIN = re.compile(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com')
BANNER = re.compile(r'\|\s*(https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com)\s*\|')
MAX_PACKAGE = 32 * 1024 * 1024


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_helper(cache, work, cancelled):
    """Verify the exact package and unpack one executable without running installer scripts."""
    import httpx
    from .core import Denied
    if sys.platform != 'darwin' or platform.machine() not in PACKAGES:
        raise Denied('Open the Mac app to start a temporary HTTPS link.')
    arch, digest = PACKAGES[platform.machine()]
    cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    name = f'cloudflared-{arch}.pkg'
    target = cache / f'{VERSION}-{name}'
    if not (target.is_file() and not target.is_symlink() and target.stat().st_size <= MAX_PACKAGE and file_hash(target) == digest):
        download = work / 'download.pkg'
        url = f'https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/{name}'
        deadline = time.monotonic() + 90
        with httpx.Client(follow_redirects=True, trust_env=False, timeout=12) as client:
            with client.stream('GET', url) as response, download.open('xb') as out:
                response.raise_for_status()
                for chunk in response.iter_bytes(131072):
                    if cancelled.is_set() or time.monotonic() > deadline:
                        raise Denied('Link setup stopped. Try again when the workspace is open.')
                    if out.tell() + len(chunk) > MAX_PACKAGE:
                        raise Denied('Cloudflare returned an unexpected helper download.')
                    out.write(chunk)
        if file_hash(download) != digest:
            raise Denied('The Cloudflare download failed its integrity check. Update Airlock or use your own domain.')
        # Work and cache live on the same filesystem.
        os.replace(download, target)
    if cancelled.is_set():
        raise Denied('Link setup stopped.')
    expanded = work / 'package'
    subprocess.run(['/usr/sbin/pkgutil', '--expand-full', str(target), str(expanded)],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=35, check=True)
    files = [p for p in expanded.rglob('cloudflared') if not p.is_symlink() and p.is_file()]
    if len(files) != 1:
        raise Denied('The verified Cloudflare package did not contain the expected executable.')
    binary = work / 'cloudflared'
    shutil.copyfile(files[0], binary)
    binary.chmod(0o700)
    shutil.rmtree(expanded)
    return binary


def supervise(binary, port):
    """Stop the child on pipe EOF, including when the owning Airlock process dies."""
    process = subprocess.Popen([str(binary), 'tunnel', '--no-autoupdate', '--metrics', '127.0.0.1:0',
                                '--url', f'http://127.0.0.1:{port}'],
                               stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        while process.poll() is None and not stop.is_set():
            if select.select([sys.stdin], [], [], 0.4)[0] and not os.read(sys.stdin.fileno(), 1):
                break
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return process.returncode


def launch_guard(binary, port, work):
    return subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), str(binary), str(port)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=work, env={'HOME':str(work), 'PATH':'/usr/bin:/bin', 'TMPDIR':str(work)},
                            start_new_session=True)


def verify_route(origin, cancelled):
    """Require the public HTTPS URL to return this bridge's scoped API schema."""
    import httpx
    from .core import Denied
    if not QUICK_ORIGIN.fullmatch(origin):
        raise Denied('The temporary link format was invalid.')
    with httpx.Client(trust_env=False, timeout=3, follow_redirects=False) as client:
        for _ in range(12):
            if cancelled.is_set():
                break
            try:
                with client.stream('GET', origin + '/openapi.json') as response:
                    if response.status_code == 200:
                        buf = bytearray()
                        for chunk in response.iter_bytes(8192):
                            if len(buf) + len(chunk) > 131072:
                                break
                            buf.extend(chunk)
                        else:
                            spec = json.loads(buf)
                            if (isinstance(spec, dict) and spec.get('servers') == [{'url':origin}]
                                and '/v1/privacy_status' in spec.get('paths', {})):
                                return
            except (httpx.HTTPError, ValueError, TypeError):
                pass
            if cancelled.wait(0.6):
                break
    raise Denied('Cloudflare could not reach this Airlock workspace. Check your internet connection and try again.')


class QuickTunnel:
    def __init__(self, cache, *, prepare=prepare_helper, launch=launch_guard, timeout=25):
        self.cache, self.prepare, self.launch, self.timeout = Path(cache), prepare, launch, timeout
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.process = None

    def start(self, port, on_exit):
        from .core import Denied
        self.cache.mkdir(parents=True, mode=0o700, exist_ok=True)
        work = tempfile.TemporaryDirectory(prefix='session-', dir=self.cache)
        process = None
        try:
            binary = self.prepare(self.cache, Path(work.name), self.cancel)
            with self.lock:
                if self.cancel.is_set():
                    raise Denied('Link setup stopped.')
                process = self.process = self.launch(binary, port, Path(work.name))
            ready = queue.Queue(maxsize=1)
            def monitor():
                try:
                    for line in process.stdout:
                        m = BANNER.search(line[:4096].decode('utf8', errors='replace'))
                        if m:
                            try: ready.put_nowait(m[1])
                            except queue.Full: pass
                    process.wait()
                finally:
                    try: ready.put_nowait(None)
                    except queue.Full: pass
                    self.cancel.set()
                    try: on_exit(self)
                    finally: work.cleanup()
            threading.Thread(target=monitor, daemon=True).start()
            try:
                origin = ready.get(timeout=self.timeout)
            except queue.Empty:
                origin = None
            if not origin or self.cancel.is_set():
                raise Denied('Cloudflare could not open a temporary link. Check the network and try again.')
            return origin
        except BaseException:
            self.stop()
            if process is None:
                work.cleanup()
            raise

    def stop(self):
        self.cancel.set()
        with self.lock:
            process = self.process
            if process and process.stdin and not process.stdin.closed:
                process.stdin.close()
        if process and process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # launch_guard creates a fresh process group containing only our helper.
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(2)
    port = int(sys.argv[2])
    if not 1024 <= port <= 65535:
        sys.exit(2)
    sys.exit(supervise(Path(sys.argv[1]), port))
