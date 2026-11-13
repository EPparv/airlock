# Airlock: your memory, across agents

Development build, November 12, 2026. This extends the existing Airlock application.
The walkthrough runs in its own fictional workspace and does not update an existing Mac installation.

## Run the isolated walkthrough

1. Extract this ZIP into a new folder. Do not overwrite your existing installation.
2. Open **Run-Airlock.command**. It creates a virtual environment and installs the
   pinned base dependencies on first use. Python 3.12 or later is required.
3. Keep the Terminal window open. The launcher selects free ports and opens the
   authenticated control panel only after the server is ready.

If opening the command file is inconvenient, open Terminal in the extracted folder:

```sh
bash Run-Airlock.command
```

The basic walkthrough needs no API key and makes no AI inference call. It uses real
encrypted storage, permissions, owner approvals and MCP dispatch. The browser's
Coding/Writing agent buttons are explicitly labelled simulators, not real Codex or
IronClaw model sessions.

To generate a real answer, open Ollama on the **same computer**, with
`qwen3:4b-instruct` installed. Click **Check local AI**, then request a private task.
The selected model is configurable with `AIRLOCK_DEMO_LOCAL_MODEL`. Remote/cloud
Ollama aliases are rejected. There is no scripted-output fallback in this workflow.

For a headless launch:

```sh
PYTHONPATH=. .venv/bin/python -m privacy_layer.memory_demo --no-open
```

The private browser link is in `.agent-demo/launch.json`. Do not share that file.
Ctrl+C stops the service. **Reset demo** replaces only this isolated fictional
workspace and revokes the previous demo tokens. It never opens real Gmail or the
original vault. Demo tokens in `.agent-demo/*.token` are updated during reset.

## Ninety-second demonstration

1. **Local library:** “These are my notes and writing style. The financial record
   stays local.” Everything shown here is fictional.
2. **Read as Coding agent:** It receives the engineering context and writing skill.
   Switch to Writing agent: it receives the meeting context and writing skill.
3. **Propose a memory:** The writing agent proposes a follow-up note. Show that it
   is absent from the library until you click **Accept and save locally**.
4. **Reuse it:** In Coding agent's scope select the new note and its source meeting
   and writing-style records, then **Save access**. Read as Coding agent again.
   The approved note is available without reimporting it.
5. **Keep context from a host:** Untick “Share selected excerpts” for Writing agent,
   keep private computation enabled, and save. A raw-context request is blocked.
   Request an investor follow-up: only a task ID/status returns to the simulator.
6. **Review and generate:** Inspect the exact application prompt and destination,
   then explicitly approve. If local Ollama or verified NEAR is configured, a draft
   is generated and held locally. The caller still sees status only. Review/edit
   the answer, approve release, and read it as the requesting agent.
7. **Demonstrate a denial:** Try the financial note. It is blocked before any
   provider call. Revoke the agent and show that its next request is rejected.

If inference is unavailable, say so and demonstrate the functioning memory and
permission flow. Do not describe a mocked test response as live AI output.

## Architecture and boundaries

The existing AES-GCM store remains the source of local connection state, imports,
shared notes and audit records. Existing linked files and the original vault stay
read-only. `ContextHub` supplies one live library; `AgentMemory` applies per-agent
record scopes and source lineage before retrieval or computation. No remote
embeddings, remote ranking or background summarization is added.

| Operation | Enforced behavior |
|---|---|
| Read context | Requires a selected record and `disclose` permission. Raw excerpts reach that host/provider after local filtering. |
| Compute-only access | Raw retrieval denied. `request_private_task` returns only task metadata. Empty record selection means this connection's selected records. |
| Private task | Owner reviews exact application prompt, destination and model. Single-use approval expires after at most ten minutes. |
| Local route | Fixed loopback Ollama endpoint; local GGUF/model/context preflight; no redirects/proxies/fallback. |
| NEAR route | Official verifier, reviewed deployment hashes, required GPU evidence, attested TLS, client-side field encryption, signed response verification. Failure blocks output; no fallback. |
| Return result | Separate owner review and approval. Only the requesting connection can retrieve it, while source/connection permissions remain valid. |
| Memory or skill update | Staged proposal. Owner accepts/rejects; revision conflicts, changed sources, expiry or revoked access prevent acceptance. No arbitrary script installation or execution. |
| Derived memory | Inherits all context records in the proposing agent's scope, conservatively. Missing/private parents block retrieval. A receiving agent also needs access to those source records. |
| Revocation | Checked before dispatch, after provider preflight, before saving a response and on result retrieval. The NEAR path also rechecks at HTTP transport dispatch after SDK preparation. |

