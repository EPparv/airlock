# NEAR HACKATHON submission preparation

Project: Airlock. Primary track: **Privacy & Private AI** (`privacy`). Rules checked November 13, 2026 at https://nearhackathon.com/HACKATHON.md.

This document prepares a submission; it is not a submission receipt. No X post or final application has been sent by this repository.

## Eligible work and baseline

Airlock existed before this submission. The vault, imports, Gmail adapter, earlier MCP tools and local execution machinery are baseline work. Only the new NEAR and shared-memory features are offered for review.

The original Mac checkout recorded its pre-NEAR source snapshot as `081b3e427c3689f67742d1989f54d3ed9f1d2087` on November 11, 2026. This repository reconstructs a sanitized snapshot from that exact source under `pre-hackathon` and `hackathon-baseline`. The reconstruction commit is dated when it was made, November 13, not backdated. The baseline deliberately excludes all earlier functionality from the claimed work, including any existing code that might itself have been developed after the October 19 announcement.

The `pre-hackathon` and `hackathon-baseline` branches hold that same baseline. The `hackathon-submission` branch marks the prepared revision; keep these review refs fixed while developing on `main`. The public history is imported from the reviewed local snapshots and does not claim to reproduce the original development commit history. After cloning, inspect the feature scope:

```sh
git diff --stat origin/pre-hackathon..origin/hackathon-submission
git diff origin/pre-hackathon..origin/hackathon-submission -- privacy_layer/near_provider.py privacy_layer/agent_memory.py privacy_layer/memory_demo.py
```

[Review the published feature diff](https://github.com/EPparv/airlock/compare/pre-hackathon...hackathon-submission).

For a ZIP download without Git history, [FEATURE_DIFF.patch](FEATURE_DIFF.patch) contains the exact implementation diff for the Python, UI, tests, optional NEAR requirements and launchers. It excludes submission prose and packaging changes. This makes the feature scope inspectable before GitHub publication too.

| Addition | Implementation |
| --- | --- |
| Confidential NEAR route with fail-closed verification and encrypted application fields | `privacy_layer/near_provider.py`, `requirements-near.txt` |
| Selected records and permissions for each agent; inherited source restrictions | `privacy_layer/agent_memory.py` |
| Proposed memories with owner acceptance and cross-agent reuse | `privacy_layer/agent_memory.py`, `privacy_layer/shared.py` |
| Separate approval of exact inference input and result disclosure | `privacy_layer/agent_memory.py`, `privacy_layer/server.py` |
| Fictional, isolated, reproducible walkthrough | `privacy_layer/memory_demo.py`, `ui/memory.*` |
| Boundary, permission and encryption checks | `tests/test_agent_memory.py`, `tests/test_near_demo.py`, `tests/test_near_encryption.py` |

This is a source preview, not the complete companion Mac application. The baseline and current source omit historical personal reports and credentials. Packaging and judge documentation are new supporting work, not a new claim about underlying AI inference.

## Readiness

| Requirement | State |
| --- | --- |
| Working, reproducible local prototype | Setup and expected observations in JUDGE.md |
| Public repository and inspectable feature diff | [EPparv/airlock](https://github.com/EPparv/airlock), with baseline and submission review branches |
| License | MIT, root LICENSE |
| Dependency and pre-existing work disclosure | Root README and this document |
| Live NEAR inference proof | Not verified; do not claim it |
| Public X demo post | Still required; for this local-only prototype, attach a video |
| Payout wallet, contact details and team size | Team must supply/confirm; do not commit the application payload |
| Final application | Not sent; review the exact payload before submission |

The final form requires the public repository and X post URLs. A source download page alone does not replace the required demo post. Deadline: November 14, 2026 at 23:59 UTC / 6:59 p.m. America/New_York. Keep the repository public through judging and the hosted page available at least through November 18, ideally November 25.

## Proposed project description

Airlock gives MCP agents shared local memory without granting every agent access to the whole library. Each connection has selected records and permissions. Agents propose new memories; the owner approves them before another permitted agent can reuse them. For a private task, the owner reviews the exact input and separately approves the result before release. The optional NEAR AI Cloud route uses the official verification/encryption SDK and blocks calls when evidence or reviewed deployment hashes are missing. The local memory and permission workflow runs with fictional data and no API key. Live NEAR inference and native IronClaw sessions remain unverified. The repository separates these additions from the existing Airlock baseline.

## Final submission boundary

Use the current official form at https://nearhackathon.com/#apply. Re-read the live rules first. Confirm the project name, lead, contact email, team size, tracks, mainnet payout account, public repository, public X demo post, description and contact consent. Do not invent a wallet or submit an empty placeholder. Check that this project has not already been submitted. One submission is permitted per repository; corrections use the organizers' request-changes flow.
