# Reproduce Airlock

## Requirements

Python 3.12 or later and internet access for the initial dependency installation. The memory walkthrough runs locally on loopback. It starts with four fictional records and creates its own `.agent-demo` workspace; it does not open the owner's existing vault or Gmail.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
bash Run-Airlock.command
```

On Windows, activate the venv and use `python -m privacy_layer.memory_demo` instead of the Bash launcher. Windows has not been runtime-tested. Python 3.12 on macOS was used for the current available tests; Linux coverage is configured in CI.

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
| Reset demo | Fictional state resets and earlier demo tokens are revoked. |

The Coding/Writing buttons are **simulated callers using the real gateway**. They are not live Codex or IronClaw sessions. Local memory writes, encryption and scope checks are real.

## Optional local AI

Use Ollama on the same computer with `qwen3:4b-instruct` installed, or set `AIRLOCK_DEMO_LOCAL_MODEL` to a supported local instruction model. Choose Check local AI. Request a private task; review and approve the exact prompt. After generation, the caller sees status only until the owner separately approves release. An unavailable model produces an error, not canned AI output. This path makes no NEAR claim.

## Optional NEAR inference

```sh
.venv/bin/python -m pip install -r requirements-near.txt
```

Supply your own `NEARAI_API_KEY`, `NEARAI_GATEWAY_COMPOSE_SHA256` and `NEARAI_MODEL_COMPOSE_SHA256` through your local environment. The hash values must come from independently reviewed deployments, not a blindly copied live report. `NEARAI_MODEL` is optional. Review [SHARED_MEMORY.md](../SHARED_MEMORY.md#near-setup-and-exact-claims) before enabling this route. The isolated demo itself needs none of these credentials.

Live NEAR generation remains unverified in this release. Missing SDK, credentials or reviewed hashes must leave the task blocked. Do not treat an environment-ready indicator as successful attestation. Do not use private real data for a first verification run.

## Automated checks and limits

Run the four modules listed in the root README for the standalone judge checks. For the broader suite, use the command in SHARED_MEMORY.md. Three modules and two cases require the omitted companion application. Three Mac sandbox cases cannot run inside the current restricted session. The SDK encryption module skips when the optional SDK is absent. These limitations are distinct from successful tests, and CI logs are the authority for a particular GitHub run.

The hosted preview is a download page, not a cloud-hosted vault. Native IronClaw sessions, a rebuilt Mac installer, live NEAR inference and automatic local-app updates are not claimed.