`never share` also applies to existing reviewed/automatic context retrieval and
legacy skill-package reads. Scoped connections cannot escape through legacy Gmail,
package/script execution or broad briefing tools. Owner-defined record restrictions
are separate from best-effort text redaction.

Existing broad connection grants are preserved. The new page displays them as
broad until the owner saves a selected-record scope. A new connection created on
the Shared memory page starts with **no record access**.

Shared notes retain origin, time, revision and source dependencies. Owner approval
does not turn an agent's assertion into a verified fact. Unknown semantic secrets
in arbitrary free text cannot be detected reliably; output disclosure still needs
owner review. A task does not grant the caller tools or access outside Airlock.

The demo's encryption key is a 0600 local file beside its encrypted state. It does
not protect against someone who controls the same OS account. The installed Mac
app retains its existing Keychain-backed configuration. Runtime plaintext exists
in process memory. Only metadata goes into the HMAC audit; prompts, proposals and
results are retained encrypted locally. No new telemetry is added.

Airlock cannot recall content already shared, intercept unrelated agent traffic,
rewrite another provider's internal memory or make that provider's inference
confidential. Compute-only mode protects source disclosure through Airlock; a
released result can still contain sensitive information.

## Use in the existing Mac app

This package is the source for `privacy-layer/`, not a rebuilt/notarized Mac app.
Review the diff and apply the changed files to that directory in a backed-up local
checkout, then restart its server using the existing launcher. The main panel has
a **Shared memory** link at `/memory`. Do not replace `.private`, Keychain state,
`.venv`, the companion `Private_AI` folder or your existing client configurations.

The regular app still needs its adjacent companion source or packaged `vendor/`
adapter. That source was not included in the saved review ZIP. The isolated new
walkthrough is self-contained and does not need it.

## Connect real agents

For Codex, Claude Desktop/Code, Cursor or another local stdio MCP client, create a
connection on Shared memory, select its records and permissions, and copy the
generated settings into the client. Each token is separate, expiring and revocable.
Settings reference a local token file; they do not embed a token value. Reload the
host's MCP tool list to discover the two new private-task tools.

For the isolated demo, `.agent-demo/codex-mcp.json` contains a local MCP server
entry with the dynamically selected port. It is a generic entry you can adapt to
the host's native format; it does not install or claim a native session test.

**IronClaw compatibility:** current upstream documentation at commit
`b0b999d96781516ee05e6ba961d6f3ead900da96` says HTTP(S) MCP extensions and rejects
stdio; the host-bundled extension path requires HTTPS. This differs from older
`ironclaw mcp add --transport stdio` instructions found online. The included
`integrations/ironclaw/manifest.toml.example` is a data-only v3 extension template
with `ask` permissions, scoped bearer-secret injection and automation forbidden.
Replace `https://airlock.invalid/mcp` only with a secured endpoint for the MCP
listener, keep the owner UI local, and provision the scoped credential through
IronClaw's host secret settings. Review its egress policy and installed-version
extension packaging procedure. Airlock does not publish a tunnel or loosen Host,
Origin or authentication checks. A reverse proxy must preserve the listener's
expected loopback Host. The template is **not a verified native integration**.

Official sources inspected:
- https://github.com/nearai/ironclaw/blob/b0b999d96781516ee05e6ba961d6f3ead900da96/docs/extensions/mcp.mdx
- https://github.com/nearai/ironclaw/blob/b0b999d96781516ee05e6ba961d6f3ead900da96/docs/extensions/building-a-tool.md

## NEAR setup and exact claims

Install the optional SDK from its pinned official source:

