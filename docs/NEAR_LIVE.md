# Airlock NEAR demo and submission

One line: For people using AI agents, Airlock runs approved private tasks through NEAR while keeping their wider context under local control.

The Build City hackpack recommends one concrete sensitive-data problem, a Confidential TEE model and a reproducible demo. Airlock uses `z-ai/glm-5.3-flash` at `https://cloud-api.near.ai/v1`, with thinking disabled for the short task. This is not the Incognito tier. The SDK still verifies both gateway and model evidence and checks the model response signature.

## Where to find it

First screen → Open NEAR private AI → Set up NEAR private AI. In the personal workspace, use NEAR / Private AI walkthrough or the setup link under Shared memory's private tasks.

## Before recording

- Obtain a NEAR AI key and credits through the official dashboard. The hackpack describes a $10 builder-credit offer, ending November 15, 2026; eligibility and availability are controlled by NEAR. No credits are claimed automatically.
- Enter the key only in the masked local field. It is retained only for this process session, never written to the fixture store, browser storage or public files.
- Install the pinned SDK with the button. No model is called during installation.
- Verify the deployment without a prompt. Review the measured configurations and approve those exact hashes. Verification failure blocks inference.
- Run the displayed fictional test. Only an actual signed expected answer is labelled passed.

## Suggested 90-second recording

1. Problem: switching agents should not require handing each provider an entire personal library.
2. Show the fictional meeting note and the separate never-share financial note.
3. Show the live NEAR test receipt. Do not show credentials or real personal records.
4. Allow the meeting note, select NEAR, review the exact prompt and approve generation.
5. Show the returned draft and the gateway, model, encryption and response-signature checks.
6. Try the restricted financial note and show local denial. If demonstrating a connected agent, show the separate result-release approval too.

## X post draft

I built Airlock at NEAR HACKATHON: a local context and permissions layer for AI agents. Choose what each agent can read, approve a private task through NEAR AI Cloud, and review the answer before sharing it. Demo below. @buidlcity @NEARProtocol @nearlegion #NEARHackathon

Use this claim only after the real NEAR workflow passes. Attach the recorded video and link the public repository. The user must publish the post; this document is not evidence of publication.

## Final submission

https://nearhackathon.com/#apply — Privacy & Private AI. Deadline November 14, 2026, 23:59 UTC / 6:59 pm New York. Requires repository, public X video post, project description, contact details, team size, mainnet NEAR payout account and consent. Confirm actual values; do not invent a wallet or duplicate an existing submission.

Sources: https://buildcity.github.io/build-city-hackpack/ and https://nearhackathon.com/HACKATHON.md (read November 14, 2026).

## Evidence boundary

Automated tests cover setup authentication, origin restrictions, key non-persistence, review expiry, blocked verification, cancellation before dispatch, expected response handling and the separate fictional workspace. They use test doubles. SDK encryption tests exercise real cryptography but do not prove a live NEAR call. A live pass is recorded only in the app after the user's actual service test.
