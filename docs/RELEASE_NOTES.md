# Airlock 0.11.7

You can open Meta Muse or Manus from Airlock and create an account before starting the HTTPS bridge. If sign-in closes the tab or redirects you away from connector setup, reopen the provider from the same connection.

# Airlock 0.11.5

Airlock can reopen its local workspace when a saved connection points to a stopped service. Connection errors now distinguish a locked workspace, an unreachable Mac, and provider setup that needs attention. Codex opens the privacy check in a dedicated local workspace. Terminal agents use the same profile Airlock configured. ChatGPT tunnel setup shows when its client is waiting for credentials, running, or stopped.

# Airlock 0.11.4

Choose an agent in Connect agent. On a Mac, the native window and the local browser workspace can open a supported client with an Airlock privacy check prepared. Airlock displays discovery or tool activity when the agent actually connects. Provider sign-in and tool approvals stay with the agent.

# Airlock 0.11.3

Connect agent now shows Codex, Cursor and Other agents. Choosing Codex or Cursor opens the app with its approved access. New connections start with no shared records. Other agents lists the remaining clients and their setup options.

iPhone pairing and cloud connection settings are in Privacy & connections. One-time excerpts are in Context & memory. On iPhone, Connect agent leads directly to Mac setup.

# Airlock 0.11.2

Choose Codex or Cursor and approve the records it may use. Airlock saves those permissions and opens the desktop app, or brings the running app forward. Airlock shows when an agent discovers its tools, makes its first call, or reads shared context. Repairing a connection preserves its existing permissions.

On iPhone, choose a one-time filtered excerpt, use a Mac for a live agent connection, or practice with two local test sessions.

# Airlock 0.11.1

A Mac can verify a temporary link itself or ask a second device to open a verification page. Enter the code displayed by the second device on the Mac. The pending link accepts only reachability verification. Pairing and agent access open after confirmation.

# Airlock 0.11.0

**Test on iPhone.** The Safari workspace stores its own encrypted vault on the phone. Create two local test agents, grant each different records, inspect filtered results and revoke access. To use actual records from your Mac, choose **Connect agent → Pair iPhone** in the Mac app. Select the records, create a one-time link and scan its QR code. Safari can request an assigned action. You still approve the write on your Mac.

**Connect a cloud agent.** The HTTPS bridge can start a temporary Cloudflare link after you approve. Airlock checks reachability before offering it for setup. Keep the Mac awake for the test. The link provider handles TLS and can see the credential and released data. Under **Cloud agents → Test a connection**, confirm a short code returned by the agent to verify that the intended app reached this grant.

**Publisher setup.** Trusted Mac builds can bundle an approved Google Desktop OAuth identity. Developer ID signing, notarization and stapling use publisher-supplied Apple credentials. The test build works with a user-owned Google app and uses ad-hoc signing.

# Airlock 0.10.0

The Mac workspace adds local setup for Muse Code, Gemini CLI, VS Code with Copilot and OpenClaw. Cloud clients have a separate setup under Connect agent. The owner can assign one agent a task, review its report and release the result to a second connection.

Context imports can select individual user-authored messages from ChatGPT and Claude exports. Recall adds local semantic matching within each connection’s scope. Data protection settings can issue temporary keys for a text-only model gateway. Device connections support field selection on live local sources, preapproved destinations for local API writes, and single-use local file appends with owner review. Gmail can use an owner-supplied Google Desktop app identity.

A signed-in provider account and its permissions are still required for live third-party use. Airlock can filter requests and data that the client sends through it. The first launch downloads the Mac runtime. The Mac download is ad-hoc signed.

## Previous releases

Airlock 0.7.0 adds privacy defaults for Connect my AI: non-sensitive selections provide locally filtered excerpts, while detected sensitive records use private tasks with separate input and result approval. Local secret detection, relevant-sentence selection, stable connection-specific pseudonyms for labelled identities, and screening of generated or edited results reduce unnecessary disclosure. Core preferences and full skills remain available for continuity.

The app, website and installation guide now use consistent product language. Existing vaults, credentials, connection permissions and signed update paths are preserved. No personal records were used in validation.

Limits: rule-based filtering is not guaranteed anonymity; NEAR live confidential inference remains unverified after real attestation requests returned HTTP 401. No inference prompt was sent. Native IronClaw integration remains unverified, and the Mac app is not Apple-notarized. See docs/PRIVACY.md and docs/NEAR_VERIFICATION.md for exact behavior and evidence.
