# Mac app: first-use acceptance

[Download the current Mac tester](https://try-airlock.parv223885.chatgpt.site/Airlock-Mac.zip). No Terminal, separately installed Python or Ollama is required for the context flow. First runtime setup needs internet. The download page reports notarization for the current release. Pull-request test builds use an ad-hoc signature.

## Start with fictional data

1. Quit any older Airlock app, unzip the new download, move Airlock.app to Applications and open it. If macOS blocks it, use System Settings → Privacy & Security → Open Anyway only if you trust this release.
2. The native Airlock window opens with three controls. Choose **Privacy & connections → Privacy checks**. Even on a Mac with an existing library, this does not initialize personal sources or restore the Dot tunnel.
3. Run the seven checks in order. Recall must return the launch and writing style; the restricted note and email must be withheld; the correction must replace November 20 with November 27; a proposal must stay pending until approved; a fresh vault reader must recover the saved context; a revoked connection must fail its next request.
4. Open each exact response and the disclosure receipts. The restricted fictional value must never appear there. No cloud model is called by these checks.
5. Quit and reopen Airlock. The checks and corrected fictional data must persist. Personal sources must remain closed. Reset clears only the test and invalidates its old connections.

## Connect a local agent

Open **Connect agent** and choose the app. Supported desktop clients open with an Airlock privacy check ready. The native Mac window and the local browser workspace use the same handoff. A new connection starts with zero shared records. Returning connections keep their existing permissions. Manage sharing under **Privacy & connections → Connected agents**.

Airlock shows when the agent discovers its tools, makes a tool call or reads shared context. The `privacy_status` check works with zero shared records. Send the prepared request if the agent opens a draft. Grant access to records separately in Airlock.

To set up a new local agent in a custom profile, unlock the personal workspace, then open **Connect agent → Advanced setup**. Choose the app and select **Configure access or profile**. Under **More settings → Client settings**, turn off **Save to the default profile on this Mac**. Connect and choose **Copy configuration**. Paste it in the agent’s custom profile. The configuration references an expiring credential stored on your Mac.

| Client | What Connect opens | Your next action |
| --- | --- | --- |
| Codex | A new Codex draft with the status request. If only the CLI is available, Terminal checks the Airlock registration. | Send the desktop draft. The CLI check runs automatically. |
| Cursor | A new Cursor draft with the status request. | Send the draft. Enable Airlock if Cursor asks. |
| Claude Desktop | A new Claude chat with the status request filled in. | Send the draft. Allow the tool if Claude asks. |
| Claude Code | A Claude Code draft in the Claude Mac app. If only the CLI is available, Terminal checks the Airlock registration. | Send the desktop draft. The CLI check runs automatically. |
| VS Code with GitHub Copilot | A private workspace with the Airlock status prompt selected. | Choose **Run in Chat**. Review any workspace or tool trust prompt from VS Code. |
| Muse Code | Terminal displays the exact status request. | Press **Return** to send it to Muse Code. |
| Gemini CLI | Terminal runs `gemini mcp list` and shows the registered servers and their status. | Read the Airlock entry. The check runs automatically. |
| OpenClaw | Terminal runs `openclaw mcp doctor airlock --probe` against the local gateway. | Read the probe result. The check runs automatically. |

If Airlock asks you to review a profile it couldn’t update, choose **Review connection → Connection help → Show configuration**. Copy the entry into the client’s settings.

Muse Code is Meta’s terminal agent. For the consumer Meta Muse app, open **Connect agent → Meta Muse**.

## Optional real AI experience

1. Under **Privacy checks → Test agent connection**, review **Fictional library**, choose your installed local agent and select **Connect fictional workspace**. This adds **airlock-test**, preserving an existing **airlock** entry.
2. Choose **Copy test request** and send it in a fresh agent chat with only **airlock-test** enabled. If the agent has not picked up the new server, reopen it. The provider can receive the allowed fictional facts.
3. Check that the answer uses the current launch date and two concise bullets. Check its citations against the local receipt. A context-request timestamp confirms retrieval only, not answer quality.
4. Use the fixed proposal prompt. The rehearsal note stays pending until approved in Airlock. Once approved, ask the AI to refresh and recall it.
5. Revoke all test AI connections. Fresh tool calls must fail. Old text may remain visible in the AI chat. Revocation cannot recall that text. Saved test config entries remain but their credentials no longer work.

## Personal workspace, only after opt-in

1. Open **Context & memory → Memories** and choose **Unlock workspace**. Existing approved connections can resume with their previous permissions. Importing real information is optional; fictional text also works here.
2. Import a fictional record you want to share. From the home screen choose **Connect agent**, then choose the agent. Follow the handoff in the table above. Return to Airlock to see when the agent finds its tools or makes its first call.
3. From the handoff choose **Manage access**, or open the agent under **Privacy & connections → Connected agents**. A new connection shows **Shared records · 0 selected**. Expand it, give one fictional record **Filtered excerpt** access and choose **Save access**. Ask the agent to retrieve that record from Airlock. Check its answer, then look for **Last read** beside the agent in **Connected agents**.
4. Correct, retire, pin and restrict records. Ask the AI to refresh and compare responses. Review proposed memories before accepting them, then add approved notes to each relevant connection's selection. Airlock cannot silently capture hidden chats.
5. Choose **Privacy & connections → App settings → Lock workspace**. New personal calls must fail. Quit and reopen; personal access stays closed until explicitly reopened. Saved personal data and permissions are preserved.
6. Revoke a personal connection and verify fresh requests fail even while the personal workspace is open.

Gmail is optional and read-only. Open Privacy & connections → Apps & data → Gmail search. Use **Connect Gmail** if this build includes the publisher’s Desktop app, or **Add Google Desktop app** to use your own. See [Google setup and release verification](GOOGLE_SIGN_IN.md). Local skills, private-task inference, NEAR and remote IronClaw/tunnel setup have separate permissions and requirements. The isolated test does not enable them. It does not install Ollama, download model weights, create paid accounts, perform provider deletion or create a remote tunnel.

## Build and validation boundaries

`python macos/package.py artifacts/Airlock_Mac_Latest.zip --app-destination artifacts/Airlock.app` builds the universal launcher and explicit code/asset allowlist. Personal data and credentials are excluded.

`python scripts/smoke_mac.py artifacts/Airlock.app` calls the native window's bootstrap with a disposable profile and no Python or Ollama on PATH. It checks an untouched existing-vault canary, all seven guided checks, real MCP transport, separate client entries, explicit personal opt-in, zero initial record access, filtering, restart behavior and revocation. CI launches the same archived executable on Apple silicon and Intel with fresh runtimes. It also exercises the native Cocoa window, embedded WebKit navigation, unlock prompt and update settings bridge. This does not test Finder, Gatekeeper, Google sign-in or a real AI conversation. Provider tests do not establish live NEAR attestation.

The website publishes only after the Python suite, both Mac install checks and archive verification pass. Its stable download updates when main deploys. Check for signed releases in **App settings** and approve installation. Keep Application Support and Keychain data intact.
