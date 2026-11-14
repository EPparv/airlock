# Reproduce Airlock

## Requirements

For the packaged Mac app, download the current build from https://epparv.github.io/airlock/. Open it, then choose **Open NEAR private AI → Set up NEAR private AI**. The setup panel installs the verifier, accepts a key for this session only, presents verified deployment configurations for review, and runs an explicitly approved fictional live test. See [NEAR_LIVE.md](NEAR_LIVE.md) for the recording walkthrough. This route does not open personal sources.

The following commands are the alternative source-code workflow.

Python 3.12 or later and internet access for the initial dependency installation. The memory walkthrough runs locally on loopback. It starts with four fictional records and creates its own `.agent-demo` workspace; it does not open the owner's existing vault or Gmail.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
bash Run-Airlock.command
```

On Windows, activate the venv and use `python -m privacy_layer.memory_demo` instead of the Bash launcher. Windows has not been runtime-tested. Python 3.12 was used for the local macOS checks and the successful Linux run in GitHub Actions.

The launcher opens the authenticated browser panel after both listeners are ready. Keep the terminal open. For a headless machine use `bash Run-Airlock.command --no-open`; the private launch URL is in `.agent-demo/launch.json`. Never publish that file or include its URL in a recording. Stop with Ctrl+C.

## Action → expected result

| Action | Visible result |
| --- | --- |
| Read context as Coding agent | Engineering context and writing style; no investor meeting or financial canary. |
| Read as Writing agent | Meeting context and writing style; no engineering note or financial canary. |
| Propose a memory | One pending proposal; the library is unchanged. |
| Owner chooses Accept and save locally | The library gains the approved memory. |
| In Coding agent access, select the new memory and its meeting/style parents, then Save access | Coding agent can reuse the new memory on its next read. |
| Try the financial record | Local denial; no provider request. |
| Revoke Writing agent and try again | Local denial, even with its old credential. |
| Reset walkthrough | Fictional state resets and earlier demo tokens are revoked. |

The Coding/Writing buttons are **simulated callers using the real gateway**. They are not live Codex or IronClaw sessions. Local memory writes, encryption and scope checks are real.

## Optional local AI

Use Ollama on the same computer with `qwen3:4b-instruct` installed, or set `AIRLOCK_DEMO_LOCAL_MODEL` to a supported local instruction model. Choose Check local AI. Request a private task; review and approve the exact prompt. After generation, the caller sees status only until the owner separately approves release. An unavailable model produces an error, not canned AI output. This path makes no NEAR claim.

## Optional NEAR inference

The Mac app's setup panel is the easiest route. Developers may instead install and configure the same SDK from the command line:

```sh
.venv/bin/python -m pip install -r requirements-near.txt
```

Supply your own `NEARAI_API_KEY`, `NEARAI_GATEWAY_COMPOSE_SHA256` and `NEARAI_MODEL_COMPOSE_SHA256` through your local environment. The hash values must come from independently reviewed deployments, not a blindly copied live report. `NEARAI_MODEL` is optional. Review [SHARED_MEMORY.md](../SHARED_MEMORY.md#near-setup-and-exact-claims) before enabling this route. The isolated demo itself needs none of these credentials.

Live NEAR generation remains unverified in this release. Missing SDK, credentials or reviewed hashes must leave the task blocked. Do not treat an environment-ready indicator as successful attestation. Do not use private real data for a first verification run.

## Automated checks and limits

The [public GitHub Actions run](https://github.com/EPparv/airlock/actions/runs/43510072813) passed 347 tests, with 4 skipped and 2 deselected, on Linux. Website links, archive scope and checksum checks also passed. These are standalone application checks; live provider calls and native client sessions were not tested by that run.

The current workflow runs the full suite with bundled adapters and the pinned NEAR SDK, a real-browser walkthrough, and package checks on Apple Silicon and Intel Macs. Releases also require signed-update and recovery checks on both platforms. Use `python -m pytest -q tests` for the suite; macOS sandbox and socket tests require an environment that permits them. The SDK encryption module skips if its optional SDK is absent. CI logs linked from each revision are the authority for that build; automated provider tests do not prove a live NEAR request.

The hosted page distributes a local Mac app, not a cloud-hosted vault. The current app includes an in-app updater and the NEAR setup flow. Native IronClaw sessions and live NEAR inference remain unverified. A live pass requires the owner's actual service test; it is never inferred from CI success.
