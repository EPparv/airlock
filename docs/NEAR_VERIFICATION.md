# NEAR verification evidence — November 14, 2026

**Result: blocked before inference. Live confidential inference is not verified.** No personal records, mail, vault or Keychain data were opened for these checks. An owner-supplied credential was held only in the verification process; it is absent from this repository and the receipts.

| Check | Actual observation |
| --- | --- |
| Official SDK | `nearai-inference-sdk` 0.3.0, pinned official commit `ff591054d63a7fd218396d70f96024396280b6ff` and archive hash in `requirements-near.txt` |
| Target | `https://cloud-api.near.ai/v1`, canonical model `z-ai/glm-5.3-flash` |
| First real preflight | 2026-11-14 17:46:36 UTC: official SDK `ApiError`, code `api.http_status`, HTTP 401 |
| Owner-requested retry | 2026-11-14 17:48:26 UTC: same official SDK code and HTTP 401 |
| Independent endpoint check | Direct GET to `/v1/attestation/report?model=z-ai%2Fglm-5.3-flash&signing_algo=ed25519` also returned HTTP 401 with the supplied credential |
| Catalog connectivity | GET `/v1/models` returned HTTP 200. Catalog availability does not establish authorization for attestation or inference. |
| Inference calls | 0: verification stopped before sending an inference prompt |
| Attestation, encryption and response signature on a live inference | Not completed. No verified deployment hashes, completion ID, signed response or live encryption proof exists for these attempts. |

The synthetic prompt prepared but **not sent** was:

> This is a fictional Airlock connection test. Reply with AIRLOCK_NEAR_OK and nothing else.

Its SHA-256 is `9e64fa9f343ce2549339375a04c19d1ed8bb915693949752343033b41e74875c`.

HTTP 401 establishes that the attestation endpoint rejected authorization for these requests. It does not establish whether the account needs a different credential, an account-side change, or a provider-side fix. We did not alter the key, invent a substitute, weaken verification, use another inference route or treat a mock response as success.

## Reproduce with a working service credential

Use the app's masked NEAR setup field, or run the source-only diagnostic. It imports no personal source adapter:

```sh
.venv/bin/python scripts/verify_near_live.py --discover --ask-key --output /tmp/near-discovery.json
```

Discovery verifies fresh hardware evidence and records measured configurations; it does not approve them. Inspect those configurations against trusted deployment information. Supply reviewed `NEARAI_GATEWAY_COMPOSE_SHA256` and `NEARAI_MODEL_COMPOSE_SHA256` values through your environment, then run without `--discover`. The prompt is fixed, synthetic and makes one small billable inference request only after preflight. No retries or fallbacks occur automatically.

A successful result requires the expected answer, official CPU/GPU and TLS verification, SDK encryption, a unique `provider_tee` signature binding, the requested model, and the exact retained request/response byte verification. Success receipts retain public signer identities, deployment digests, verification time, completion ID, signed hashes and signature. Local tests use mocks or local cryptographic fixtures and are explicitly separate from live verification.

Official references: [NEAR verification flow](https://docs.near.ai/cloud/verification), [official inference SDK](https://github.com/nearai/inference-sdk/tree/ff591054d63a7fd218396d70f96024396280b6ff/py), [builder credit/key instructions](https://buildcity.github.io/build-city-hackpack/#idea).
