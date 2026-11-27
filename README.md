# Airlock

Airlock is a local context and permissions layer for MCP agents. It solves two problems: repeating personal context across agents, and disclosing an entire private library to get one useful answer. Each agent receives selected, locally filtered context. Sensitive records use private tasks with separate input and result approvals. Useful preferences stay available across sessions.

[Download the Mac tester](https://try-airlock.parv223885.chatgpt.site/Airlock-Mac.zip)

Version **0.11.7** opens in its own Mac window. The home screen has three controls.

## The workspace

- **Connect agent** lets you choose an installed app or an online agent. Supported clients open with the Airlock privacy check ready. New connections share zero records.
- **Context & memory** holds memories, reusable skills, imports, linked sources and agent proposals. Search, edit, pin, retire or restrict a record. Review imported records before saving. Skill packages and their generated files are under Skills.
- **Privacy & connections** contains connected agents, the local redaction tester, app and data permissions, write approvals, disclosure receipts, private inference, diagnostics and app settings. Mail recipients, calendar details and attachments resolve locally. You can give each agent selected fields from a live on-device SQLite database, CSV or JSON file, or a snapshot. Agents can request a write to one configured API endpoint or an append to a specific file. You approve the exact payload. The endpoint receives approved values and the agent receives a receipt.

Only tools routed through Airlock use these policies. Free-text detection is best effort. Providers can retain the excerpts you release. Apple Mail needs a configured sending account, and Calendar needs a writable calendar. macOS may ask for Automation permission. If a write is unconfirmed, check the destination before retrying it.

## Test on iPhone

Open [the iPhone sample](https://try-airlock.parv223885.chatgpt.site/#sample) in Safari. Switch between the writing and planning agents to see which fictional memory each can read. Revoke one agent and switch back to the other. The sample runs in memory and resets when you leave. Anyone with the link can try it without an account.

On iPhone, **Connect agent → Set up on Mac** shares the Mac setup link. To test permissions with your own iPhone vault, open **Privacy & connections → Local test sessions**. Safari stores this vault on your device. Clearing website data removes it. To use Mac records on your phone, open **Privacy & connections → Pair iPhone** on the Mac, enable the HTTPS bridge, select records, and scan the one-time code. You can request an assigned action from your phone and approve it on your Mac.

## Open and run on Mac

1. Unzip the Mac download, move **Airlock.app** to Applications and open it. First setup downloads the pinned runtime. Subsequent launches use the installation on your Mac.
2. Choose **Context & memory → Memories → Unlock workspace → Add memory**, or import existing context. Personal access opens only after you choose to unlock it.
3. Choose **Connect agent** and pick an app. For Codex and Cursor, Airlock saves the connection and opens the app with a privacy check ready. You can give it access to selected memories under **Privacy & connections → Connected agents**.
4. Manage access under **Privacy & connections → Connected agents**. Use **App settings → Lock workspace** to close personal access. To explore with fictional data while locked, choose **Privacy checks**.

Quitting and reopening starts with personal access closed. Test results persist in their own encrypted fixture vault; its key is stored beside it because it contains only fictional fixtures. Personal vault keys continue to use macOS Keychain. Resetting the test revokes test connections and replaces only fictional data. For Gmail on a fresh installation, open Apps & data → Gmail search. Choose Connect Gmail if this download includes the publisher’s Google Desktop app, or add your own OAuth client. Gmail reads require consent from the account holder. [Gmail setup](docs/GOOGLE_SIGN_IN.md)


The download page shows the signing status for its exact Mac archive. Pull-request testing builds are ad-hoc signed. If macOS blocks one, try opening it, then use System Settings → Privacy & Security → Open Anyway if you trust the build. Public releases can use [Developer ID signing and Apple notarization](docs/MAC_SIGNING.md). From build 67, use **Airlock → Check for Updates → Update and Restart**. The app checks at launch by default; this can be disabled in its menu. Versions before build 67 need one manual replacement to add the updater. Your encrypted Application Support data is preserved, and personal access closes on restart. Numbered downloads are kept in [GitHub Releases](https://github.com/EPparv/airlock/releases). See [update verification and recovery](docs/UPDATES.md).

Your existing AI generates answers with its own account. Optional private-task inference requires separately configured Ollama or NEAR. Those are not required for importing, sharing context, agent connections, or memory proposals and approvals. See [the Mac test steps](docs/MAC.md).

## Connection setup

The main setup shows common desktop AIs and the records to share together. Manual integrations, connection duration and request limits are under optional controls. Private, retired and stale records are excluded; changing a selected record requires a fresh review before connecting. Memory proposals remain opt-in and owner-reviewed.

Managed connections from an earlier Airlock installation are migrated to the installed app. Settings are backed up first, unrelated connections are preserved, and unknown/custom entries are never overwritten. Invalid configuration errors are distinct from ownership conflicts. The connection screen shows separate status for saved settings, tool discovery, the first tool call and the first context read.

## Connect cloud agents and hand work to another agent

Open **Connect agent** and choose a provider under **Online**. For Meta Muse, open the custom API connector flow. For Manus, use a private HTTPS MCP endpoint. ChatGPT uses an owner-configured Secure MCP Tunnel. Start with an empty scope, choose the records a connection needs, then check its last successful request. The Mac must be awake and unlocked in Airlock. See [cloud agent setup](docs/REMOTE_CLIENTS.md).

Under **Privacy & connections → Approvals & activity → Agent handoffs**, give one agent an assignment and choose who should receive the outcome. The worker claims the assignment and submits a report. You review and release the exact text for the second agent. Each agent uses its own permissions, and a separately approved memory proposal can outlive the handoff.

Under **Privacy & connections → Data protection → Filter model requests**, create a client key for Ollama on this Mac or your OpenAI API account. Point a compatible client at the displayed base URL with model `airlock`. Airlock screens plain text before dispatch. It rejects unsupported traffic, including native tool calls and attachments. Each connection has its own key, call budget and lifetime. See [gateway behavior](docs/PRIVACY.md).

## Privacy by default

Connect my AI grants filtered excerpt access only to non-sensitive selections. Detected medical, financial, identity and other sensitive records default to private tasks; mixed selections can still share ordinary preferences immediately. Never-share records remain unavailable for either route. Existing grants are not expanded or revoked by an update.

Airlock strips detected PII and secrets locally, selects relevant sentences, and assigns stable connection-specific pseudonyms to explicitly labelled people and organizations. Core preferences and full skill instructions preserve continuity. Generated results and owner edits are screened before release, and checked again when the agent retrieves them. No external redaction service receives the original records.

Detection is rule-based and incomplete. Unlabelled names, unusual secrets and combinations of ordinary facts can still identify a person. The agent/provider can retain the text it receives. See [the privacy architecture and limits](docs/PRIVACY.md).

## Continuity across sessions

The updated transfer prompt captures a core profile, detailed projects, dated decisions, corrections, open loops, full workflows and explicit coverage gaps. Up to six owner-selected core records accompany every authorized automatic or scoped context request, even without matching keywords. Larger recall results are paginated. Relevant memory sentences are selected locally and marked when shortened; core preferences and full skill instructions remain intact. Long selected text is returned in explicit parts.

Shared memory lets the owner pin core records, correct imported facts and retire outdated ones. New approved agent notes record source hashes and are withheld if their sources change. Connections show their last successful context request. To learn from ongoing work, enable memory proposals, review them, and include approved notes in the relevant agents' scopes.

Airlock instructs clients to refresh before substantive personalized answers and after compaction. It cannot force a host to call its tools, read hidden conversations, or reproduce a provider's internal memory and model behavior. Airlock combines lexical matches with local associations and, where available, Apple’s on-device English sentence embeddings. You can also import selected user messages from ChatGPT and Claude exports. See [the continuity acceptance test and boundaries](docs/CONTINUITY.md).

## Developer walkthrough

**NEAR HACKATHON 2026 track: Privacy & Private AI (`privacy`).** This is a new feature on an existing Airlock application. See [the hackathon scope and baseline diff](docs/HACKATHON.md#eligible-work-and-baseline), [the judge walkthrough](docs/JUDGE.md) and [the demo script](docs/DEMO.md).

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

## Use NEAR from the app

Choose **Privacy & connections → Privacy checks → Private inference walkthrough → Walkthrough NEAR settings**. This workspace uses fictional data and does not open personal sources.

1. Get a key from [NEAR AI Cloud](https://cloud.near.ai) or [NEAR Builders hackathon credits](https://nearbuilders.org/dashboard). Paste it into Airlock's local masked field. Keys remain in process memory only and are cleared on restart.
2. Click **Install verifier** if needed. This installs the pinned official SDK and dependencies; it makes no model call.
3. Click **Verify deployment**. Airlock checks TLS and CPU/GPU evidence, then displays the measured gateway/model configurations. Review and explicitly approve those exact configurations. This pins them for the session; hardware attestation is not a code audit.
4. Click **Test inference**, review the displayed prompt and choose **Run test**. The displayed synthetic prompt uses no personal context, makes one small billable call, and must return the expected signed result. The UI records actual checks and time; readiness alone is never labelled a live pass.
5. Open **Inference walkthrough**, choose **NEAR confidential inference**, allow the fictional meeting note, review the request, and generate. The restricted financial note must remain blocked. For real agent requests, Shared memory also requires separate approval before releasing the result to the requesting agent.

The setup route is local and owner-authenticated. It has no Incognito or unverified fallback. The cloud API key is never stored beside the fictional vault key. Live operation still needs the user's key, available credits, supported verification hardware evidence, reviewed deployment configurations and network access. See [the NEAR demo and submission guide](docs/NEAR_LIVE.md).

## How NEAR fits

The optional remote route uses **NEAR AI Cloud**, via the official [nearai/inference-sdk](https://github.com/nearai/inference-sdk) pinned in `requirements-near.txt`. `privacy_layer/near_provider.py` requests field encryption, verifies gateway and model evidence, enforces reviewed deployment hashes, checks the model response signature, and rechecks permission immediately before dispatch. Verification failures block the operation; there is no unverified-cloud fallback. The owner approves the exact application prompt before the call and separately reviews the answer before an agent can retrieve it.

**Live NEAR inference has not been verified for this release.** Real attestation requests with an owner-supplied key returned HTTP 401 on November 14, 2026, including an explicit retry and a direct endpoint check. No inference prompt was sent and no cryptographic verification passed. See [the exact verification evidence](docs/NEAR_VERIFICATION.md). Passing mock tests or local SDK cryptographic tests does not prove live NEAR compatibility. This project does not deploy a smart contract, make on-chain payments, or use NEAR Intents. It is not a universal traffic interceptor or a verified native IronClaw extension.

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

The required companion adapters are now bundled in `vendor/`. CI runs the full Python suite on Linux and a fresh Mac install, isolated test, explicit personal opt-in, initially closed agent connection and MCP retrieval smoke test. The Mac smoke test does not run a real AI conversation, Google login or Finder/Gatekeeper interaction. Live Ollama, live NEAR and native agent conversations are not exercised by CI.

MIT licensed. See [LICENSE](LICENSE).
