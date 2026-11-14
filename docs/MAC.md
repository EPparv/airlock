# Mac app: first-use acceptance

Download the current app at https://epparv.github.io/airlock/. No Terminal, separately installed Python or Ollama is required for the context flow. First runtime setup needs internet. This app is ad-hoc signed, not Apple-notarized.

## Start with fictional data

1. Quit any older Airlock app, unzip the new download, move Airlock.app to Applications and open it. If macOS blocks it, use System Settings → Privacy & Security → Open Anyway only if you trust this release.
2. The browser opens **Fictional test workspace**. Confirm it says personal sources are closed. Even on a Mac with an existing library, this does not initialize personal sources or restore the Dot tunnel.
3. Run the seven checks in order. Recall must return the launch and writing style; the restricted note and email must be withheld; the correction must replace November 20 with November 27; a proposal must stay pending until approved; a fresh vault reader must recover the saved context; a revoked connection must fail its next request.
4. Open each exact response and the disclosure receipts. The restricted fictional value must never appear there. No cloud model is called by these checks.
5. Quit and reopen Airlock. The checks and corrected fictional data must persist. Personal sources must remain closed. Reset clears only the test and invalidates its old connections.

## Optional real AI experience

1. In the test screen, select Codex, Claude Desktop, Claude Code or Cursor. Explicitly allow the displayed fictional records and connect. This adds **airlock-test**, preserving an existing **airlock** entry.
2. Restart the AI and start a fresh chat. Enable only airlock-test for this check, then copy the provided prompt. The provider can receive the allowed fictional facts. Airlock does not control the AI's own memory or other tools.
3. Check that the answer uses the current launch date and two concise bullets. Check its citations against the local receipt. A context-request timestamp confirms retrieval only, not answer quality.
4. Use the fixed proposal prompt. The rehearsal note stays pending until approved in Airlock. Once approved, ask the AI to refresh and recall it.
5. Revoke all test AI connections. Fresh tool calls must fail. Old text may remain visible in the AI chat. Revocation cannot recall that text. Saved test config entries remain but their credentials no longer work.

## Personal workspace, only after opt-in

1. Explicitly open personal sources using the checkbox and button. Existing approved connections can resume with their previous permissions. Importing real information is optional; fictional text also works here.
2. Import and review context. Click **Connect my AI**. Confirm no records are preselected and private records are absent. Choose the AI and records together, then connect. Older managed Airlock settings should migrate without changing other connections.
3. Restart your AI, enable Airlock if prompted and paste the supplied question. The screen must say **Waiting for your AI** until a real context request arrives. Check the response. Further permissions can be edited in Shared memory. Gmail and arbitrary actions remain unavailable to scoped connections.
4. Correct, retire, pin and restrict records. Ask the AI to refresh and compare responses. Review proposed memories before accepting them, then add approved notes to each relevant connection's selection. Airlock cannot silently capture hidden chats.
5. Return to Fictional test & access controls and close personal access. New personal calls must fail. Quit and reopen; personal access stays closed until explicitly reopened. Saved personal data and permissions are preserved.
6. Revoke a personal connection and verify fresh requests fail even while the personal workspace is open.

Gmail is optional and read-only. New Gmail sign-in is not configured in this public build. Local skills, private-task inference, NEAR and remote IronClaw/tunnel setup have separate permissions and requirements. The isolated test does not enable them. It does not install Ollama, download model weights, create paid accounts, perform provider deletion or create a remote tunnel.

## Build and validation boundaries

`python macos/package.py artifacts/Airlock_Mac_Latest.zip --app-destination artifacts/Airlock.app` builds the universal launcher and explicit code/asset allowlist. Personal data and credentials are excluded.

`python scripts/smoke_mac.py artifacts/Airlock.app` calls the native window's bootstrap with a disposable profile and no Python or Ollama on PATH. It checks an untouched existing-vault canary, all seven guided checks, real MCP transport, separate client entries, explicit personal opt-in, zero initial record access, filtering, restart behavior and revocation. CI installs fresh runtimes on Apple silicon and Intel. This does not test Finder, Gatekeeper, Google sign-in or a real AI conversation. Provider tests do not establish live NEAR attestation.

The website publishes only after the Python suite, both Mac install checks and archive verification pass. Its stable download updates when main deploys. Downloaded copies do not auto-update; quit, download and replace the app. Keep Application Support and Keychain data intact.
