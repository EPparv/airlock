"""Owner-invoked Mac updates. No HTTP/MCP endpoint and no access to vault contents.

The signed manifest authenticates an exact main-branch GitHub workflow and commit.
The archive is verified before extraction. Only the application bundle is swapped;
bootstrap retains the stable Application Support paths used by keys and clients.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler

from .version import VERSION, BUILD

SITE = "https://epparv.github.io/airlock/"
IDENTITY = "https://github.com/EPparv/airlock/.github/workflows/checks.yml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"
APP_ID = "local.privateai.privacy-portable"
ARCHIVE = "Airlock_Mac_Latest.zip"
MAX_ARCHIVE = 40 * 1024 * 1024
MAX_UNPACKED = 120 * 1024 * 1024


class UpdateError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(name, limit):
    """No cookies, tokens, local context, redirects, or server-selected URLs."""
    if name not in ("updates.json", "updates.sigstore.json", ARCHIVE):
        raise UpdateError("Unknown update resource.")
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))
    request = Request(SITE + name, headers={"User-Agent": "Airlock-Updater/1", "Cache-Control": "no-cache"})
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != SITE + name:
            raise UpdateError("The update download location changed.")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("The update exceeds its size limit.")
    return data


def validate_manifest(value):
    required = {"schema", "version", "build", "commit", "archive", "sha256", "size", "minimum_macos", "notes"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != 1:
        raise UpdateError("Unsupported update format.")
    if not isinstance(value["version"], str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-alpha\.\d+)?", value["version"]):
        raise UpdateError("Invalid update version.")
    if type(value["build"]) is not int or not 1 <= value["build"] <= 100000000:
        raise UpdateError("Invalid update build.")
    if not isinstance(value["commit"], str) or not re.fullmatch("[0-9a-f]{40}", value["commit"]):
        raise UpdateError("Invalid release revision.")
    if value["archive"] != ARCHIVE or not isinstance(value["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", value["sha256"]):
        raise UpdateError("Invalid update archive.")
    if type(value["size"]) is not int or not 1 <= value["size"] <= MAX_ARCHIVE:
        raise UpdateError("Invalid archive size.")
    if not isinstance(value["minimum_macos"], str) or not re.fullmatch(r"\d+\.\d+\.\d+", value["minimum_macos"]):
        raise UpdateError("Invalid system requirement.")
    if not isinstance(value["notes"], str) or len(value["notes"]) > 2000:
        raise UpdateError("Invalid release notes.")
    return value


def verify_manifest(data, signature):
    if len(data) > 16384 or len(signature) > 131072:
        raise UpdateError("The update metadata is too large.")
    # Parsing is not trust: no value is used until all signature policies pass.
    manifest = validate_manifest(json.loads(data))
    from sigstore.models import Bundle
    from sigstore.verify import Verifier
    from sigstore.verify.policy import Identity, AllOf, GitHubWorkflowSHA, GitHubWorkflowRepository, GitHubWorkflowRef
    policy = AllOf([
        Identity(identity=IDENTITY, issuer=ISSUER),
        GitHubWorkflowRepository("EPparv/airlock"),
        GitHubWorkflowRef("refs/heads/main"),
        GitHubWorkflowSHA(manifest["commit"]),
    ])
    # Refresh the Sigstore trust root through TUF; do not silently fall back to
    # unsigned metadata or a checksum obtained from the same download server.
    bundle = Bundle.from_json(signature)
    Verifier.production().verify_artifact(data, bundle, policy)
    return manifest


def latest():
    return verify_manifest(fetch("updates.json", 16384), fetch("updates.sigstore.json", 131072))


def compatible(manifest):
    import platform
    current = tuple(int(n) for n in platform.mac_ver()[0].split("."))
    minimum = tuple(int(n) for n in manifest["minimum_macos"].split("."))
    return (current + (0, 0, 0))[:3] >= minimum


def extract_archive(data, manifest, directory):
    """Reject traversal, links, duplicates, ambiguous names and zip bombs."""
    import io
    import zipfile
    if len(data) != manifest["size"] or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise UpdateError("The downloaded update failed its checksum check.")
    directory = Path(directory)
    prefix = "Airlock/Airlock.app/"
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > 1000 or sum(x.file_size for x in entries) > MAX_UNPACKED:
            raise UpdateError("The update archive exceeds its extraction limit.")
        for entry in entries:
            name = entry.filename
            parts = PurePosixPath(name).parts
            mode = entry.external_attr >> 16
            if (name.casefold() in seen or not name.isascii() or "\\" in name or "\x00" in name
                    or name.startswith("/") or any(x in ("..", ".private", "runtime") for x in parts)
                    or "/".join(parts) != name.rstrip("/") or entry.flag_bits & 1
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise UpdateError("Unsafe entry in the update archive.")
            seen.add(name.casefold())
            if name == "Airlock/Read me.html":
                continue
            if not name.startswith(prefix):
                raise UpdateError("Unexpected file outside the application bundle.")
            relative = name.removeprefix(prefix)
            if not relative.startswith("Contents/"):
                raise UpdateError("Unexpected application file.")
            target = directory / "Airlock.app" / relative
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(archive.read(entry))
            target.chmod(0o755 if relative in ("Contents/MacOS/Airlock", "Contents/Resources/bootstrap.sh") else 0o644)
    return directory / "Airlock.app"


def app_release(app):
    app = Path(app)
    if app.is_symlink() or not app.is_dir():
        raise UpdateError("Airlock must be a regular app in a writable folder, such as Applications.")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    release = json.loads((app / "Contents/Resources/payload/release.json").read_bytes())
    if info.get("CFBundleIdentifier") != APP_ID or info.get("CFBundleVersion") != str(release.get("build")):
        raise UpdateError("The application identity does not match Airlock.")
    return release


def validate_app(app, manifest):
    release = app_release(app)
    if any(release.get(k) != manifest[k] for k in ("version", "build", "commit")):
        raise UpdateError("The application does not match the signed release.")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                   check=True, capture_output=True, timeout=30)


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def swap_apps(installed, staged):
    """macOS atomic exchange: the installed app path is never missing."""
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(installed), os.fsencode(staged), 2) != 0:  # RENAME_SWAP
        raise OSError(ctypes.get_errno(), "Could not exchange application bundles")


def live_session(base):
    """Read only the owner's local launch receipt, never the encrypted library."""
    from .launcher import probe_session
    return probe_session(Path(base) / 'app/.private/launch.json', timeout=1)


