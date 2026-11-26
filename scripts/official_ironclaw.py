"""Live synthetic IronClaw 1.4.1 WebUI-to-Airlock acceptance. Linux x86_64 only."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TAG = "ironclaw-v1.4.1"
PLATFORM = "ironclaw-x86_64-unknown-linux-gnu"
RELEASE = f"https://github.com/nearai/ironclaw/releases/download/{TAG}/{PLATFORM}.tar.gz"
ARCHIVE_HASH = "72b893d3e8f5f5a431cfaf9bc48e9dae71755e2d049ab4119c0646d352da4630"
BINARY_HASH = "d7579e8c79e74fbacc97e54d0625c0befd138c6f4009ce4f1e11fc610e7a2464"
CODE = re.compile(r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}")
TOOL = re.compile(r"[A-Za-z0-9_.:-]*airlock[A-Za-z0-9_.:-]*privacy_status$", re.I)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def write_new(path, value):
    with open(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as out:
        out.write(value)


def digest(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def install(root, local_binary):
    binary = root / "ironclaw"
    if local_binary:
        shutil.copy(local_binary, binary)
    else:
        archive = root / "release.tgz"
        with urllib.request.urlopen(RELEASE, timeout=90) as src, archive.open("wb") as out:
            shutil.copyfileobj(src, out)
        assert digest(archive) == ARCHIVE_HASH, "release checksum"
        with tarfile.open(archive) as tar, binary.open("wb") as out:
            member = tar.getmember(f"{PLATFORM}/ironclaw")
            assert member.isfile()
            shutil.copyfileobj(tar.extractfile(member), out)
    assert digest(binary) == BINARY_HASH, "binary checksum"
    binary.chmod(0o700)
    return binary


def nested(value, depth=0):
    if depth > 10:
        return
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from nested(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from nested(item, depth + 1)
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return
        if isinstance(decoded, (dict, list)):
            yield from nested(decoded, depth + 1)


def model_handler(observed, events):
    class Model(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def reply(self, data, ctype="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(json.dumps({"object": "list", "data": [{"id": "synthetic", "object": "model"}]}).encode())

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tools = [t.get("function", {}).get("name", "") for t in request.get("tools", [])]
            tool_results = [m for m in request.get("messages", []) if m.get("role") == "tool"]
            rows = list(nested(tool_results))
            calls = [call.get("function", {}).get("name") for m in request.get("messages", [])
                     if m.get("role") == "assistant" for call in m.get("tool_calls", [])]
            # The proof must come from the actual runtime's tool message.
            for row in rows:
                proof = row.get("connection_check")
                if isinstance(proof, str) and CODE.fullmatch(proof) and not observed.exists():
                    write_new(observed, proof)
                    events.append("native_tool_returned_code")
            name, args = None, {}
            if not observed.exists() and len(calls) < 4:
                direct = next((t for t in tools if TOOL.fullmatch(t)), None)
                matched = next((row["name"] for row in rows if isinstance(row.get("name"), str)
                                and TOOL.fullmatch(row["name"])), None)
                if direct and direct not in calls:
                    name = direct
                elif matched and "tool_call" not in calls and "tool_call" in tools:
                    name, args = "tool_call", {"name": matched, "arguments": "{}"}
                elif "tool_search" not in calls and "tool_search" in tools:
                    name, args = "tool_search", {"query": "airlock privacy_status"}
            msg = {"role": "assistant", "content": "Status check finished."}
            if name:
                events.append("native_status_selected" if name != "tool_search" else "native_search_selected")
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_" + uuid.uuid4().hex, "type": "function",
                     "function": {"name": name, "arguments": json.dumps(args)}}]}
            finish = "tool_calls" if name else "stop"
            common = {"id": uuid.uuid4().hex, "model": "synthetic", "created": int(time.time())}
            if request.get("stream"):
                if name:
                    msg["tool_calls"][0]["index"] = 0
                chunks = [{"index": 0, "delta": msg, "finish_reason": None},
                          {"index": 0, "delta": {}, "finish_reason": finish}]
                data = b"".join(b"data: " + json.dumps({**common, "object": "chat.completion.chunk",
                    "choices": [chunk]}).encode() + b"\n\n" for chunk in chunks) + b"data: [DONE]\n\n"
                self.reply(data, "text/event-stream")
            else:
                self.reply(json.dumps({**common, "object": "chat.completion", "choices": [
                    {"index": 0, "message": msg, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode())
    return Model


class Failure(Exception):
    pass


def main(args, stages):
    with tempfile.TemporaryDirectory() as fresh, contextlib.ExitStack() as stack:
        root = Path(fresh)
        binary = install(root, args.binary)
        profile, work = root / "profile", root / "work"
        work.mkdir()
        model = ThreadingHTTPServer(("127.0.0.1", 0), model_handler(args.observed_file, stages))
        threading.Thread(target=model.serve_forever, daemon=True).start()
        stack.callback(model.server_close)
        stack.callback(model.shutdown)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "IRONCLAW_REBORN_HOME": str(profile),
               "IRONCLAW_REBORN_WORKSPACE_ROOT": str(work), "SECRETS_MASTER_KEY": secrets.token_hex(32),
               "LLM_BACKEND": "openai_compatible", "LLM_BASE_URL": f"http://127.0.0.1:{model.server_port}/v1",
               "LLM_API_KEY": "synthetic", "LLM_MODEL": "synthetic", "NO_PROXY": "127.0.0.1,localhost",
               "RUST_LOG": "warn"}
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "SSL_CERT_FILE"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        sink = stack.enter_context((root / "ironclaw.log").open("w+b"))
        run = subprocess.run([binary, "onboard", "--no-service"], stdin=subprocess.DEVNULL, stdout=sink,
                             stderr=subprocess.STDOUT, env=env, cwd=work, timeout=60)
        if run.returncode:
            raise Failure("onboarding_failed")
        host = subprocess.Popen([binary, "serve", "--host", "127.0.0.1", "--port", str(port)],
                                stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=work)
        def stop():
            host.terminate()
            try:
                host.wait(8)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait(5)
        stack.callback(stop)
        for _ in range(150):
            try:
                with opener.open(base, timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.2)
        else:
            raise Failure("webui_unavailable")
        token = (profile / "webui-token").read_text().strip()

        def api(stage, path, payload=None):
            request = urllib.request.Request(base + "/api/webchat/v2/" + path,
                data=None if payload is None else json.dumps(payload).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Origin": base})
            try:
                with opener.open(request, timeout=55) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as exc:
                stages.append(stage + "_http_" + str(exc.code))
                raise Failure(stage) from None
            stages.append(stage + "_ok")
            return data

        session = api("authenticated_session", "session")
        api("authenticated_catalog", "extensions")
        write_new(args.ready_file, "ready")
        for _ in range(1200):
            if args.connection_file.exists() and args.connection_file.stat().st_size:
                try:
                    fixture = json.loads(args.connection_file.read_bytes())
                    break
                except ValueError:
                    pass
            time.sleep(.25)
        else:
            raise Failure("no_grant_received")
        if args.connection_file.stat().st_mode & 0o077:
            raise Failure("private_grant_file_permissions")
        addr = urlsplit(fixture["url"])
        if addr.scheme != "https" or addr.path != "/mcp" or addr.username or addr.password or addr.query or addr.fragment:
            raise Failure("invalid_test_endpoint")
        reg = api("registration", "extensions/register-hosted-mcp", {
            "desired_id": "airlock", "desired_name": "Airlock", "endpoint": fixture["url"],
            "auth_selection": {"kind": "bearer"}})
        package = reg["package_ref"]
        ext = "extensions/" + package["id"] + "/setup"
        api("install", "extensions/install", {"package_ref": package, "client_action_id": str(uuid.uuid4())})
        spec = api("credential_requirements", ext)
        name = next(s["name"] for s in spec["secrets"] if s["setup"]["kind"] == "manual_token")
        try:
            api("configure", ext, {"client_action_id": str(uuid.uuid4()), "action": "submit",
                                   "payload": {"secrets": {name: fixture["credential"]}}})
        except Failure:
            check = api("read_configuration", ext)
            if any(s.get("provided") for s in check.get("secrets", [])):
                stages.append("bearer_stored")
            text = (root / "ironclaw.log").read_text(errors="ignore")
            for detail in ("network_error", "published no callable tools", "unauthorized", "unauthenticated"):
                if detail in text.lower():
                    stages.append("vendor_" + detail.replace(" ", "_"))
            raise
        thread = api("open_thread", "threads", {"client_action_id": str(uuid.uuid4())})["thread"]["thread_id"]
        response = api("submit_status_request", "channels/" + session["session_channel_extension_id"] + "/messages", {
            "client_action_id": str(uuid.uuid4()), "thread_id": thread, "content": "Call the Airlock privacy_status tool once."})
        for _ in range(240):
            if args.observed_file.exists():
                return
            time.sleep(.3)
        raise Failure("native_tool_result_missing")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for flag in ("ready-file", "connection-file", "observed-file", "summary-file"):
        ap.add_argument("--" + flag, type=Path, required=True)
    ap.add_argument("--binary", type=Path)
    options = ap.parse_args()
    stages = []
    result = {"client": "official IronClaw 1.4.1 Linux binary", "selector": "synthetic local model", "ok": False, "stages": stages}
    try:
        main(options, stages)
        result["ok"] = True
    except Failure as exc:
        result["error"] = str(exc)
    except Exception as exc:
        result["error"] = type(exc).__name__
    write_new(options.summary_file, json.dumps(result))
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result["ok"] else 1)
