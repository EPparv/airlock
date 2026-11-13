# Mac app: first-use acceptance

Download the current app at https://epparv.github.io/airlock/. This is a Mac-only alpha. No Terminal, separately installed Python or Ollama is required for the main flow. Internet is required for the app's first runtime setup. AI answers use the account in your existing Codex, Claude or Cursor app.

1. Unzip, move Airlock.app to Applications, double-click. If macOS blocks this non-notarized beta, try opening it and then use System Settings → Privacy & Security → Open Anyway if you trust it.
2. Wait for the setup window. It installs pinned, hash-checked dependencies automatically and opens the local panel in your browser. You should see an empty library on a fresh Mac.
3. Import a fictional note: “Cypress launch is November 20.” Add the skill “Use two concise bullets for Cypress updates.” Review and save both.
4. Skip Gmail. Connect your existing AI using **Connect my AI**. Restart that AI and enable Airlock if it asks.
5. Ask: “Use Airlock: when is the Cypress launch, and how should you format my update?” It should retrieve both facts. Check Privacy → What was shared.
6. Open Shared memory. Select the records that a connected agent may read. Have it propose a useful new memory. Reject one proposal and approve another; only the approved one should become available under the selected scope. The complete source/privacy tests are in SHARED_MEMORY.md.
7. Quit and reopen Airlock. The imports and connection settings should remain. Your existing AI connection should work after the service restarts.
8. Revoke the connection in Airlock. The AI must lose access immediately. Creating a new connection requires owner approval.
9. To update, quit Airlock, download the latest app and replace it. Reopen and repeat steps 5–8. Do not remove Application Support or Keychain data.

Gmail is optional and read-only. New Gmail sign-in is not configured in this public build. Existing configured installations retain their connection. Local skills, private-task inference, NEAR and remote IronClaw/tunnel setup have their own permissions and setup requirements. This package does not silently install Ollama, download model weights, create paid accounts or configure a remote tunnel.

## Build and validation boundaries

`python macos/package.py artifacts/Airlock_Mac_Latest.zip --app-destination artifacts/Airlock.app` builds the universal native launcher from this repository and the explicit payload allowlist. No adjacent companion checkout is needed. App state, Google user tokens and personal exports are not packaged.

`python scripts/smoke_mac.py artifacts/Airlock.app` checks the same automatic installer the native window calls, with a disposable profile and no Python or Ollama on PATH. It checks import, client configuration, real MCP transport, filtering, restart persistence and revocation. CI runs this with fresh runtime installs on Apple silicon and Intel. This smoke test does not exercise Finder/Gatekeeper interaction, Google sign-in or a real AI conversation. Provider tests do not establish live NEAR attestation. The alpha is ad-hoc signed, not notarized.

The website publishes only after the Python tests, both Mac install checks and archive verification pass. Its stable Mac download updates when main is deployed. Downloaded copies do not auto-update.
