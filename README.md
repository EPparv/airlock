# Airlock

Airlock is a local context and permissions layer for MCP agents. It solves two problems: repeating personal context across agents, and disclosing an entire private library to get one useful answer. Each agent receives selected, locally filtered context. Sensitive records use private tasks with separate input and result approvals. Useful preferences stay available across sessions.

Download the Mac app: https://epparv.github.io/airlock/

Version **0.8.0** adds a local action workspace for connected agents. No Terminal, separate Python installation or Ollama is needed for the main context flow.

## The workspace

- **Actions** queues a message with an optional attachment, a calendar event, or access to specific data fields. Agents receive a reference scoped to their connection. Mail recipients, event details and attachments stay in the local action. Review the exact write before Airlock sends it to Apple Mail or Calendar.
- **Agents** connects Claude Desktop, Claude Code, Codex or Cursor. Each agent starts with empty record access. You can enable follow-ups to the selected Mail sender or the attendees of the most recent Calendar meeting. Airlock resolves the recipient on your Mac. Restart the client after connecting.
- **Library** stores shared memories and skills in the encrypted personal vault. Approve proposed updates here. Device-only records remain private.
- **Activity** shows the actual response returned to each agent. Field views support a fixed JSON GET API, JSON/CSV files and SQLite snapshots. Select the permitted fields. Airlock filters values and gives each connection its own identity tokens. Free-text detection is best effort. A cloud AI sees the filtered context you choose to share and can retain it. Only tools routed through Airlock use these policies.

Apple Mail needs a configured sending account. Calendar events require a writable calendar. macOS may ask for Automation permission on first use. An unconfirmed submission stays available for inspection and requires checking the destination app. The initial fictional example uses neither app.

## Open and run on Mac

1. Download and unzip **Airlock_Mac_Latest.zip**. Move **Airlock.app** to Applications and open it.
2. The app installs its pinned runtime automatically, then opens the local control panel in your browser. First setup needs internet.
3. Approve the fictional Mail example, inspect its receipt, and try reading the selected pipeline fields. Open **Privacy checks** for the seven guided checks. Your existing personal library, Gmail and source files stay closed.
4. Optionally add the separate **airlock-test** connection to Codex, Claude or Cursor. Restart that AI and use the prompts shown. Only allowed fictional records are available through this connection; the AI's other tools and memories are outside Airlock's control.
5. When ready, explicitly open the personal workspace. Open **Library** to add memories or skills. In **Agents**, choose **Connect agent** and select its exact records and device permissions. Nothing is preselected. Connect, restart your AI and paste the first question. Airlock distinguishes saved settings from a real context request. Connections created without a selection still have no record access. Existing approved connections retain their permissions and can resume only while personal access is open.

Quitting and reopening starts with personal access closed. Test results persist in their own encrypted fixture vault; its key is stored beside it because it contains only fictional fixtures. Personal vault keys continue to use macOS Keychain. Resetting the test revokes test connections and replaces only fictional data. New Gmail sign-in is not configured in this public build; existing configured installations retain it.


The Mac app is ad-hoc signed, **not Apple-notarized**. If macOS blocks it, try opening it, then use System Settings → Privacy & Security → Open Anyway if you trust the release. A Developer ID certificate and notarization are still required to remove that first-open friction. From build 67, use **Airlock → Check for Updates → Update and Restart**. The app checks at launch by default; this can be disabled in its menu. Versions before build 67 need one manual replacement to add the updater. Your encrypted Application Support data is preserved, and personal access closes on restart. Numbered downloads are kept in [GitHub Releases](https://github.com/EPparv/airlock/releases). See [update verification and recovery](docs/UPDATES.md).

Your existing AI generates answers with its own account. Optional private-task inference requires separately configured Ollama or NEAR. Those are not required for importing, sharing context, agent connections, or memory proposals and approvals. See [the Mac test steps](docs/MAC.md).

## Connection setup

The main setup shows common desktop AIs and the records to share together. Manual integrations, connection duration and request limits are under optional controls. Private, retired and stale records are excluded; changing a selected record requires a fresh review before connecting. Memory proposals remain opt-in and owner-reviewed.

Managed connections from an earlier Airlock installation are migrated to the installed app. Settings are backed up first, unrelated connections are preserved, and unknown/custom entries are never overwritten. Invalid configuration errors are distinct from ownership conflicts. A saved settings file is not proof that an AI connected: the UI waits for a real context request.

## Privacy by default

Connect my AI grants filtered excerpt access only to non-sensitive selections. Detected medical, financial, identity and other sensitive records default to private tasks; mixed selections can still share ordinary preferences immediately. Never-share records remain unavailable for either route. Existing grants are not expanded or revoked by an update.

Airlock strips detected PII and secrets locally, selects relevant sentences, and assigns stable connection-specific pseudonyms to explicitly labelled people and organizations. Core preferences and full skill instructions preserve continuity. Generated results and owner edits are screened before release, and checked again when the agent retrieves them. No external redaction service receives the original records.

Detection is rule-based and incomplete. Unlabelled names, unusual secrets and combinations of ordinary facts can still identify a person. The agent/provider can retain the text it receives. See [the privacy architecture and limits](docs/PRIVACY.md).

## Continuity across sessions

The updated transfer prompt captures a core profile, detailed projects, dated decisions, corrections, open loops, full workflows and explicit coverage gaps. Up to six owner-selected core records accompany every authorized automatic or scoped context request, even without matching keywords. Larger recall results are paginated. Relevant memory sentences are selected locally and marked when shortened; core preferences and full skill instructions remain intact. Long selected text is returned in explicit parts.

Shared memory lets the owner pin core records, correct imported facts and retire outdated ones. New approved agent notes record source hashes and are withheld if their sources change. Connections show their last successful context request. To learn from ongoing work, enable memory proposals, review them, and include approved notes in the relevant agents' scopes.

Airlock instructs clients to refresh before substantive personalized answers and after compaction. It cannot force a host to call its tools, read hidden conversations, or reproduce a provider's internal memory and model behavior. Retrieval remains local lexical ranking with aliases, not semantic embeddings. See [the continuity acceptance test and boundaries](docs/CONTINUITY.md).

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

On the first screen, choose **Open NEAR private AI**, then **Set up NEAR private AI**. This workspace uses fictional data and does not open personal sources.

1. Get a key from [NEAR AI Cloud](https://cloud.near.ai) or [NEAR Builders hackathon credits](https://nearbuilders.org/dashboard). Paste it into Airlock's local masked field. Keys remain in process memory only and are cleared on restart.
2. Click **Install NEAR verifier** if needed. This installs the pinned official SDK and dependencies; it makes no model call.
3. Click **Verify deployment without sending a prompt**. Airlock checks TLS and CPU/GPU evidence, then displays the measured gateway/model configurations. Review and explicitly approve those exact configurations. This pins them for the session; hardware attestation is not a code audit.
4. Click **Approve and run this test**. The displayed synthetic prompt uses no personal context, makes one small billable call, and must return the expected signed result. The UI records actual checks and time; readiness alone is never labelled a live pass.
5. Open **Private AI walkthrough**, choose **NEAR**, allow the fictional meeting note, review the request, and generate. The restricted financial note must remain blocked. For real agent requests, Shared memory also requires separate approval before releasing the result to the requesting agent.

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