def launch_app(app, base, profile_home=None, restored=False):
    args = [str(Path(app) / "Contents/MacOS/Airlock"), "--data-dir", str(base), "--no-update-check"]
    if profile_home:
        args += ["--profile-home", str(profile_home)]
    if restored:
        args.append("--update-restored")
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def wait_ready(process, base, version, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        record = live_session(base)
        if record and record.get("version") == version and record.get("mode") == "safe-test":
            return True
        time.sleep(.5)
    return False


def stop_new_app(process, base):
    # Only terminate the native child we launched and its authenticated service.
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    record = live_session(base)
    if record and type(record.get("pid")) is int and record["pid"] > 1:
        try:
            os.kill(record["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(40):
        if not live_session(base):
            return
        time.sleep(.25)
    raise UpdateError("The new app did not stop. Its backup has been retained.")


def replace_and_restart(installed, staged, base, manifest, profile_home=None):
    """Keep the previous bundle until the new authenticated safe workspace works."""
    old = app_release(installed)
    swap_apps(installed, staged)
    process = None
    try:
        process = launch_app(installed, base, profile_home)
        if not wait_ready(process, base, manifest["version"]):
            raise UpdateError("The new version did not start.")
    except Exception:
        if process:
            stop_new_app(process, base)
        swap_apps(installed, staged)
        launch_app(installed, base, profile_home, restored=True)
        raise UpdateError("The update could not start. The previous app was restored.") from None
    atomic_json(Path(base) / "previous-app.json", {"version": old["version"], "path": str(staged)})
    return getattr(process, 'pid', None)


def install(app, base, expected_build, parent_pid, status, profile_home=None):
    app = Path(app).absolute()
    base = Path(base).resolve()
    if app.is_symlink() or parent_pid <= 1 or parent_pid != os.getppid():
        raise UpdateError("Install updates from the Airlock app menu.")
    old = app_release(app)
    if old.get("build") != BUILD or old.get("version") != VERSION:
        raise UpdateError("Quit other copies of Airlock, then try again.")
    # This file serializes concurrent native windows; it contains no user data.
    fd = os.open(base / "update.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError("An update is already in progress.") from None
        manifest = latest()
        if manifest["build"] != expected_build or expected_build <= BUILD:
            raise UpdateError("The available version changed. Check for updates again.")
        if not compatible(manifest):
            raise UpdateError("This update requires a newer version of macOS.")
        try:
            stage = Path(tempfile.mkdtemp(prefix=".Airlock-update-", dir=app.parent))
        except OSError:
            raise UpdateError("Move Airlock to a writable Applications folder, reopen it, then update.") from None
        preserve = False
        try:
            data = fetch(ARCHIVE, manifest["size"])
            staged = extract_archive(data, manifest, stage)
            validate_app(staged, manifest)
            if app_release(app) != old:
                raise UpdateError("Another copy of Airlock changed during the update.")
            atomic_json(status, {"phase": "ready", "version": manifest["version"]})
            # The native owner now quits normally, closing its local service.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    os.kill(parent_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(.2)
            else:
                raise UpdateError("Airlock did not quit. The existing app was kept.")
            for _ in range(40):
                if not live_session(base):
                    break
                time.sleep(.25)
            else:
                raise UpdateError("The local service is still running. The existing app was kept.")
            # Retain recovery files even if swapping or restarting fails.
            preserve = True
            pid = replace_and_restart(app, staged, base, manifest, profile_home)
            atomic_json(status, {"phase": "installed", "version": manifest["version"], "app_pid": pid})
        finally:
            if not preserve:
                shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "install"))
    parser.add_argument("--app", type=Path)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--expected-build", type=int)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--profile-home", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "check":
            value = latest()
            print(json.dumps({"current": VERSION, "latest": value["version"], "build": value["build"],
                              "available": value["build"] > BUILD, "compatible": compatible(value), "notes": value["notes"]}))
        else:
            if not all((args.app, args.expected_build, args.parent_pid, args.status)):
                raise UpdateError("Incomplete update request.")
            install(args.app, args.base, args.expected_build, args.parent_pid, args.status, args.profile_home)
    except Exception as error:
        # No traceback, certificate contents, filesystem contents or credentials.
        message = str(error) if isinstance(error, UpdateError) else "Could not verify or download the update. Check your connection and try again."
        if args.status:
            atomic_json(args.status, {"phase": "error", "message": message})
        print(json.dumps({"error": message}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
