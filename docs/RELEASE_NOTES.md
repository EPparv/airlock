# Airlock 0.10.0

The Mac workspace adds local setup for Muse Code, Gemini CLI, VS Code with Copilot and OpenClaw. Cloud clients have a separate setup under Connect agent. The owner can assign one agent a task, review its report and release the result to a second connection.

Context imports can select individual user-authored messages from ChatGPT and Claude exports. Recall adds local semantic matching within each connection’s scope. Data protection settings can issue temporary keys for a text-only model gateway. Device connections support field selection on live local sources, preapproved destinations for local API writes, and single-use local file appends with owner review. Gmail can use an owner-supplied Google Desktop app identity.

A signed-in provider account and its permissions are still required for live third-party use. Airlock can filter requests and data that the client sends through it. The first launch downloads the Mac runtime. The Mac download is ad-hoc signed.

## Previous releases

Airlock 0.7.0 adds privacy defaults for Connect my AI: non-sensitive selections provide locally filtered excerpts, while detected sensitive records use private tasks with separate input and result approval. Local secret detection, relevant-sentence selection, stable connection-specific pseudonyms for labelled identities, and screening of generated or edited results reduce unnecessary disclosure. Core preferences and full skills remain available for continuity.

The app, website and installation guide now use consistent product language. Existing vaults, credentials, connection permissions and signed update paths are preserved. No personal records were used in validation.

Limits: rule-based filtering is not guaranteed anonymity; NEAR live confidential inference remains unverified after real attestation requests returned HTTP 401. No inference prompt was sent. Native IronClaw integration remains unverified, and the Mac app is not Apple-notarized. See docs/PRIVACY.md and docs/NEAR_VERIFICATION.md for exact behavior and evidence.