```sh
.venv/bin/python -m pip install -r requirements-near.txt
```

Set `NEARAI_API_KEY` locally through your existing secret/environment workflow.
Set `NEARAI_GATEWAY_COMPOSE_SHA256` and `NEARAI_MODEL_COMPOSE_SHA256` to independently
reviewed SHA-256 hashes of the accepted app-compose configurations. Do not copy
unverified live reports into an allowlist simply to get a green check.
`NEARAI_MODEL` defaults to `z-ai/glm-5.3-flash`; use a canonical NEAR Confidential
TEE model, not Incognito or a third-party route.

The SDK at commit `ff591054d63a7fd218396d70f96024396280b6ff` (0.3.0) is configured
with `e2ee=True`. It verifies candidate attestations, selects/pins the verified
model key and encrypts application fields. The adapter still requires gateway
TLS binding, UpToDate hardware with no advisories, verified GPU evidence and a
unique model-TEE response-signature binding. It never falls back to plaintext.
The SDK retains encrypted wire bytes for response signature verification.

The current pinned SDK uses protocol v3 with reply-key binding. The official
web guide reviewed during this work describes v2. The SDK's local cryptographic
round trip passes; deployed-model compatibility still needs a real NEAR request.
The review UI shows **application-level JSON**, not random encrypted wire bytes.
Model ID, routing, timing and other transport metadata are not all encrypted.
Deployment hashes are acceptance policy, not independent Sigstore source/build
provenance verification. Attestation does not prove absence of software bugs.

SDK installation upgraded cryptography to 50.0.2 in the tested environment through
its transitive dependencies; the base-only app is separately pinned by
`requirements.lock`. No NEAR API key or reviewed hashes were available here.

Official sources:
- https://docs.near.ai/cloud/models
- https://docs.near.ai/cloud/verification
- https://docs.near.ai/cloud/guides/e2ee-chat-completions
- https://github.com/nearai/inference-sdk/tree/ff591054d63a7fd218396d70f96024396280b6ff/py

## Validation and limits

- **349 Python tests passed**, including actual MCP HTTP/stdio discovery and calls,
  two simultaneous scoped HTTP clients, existing founder workflow checks, owner
  authentication, source restrictions and new task/proposal boundaries.
- **26 new frontend DOM checks and 35 existing founder-demo DOM checks passed** against actual production ASGI routes.
  Ollama responses were mocked and labelled. This is not rendered-browser QA.
- Actual pinned SDK encryption/decryption, fresh keys, model-key pin headers and
  reply encryption were tested with locally generated keys. Attestation was not
  performed in those crypto tests. NEAR failure tests use explicitly mocked SDKs.
- Revocation in the final NEAR dispatch trace is tested independently of preflight.
- The server launched successfully with isolated encrypted state and loopback
  owner/MCP listeners. No live local AI generation: this runtime has no reachable
  selected Ollama model. No live NEAR inference: key and reviewed hashes missing.
- Three existing test modules could not collect because the original ZIP omitted
  the companion `private_ai` package. Two additional tests in `test_automatic.py`
  require that same package and were deselected. Three macOS sandbox tests were
  skipped on Linux. No test failure was relabelled as a pass.
- Chromium launch failed with an environment socket permission error. No browser
  screenshots, native host UI recording or live inference latency is claimed.
- The running Mac app and its installed agent connections were not modified.

Reproduce the available Python suite (clear inherited proxy variables for local
test HTTP clients only):

```sh
env -u ALL_PROXY -u HTTPS_PROXY -u HTTP_PROXY -u all_proxy -u https_proxy -u http_proxy \
  PYTHONPATH=. .venv/bin/pytest -q tests \
  --ignore=tests/test_context.py --ignore=tests/test_portable.py \
  --ignore=tests/test_sources_status.py \
  -k 'not structural_mime_selection and not text_attachment_without'
```

With the original companion source restored, run the full suite without those
exclusions. For DOM checks install `jsdom@26` in a separate test dependency folder
and set `JSDOM_PATH` to its absolute module directory, then run:

```sh
node tests/memory_dom.cjs
node tests/near_dom.cjs
```

