# Airlock

Airlock is a local context and permissions layer for MCP agents. It solves two problems: repeating personal context across agents, and disclosing an entire private library to get one useful answer. Each agent receives a selected view. Proposed memories, inference inputs and returned results require owner approval.

**NEAR HACKATHON 2026 track: Privacy & Private AI (`privacy`).** This is a new feature on an existing Airlock application. See [the hackathon scope and baseline diff](docs/HACKATHON.md#eligible-work-and-baseline), [the judge walkthrough](docs/JUDGE.md) and [the demo script](docs/DEMO.md).

Download the Mac app: https://epparv.github.io/airlock/

This is **0.6.0 alpha 3**, now packaged as a Mac app with the shared memory features. No Terminal, separate Python installation or Ollama is needed for the main context flow.

## Open and run on Mac

1. Download and unzip **Airlock_Mac_Latest.zip**. Move **Airlock.app** to Applications and open it.
2. The app installs its pinned runtime automatically, then opens the local control panel in your browser. First setup needs internet.
3. Import memories and skills. Gmail is optional. New Gmail sign-in is not configured in this public build; existing configured installations retain it.
4. Choose your existing Codex, Claude or Cursor app. Restart that AI, enable Airlock if prompted, and paste the test question. Keep Airlock open.

The alpha is ad-hoc signed, **not Apple-notarized**. If macOS blocks it, try opening it, then use System Settings → Privacy & Security → Open Anyway if you trust the release. A Developer ID certificate and notarization are still required to remove that first-open friction. Updates currently require replacing the app; your encrypted Application Support data is preserved.

Your existing AI generates answers with its own account. Optional private-task inference requires separately configured Ollama or NEAR. Those are not required for importing, sharing context, agent connections, or memory proposals and approvals. See [the Mac test steps](docs/MAC.md).

## Continuity across sessions

The updated transfer prompt captures a core profile, detailed projects, dated decisions, corrections, open loops, full workflows and explicit coverage gaps. Up to six owner-selected core records accompany every authorized automatic or scoped context request, even without matching keywords. Larger recall results are paginated; long records are returned in explicit parts instead of silently losing the ending.

Shared memory lets the owner pin core records, correct imported facts and retire outdated ones. New approved agent notes record source hashes and are withheld if their sources change. Connections show their last successful context request. To learn from ongoing work, enable memory proposals, review them, and include approved notes in the relevant agents' scopes.

Airlock instructs clients to refresh before substantive personalized answers and after compaction. It cannot force a host to call its tools, read hidden conversations, or reproduce a provider's internal memory and model behavior. Retrieval remains local lexical ranking with aliases, not semantic embeddings. See [the continuity acceptance test and boundaries](docs/CONTINUITY.md).

## Developer walkthrough

The source walkthrough uses fictional records and simulated agent requests. It requires Python 3.12+ and `bash Run-Airlock.command`. Its permission checks and MCP calls are real. Optional inference setup is documented in [SHARED_MEMORY.md](SHARED_MEMORY.md).

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

The public website is a product page with current Mac and source downloads. The vault, owner control panel, private prompts, credentials and MCP service run locally. Publishing the website does not publish your local server. The existing Airlock Chat website is a separate application and is not built by this repository.

## Develop and publish

```sh
python3 scripts/build_site.py
python3 scripts/check_site.py
```

`dist/` contains the website, a repeatable source ZIP and `release.json` with its SHA-256. Only `dist/` is published. The build uses an explicit source allowlist and excludes runtime data, credentials and Git history. Edit the source files, not the generated ZIP or `dist/`.

GitHub Actions tests the app, builds the universal Mac launcher, verifies first setup on Apple silicon and Intel runners, and builds the site on pushes and pull requests. Enable Pages and the `PUBLISH_PAGES` repository variable to publish successful `main` builds at a stable address after the checks pass. Netlify is also supported through `netlify.toml`, with a separate repository connection. Neither service is considered connected until its first deployment succeeds.

See [PUBLISHING.md](PUBLISHING.md) for the one-time connection, custom domain and rollback steps.

## Tests

The required companion adapters are now bundled in `vendor/`. CI runs the full Python suite on Linux and a fresh Mac install, import, agent connection and MCP retrieval smoke test. The Mac smoke test does not run a real AI conversation, Google login or Finder/Gatekeeper interaction. Live Ollama, live NEAR and native agent conversations are not exercised by CI.

MIT licensed. See [LICENSE](LICENSE).
