# Airlock

Airlock is a local context and permissions layer for MCP agents. It solves two problems: repeating personal context across agents, and disclosing an entire private library to get one useful answer. Each agent receives a selected view. Proposed memories, inference inputs and returned results require owner approval.

**NEAR HACKATHON 2026 track: Privacy & Private AI (`privacy`).** This is a new feature on an existing Airlock application. See [the hackathon scope and baseline diff](docs/HACKATHON.md#eligible-work-and-baseline), [the judge walkthrough](docs/JUDGE.md) and [the demo script](docs/DEMO.md).

Public preview/download: https://private-ai-phone-parv.parv223885.chatgpt.site/airlock/preview/

This is the **0.6.0 alpha source preview**. The isolated walkthrough works without the companion application. It is not a rebuilt or notarized Mac application, and it does not update an existing installation.

## Try it

Requires Python 3.12 or later. Extract the download into a new directory, then run:

```sh
bash Run-Airlock.command
```

First launch installs pinned Python dependencies. Keep Terminal open while using the local control panel. The walkthrough uses fictional records, encrypted storage, actual permissions and MCP calls. Its Coding and Writing buttons simulate agent requests, not model inference.

Optional real inference uses a locally installed Ollama model. NEAR confidential inference additionally requires your API key and independently reviewed deployment hashes. Neither is required for the memory walkthrough. See [SHARED_MEMORY.md](SHARED_MEMORY.md) for setup, boundaries and validation limits.

For an automated judge, from the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_agent_memory.py tests/test_near_demo.py tests/test_local_demo.py tests/test_clients.py
python3 scripts/build_site.py
python3 scripts/check_site.py
```

Expected: tests pass; the site check reports a valid archive and checksum. Provider tests use explicit mocks. These commands do not call live NEAR or prove hardware attestation. Open the local UI with `bash Run-Airlock.command` and follow the action/result table in [JUDGE.md](docs/JUDGE.md).

## How NEAR fits

The optional remote route uses **NEAR AI Cloud**, via the official [nearai/inference-sdk](https://github.com/nearai/inference-sdk) pinned in `requirements-near.txt`. `privacy_layer/near_provider.py` requests field encryption, verifies gateway and model evidence, enforces reviewed deployment hashes, checks the model response signature, and rechecks permission immediately before dispatch. Verification failures block the operation; there is no unverified-cloud fallback. The owner approves the exact application prompt before the call and separately reviews the answer before an agent can retrieve it.

**Live NEAR inference has not been verified for this release.** No live key and reviewed deployment hashes were available during validation. Passing mock tests or local SDK cryptographic tests does not prove live NEAR compatibility. This project does not deploy a smart contract, make on-chain payments, or use NEAR Intents. It is not a universal traffic interceptor or a verified native IronClaw extension.

## Existing work and dependencies

The earlier local vault, MCP gateway, imports, Gmail adapter, local skill runner and Mac interface are baseline work. The hackathon additions are the NEAR provider, exact source scopes, owner-reviewed cross-agent memory proposals, private-task input/result approvals and the isolated walkthrough. The `pre-hackathon` branch is a **reconstructed, conservative pre-NEAR snapshot**, not a claim that its commit was created before the event. The `hackathon-submission` branch identifies the prepared submission revision. After cloning, inspect `git diff origin/pre-hackathon..origin/hackathon-submission` and the [scope notes](docs/HACKATHON.md). These review branches are separate from ongoing development on `main`.

Built with Python, the official MCP SDK, Starlette/Uvicorn, cryptography AES-GCM, PyYAML, the optional official NEAR SDK, and vanilla HTML/CSS/JavaScript. Pytest and HTTPX are used for tests. Dependencies are pinned; their respective licenses apply. AI coding assistants helped implement and test the project. The product is MIT licensed. No other independently submitted project is declared in this repository; add a cross-disclosure if the team submits another project.

## What is hosted

The public website is a product page and current source download. The vault, owner control panel, private prompts, credentials and MCP service run locally. Publishing the website does not publish your local server. The existing Airlock Chat website is a separate application and is not built by this repository.

## Develop and publish

```sh
python3 scripts/build_site.py
python3 scripts/check_site.py
```

`dist/` contains the website, a repeatable source ZIP and `release.json` with its SHA-256. Only `dist/` is published. The build uses an explicit source allowlist and excludes runtime data, credentials and Git history. Edit the source files, not the generated ZIP or `dist/`.

GitHub Actions checks the isolated app and builds the site on pushes and pull requests. Enable Pages and the `PUBLISH_PAGES` repository variable to publish successful `main` builds at a stable address after the checks pass. Netlify is also supported through `netlify.toml`, with a separate repository connection. Neither service is considered connected until its first deployment succeeds.

See [PUBLISHING.md](PUBLISHING.md) for the one-time connection, custom domain and rollback steps.

## Tests

The regular Mac app still depends on an adjacent `Private_AI` companion package that is not part of this preview. CI explicitly excludes three companion-dependent modules and two companion-dependent cases; it does not represent full Mac-app validation. Live Ollama, live NEAR and native agent sessions are not exercised by CI. The standalone memory, permissions and MCP tests run normally.

MIT licensed. See [LICENSE](LICENSE).
