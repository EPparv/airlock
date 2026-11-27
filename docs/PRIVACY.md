# Privacy architecture

Airlock 0.7.0 applies local controls to the data it releases through its own connections. It does not intercept another app's traffic or control its memory, retention, or other tools.

## Context and continuity

1. The owner selects exact records. Nothing is selected automatically in Connect my AI. Never-share, device-only, retired, stale and out-of-scope records are rejected, including derived records whose original sources are restricted.
2. Detected sensitive records default to private computation. Mixed selections grant excerpt access only to the non-sensitive subset. The classifier covers known medical, financial, identity, credential and other sensitive patterns; it is not universal semantic detection. Sensitivity is checked again at retrieval, including source lineage.
3. Local filtering removes known email, phone, address, identity-number, token, key, protected-phrase and private-passage patterns. Additional JWT, bearer, GitHub, Slack and Google-key patterns are covered. Filtering happens before clipping and again at the gateway's release boundary.
4. Relevant memory sentences are selected using the question. Qualifications containing terms such as “not”, “unless”, “except” and “must” remain. Responses identify shortened text. Approved core preferences and full skill instructions stay intact; remaining matches use connection-bound pages. Empty/broad queries can return the permitted filtered selection. Lexical matching can miss relevance or lose context: it is not a semantic summary.
5. Explicitly labelled people and organizations receive stable keyed pseudonyms, scoped to one connection. Unlabelled repeats of recognized identities use the same pseudonym. Pseudonyms and their local dictionary survive restarts; another connection gets different aliases. Record references are also opaque per connection. Source IDs and identity dictionaries remain in the encrypted vault. Common project names and unrecognized identities can remain visible; these aliases do not guarantee anonymity.

## Private tasks and screened results

Private computation needs separate permission on selected sources. The requesting AI receives only a task ID and status. An owner reviews the exact minimized application prompt and approves it before inference. Never-share records and authentication/recovery documents remain blocked. Other sensitive facts can be included in this approved computation; detected direct identifiers, credentials and protected phrases are still removed. A whole credential-containing passage may be withheld, so a useful task may require a separate safe fact.

Local Ollama uses a fixed loopback endpoint with local-model checks. NEAR requires the pinned official SDK, attested TLS, CPU/GPU verification, reviewed deployment hashes, client-side encryption and a unique provider-TEE response signature. There is no automatic retry or fallback to another provider. Deployment-hash approval is not independent source/build provenance verification.

A generated draft stays in the encrypted store. Airlock shows a screened suggestion, allows edits and provides **Screen edits**. Release requires explicit approval of text that passes the current screening policy. Edited PII, secrets, protected phrases or detected sensitive passages block release. Retrieval screens the approved result again and rechecks grant expiry, revocation, source changes and permissions. Screening cannot prove arbitrary prose contains no identifying facts; the owner must review meaning, not only removed patterns.

The gateway performs a final pass over human-readable source fields for reviewed, scoped and automatic responses, including skill resources. Existing automatic connections retain their broad selection permission, with stronger filtering; the update does not silently grant computation or rewrite existing permissions. Use Shared memory to restrict an existing connection to selected sources.

## Stored data and updates

No personal records were used to develop or test these changes. Tests use disposable synthetic profiles. No existing vault, Keychain entry, token, client configuration or installed app is modified during validation. Runtime alias dictionaries and task results use the existing encrypted store; audit logs do not receive raw prompts. NEAR keys remain session-only. Mac updates keep the same app identity and data location, signature verification, backups, rollback and initially closed personal workspace. Builds before 67 require one manual replacement to gain the updater.

## Limits

Rule-based redaction is not complete anonymization. Unlabelled names, novel credentials, paraphrased sensitive facts, and unique combinations of projects or dates may remain identifying. Pseudonyms intentionally allow continuity within a connection. An external host can retain the safe text it receives; revocation cannot recall copies. Airlock cannot force a host to refresh its tools or reproduce another product's personal memory. The Mac app is not Apple-notarized. Live NEAR confidential inference remains unverified; see [actual verification attempts](NEAR_VERIFICATION.md).

## Filter model requests

Open the personal workspace, choose **Privacy & connections → Data protection → Filter model requests**, and create a connection. Copy its base URL and one-time key into a client that lets you choose an OpenAI-compatible endpoint. Use the model ID `airlock`. The example reads the URL and key from your environment.

```python
import os
from openai import OpenAI

client = OpenAI(base_url=os.environ["AIRLOCK_MODEL_URL"],
                api_key=os.environ["AIRLOCK_MODEL_KEY"])

# POST /v1/chat/completions
chat = client.chat.completions.create(
    model="airlock", messages=[{"role": "user", "content": "Write a meeting agenda."}]
)
print(chat.choices[0].message.content)

# POST /v1/responses, with a string or a self-contained list of text messages
one = client.responses.create(model="airlock", input="Write a meeting agenda.")
two = client.responses.create(
    model="airlock", store=False, instructions="Use short sentences.",
    input=[{"role": "user", "content": [{"type": "input_text", "text": "Write a meeting agenda."}]}],
)
print(one.output_text, two.output_text)
```

Both routes accept system, developer, user, and assistant text. Responses instructions and all supplied history pass through the same local filter. Streaming clients receive buffered text after generation finishes. Submit the required history on each request. Tools, files, images, stored conversation IDs, provider-specific metadata, and background jobs receive an error. These limits matter for coding agents that automatically attach tools to every request. A client using its own model endpoint continues to send its prompts there.

Each connection is limited to one owner-selected model, 100 generation calls, and 24 hours. Closing the personal workspace or restarting Airlock discards the key and local connection state. Ollama runs at a fixed loopback address and must report locally installed GGUF weights. Selecting OpenAI sends the filtered text to its Chat Completions API with storage disabled. Its API key stays in process memory. Airlock never sends the local client key or arbitrary client headers to the selected model. The provider may apply its own data handling policies.

Filtering replaces known contact patterns and explicitly labelled identities with connection-specific tokens. It removes matching protected phrases, known secrets, and detected sensitive passages. Unlabelled names and identifying facts in ordinary prose can survive detection. The gateway keeps no prompt transcript. It retains a bounded identity lookup in memory for the lifetime of a connection so that subsequent messages can use the same tokens.

Wire format references are the [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat), the [Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create), and [Ollama's OpenAI compatibility guide](https://docs.ollama.com/api/openai-compatibility).
