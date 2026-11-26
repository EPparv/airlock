"""Temporary, owner-started Cloudflare transport for the agent-only listener."""
import hashlib
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
    process = subprocess.Popen([str(binary), 'tunnel', '--no-autoupdate', '--protocol', 'http2',
                                '--metrics', '127.0.0.1:0',
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


def probe_link(url, check, cancelled, *, local, seconds, transport=None):
    """Request only the expiring handshake, using the operating system's resolver."""
    import httpx
    deadline = time.monotonic() + seconds
    reason = 'connection unavailable'
    with httpx.Client(trust_env=False, timeout=3, follow_redirects=False, transport=transport) as client:
        while not cancelled.is_set():
            try:
                with client.stream('GET', url + check.path) as response:
                    if local and response.status_code == 204 and response.headers.get('X-Airlock-Link') == check.identifier:
                        return None
                    if not local and response.status_code == 200:
                        body = bytearray()
                        for chunk in response.iter_bytes(4096):
                            if len(body) + len(chunk) > 16384:
                                break
                            body.extend(chunk)
                        else:
                            if check.output().encode() in body:
                                return None
                        reason = 'unexpected verification page'
                    else:
                        reason = 'HTTP ' + str(response.status_code)
                        if response.headers.get('cf-mitigated') == 'challenge':
                            return reason + ' browser challenge'
                        if response.status_code == 429:
                            return reason + ' rate limit'
            except httpx.TimeoutException:
                reason = 'network timeout'
            except httpx.ConnectError as error:
                cause = str(error).lower()
                if 'certificate' in cause or 'ssl' in cause:
                    reason = 'TLS validation failed'
                elif any(t in cause for t in ('nodename','name resolution','name or service','name not known','no address associated')):
                    reason = 'DNS unavailable'
                else:
                    reason = 'connection unavailable'
            except httpx.HTTPError:
                reason = 'HTTP transport failed'
            left = deadline - time.monotonic()
            if left <= 0 or cancelled.wait(min(2.0, left)):
                break
    return 'workspace closed' if cancelled.is_set() else reason


def verify_route(origin, cancelled, check, *, transport=None, seconds=12):
    from .core import Denied
    if not QUICK_ORIGIN.fullmatch(origin):
        raise Denied('Cloudflare returned an invalid temporary hostname.')
    reason = probe_link(origin, check, cancelled, local=False, seconds=seconds, transport=transport)
    if reason == 'DNS unavailable':
        return False
    if reason:
        raise Denied('Public Cloudflare verification failed (' + reason + '). Try another network or a named HTTPS bridge.')
    return True


def helper_error(line, current):
    """Map known helper-side failures to safe messages. Do not retain log lines."""
    lower = line.lower()
    code = re.search(r'(?:provisioning failed with status|status code|statuscode)[:= ]+([1-5][0-9]{2})', lower)
    if code:
        return 'Cloudflare link provisioning returned HTTP ' + code[1] + '.'
    if 'failed to request quick tunnel' in lower or 'failed to unmarshal quick tunnel' in lower:
        return 'Cloudflare could not provision a temporary hostname.'
    if 'not defined' in lower and 'flag' in lower:
        return 'The installed helper rejected the tunnel settings.'
    if 'dial' in lower or 'handshake' in lower or 'tunnel connection failure' in lower:
        return 'Cloudflare edge connection failed. Allow outbound TCP port 7844 or use another network.'
    return current


class QuickTunnel:
    def __init__(self, cache, *, prepare=prepare_helper, launch=launch_guard, timeout=75):
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
            try:
                binary = self.prepare(self.cache, Path(work.name), self.cancel)
            except Denied:
                raise
            except Exception as error:
                import httpx
                if isinstance(error, httpx.HTTPStatusError):
                    raise Denied(f'Cloudflare helper download returned HTTP {error.response.status_code}.') from None
                if isinstance(error, httpx.HTTPError):
                    raise Denied('The verified helper download could not reach GitHub over HTTPS.') from None
                raise Denied('The verified helper could not be unpacked on this Mac. Check available disk space and reopen Airlock.') from None
            with self.lock:
                if self.cancel.is_set():
                    raise Denied('Link setup stopped.')
                process = self.process = self.launch(binary, port, Path(work.name))
            ready = queue.Queue(maxsize=1)
            status = {'origin':None, 'connected':False, 'error':None}
            def monitor():
                try:
                    for log_entry in process.stdout:
                        line = log_entry[:4096].decode('utf8', errors='replace')
                        match = BANNER.search(line)
                        if match:
                            status['origin'] = match[1]
                        if 'registered tunnel connection' in line.lower():
                            status['connected'] = True
                        status['error'] = helper_error(line, status['error'])
                        if status['origin'] and status['connected']:
                            try: ready.put_nowait(status['origin'])
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
                phase = ('Cloudflare assigned a hostname but the edge connection did not register. '
                         'Allow outbound TCP port 7844 or try a different network.' if status['origin'] else
                         'The helper did not receive a temporary hostname from Cloudflare.')
                raise Denied(status['error'] or phase)
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
