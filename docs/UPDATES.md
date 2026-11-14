# App updates and version history

Install alpha 7 once by replacing the older app and moving it to Applications.
After that, choose **Airlock → Check for Updates → Update and Restart** in the
Mac menu bar. Airlock also checks on launch; turn that off in the same menu if
desired. “About Airlock” shows the installed version. Installation always needs
a click. There is no Terminal, Python, Ollama or Git setup for the user.

The stable website distributes the newest validated build. Git tracks every
source change, while [GitHub Releases](https://github.com/EPparv/airlock/releases)
keeps a numbered Mac ZIP, source ZIP, release metadata and signature for each
published version. Do not reuse a version/build number for a changed release.

## What an update does

1. Fetch a small manifest and signature from the fixed Airlock Pages origin.
2. Verify Sigstore's certificate chain and transparency evidence, using TUF to
   refresh the trusted roots. Require the exact `EPparv/airlock` main-branch
   `checks.yml` identity, GitHub OIDC issuer, repository/ref and matching commit.
3. Offer only a higher build number compatible with this macOS version.
4. On the owner's click, fetch and verify the manifest again. Download the ZIP
   from the fixed origin and verify the signed size and SHA-256 before extraction.
5. Reject unsafe paths, symlinks, special files, duplicate names, unexpected
   top-level content and excessive sizes. Check bundle identity, version, build,
   commit and the macOS bundle signature. The publisher identity comes from the
   Sigstore signature; ad-hoc macOS signing alone does not establish it.
6. Wait for the native owner app and its authenticated local service to close.
   Use macOS's atomic directory exchange to replace only the application bundle.
7. Launch the new app and wait for its authenticated safe workspace. If startup
   fails, stop the new app, exchange the old bundle back and reopen it. Keep the
   previous bundle and a local `previous-app.json` receipt after a successful update.

The updater has no HTTP or MCP endpoint. AI agents cannot request an update.
Checks send no library content, AI credentials or device identifier. The download
host and Sigstore infrastructure can see ordinary network metadata such as the
client IP. No analytics are added. A check or verification failure leaves the
current app installed; manually triggered checks show an error.

The encrypted library, encryption keys, AI configuration files and stable
Application Support paths are retained. Personal access closes on restart.
An agent may need to reconnect after the brief local service interruption.
The updater is not a vault backup: keep encrypted backups separately. A future
release that changes the vault schema must explicitly design migration and
rollback compatibility before being published.

## Recovery and limits

Airlock must be in a writable folder, normally Applications. Read-only disks or
macOS App Translocation can block replacement; move the app, reopen it and retry.
The updater does not request administrator access or modify Gatekeeper settings.
The beta is still not Apple-notarized; release verification is a separate control.

The prior bundle is retained in a private `.Airlock-update-*` folder beside the
installed app; its exact path is recorded in Application Support's
`previous-app.json`. In a failed start it is restored automatically. The numbered
GitHub release is also available for a deliberate manual reinstall. Do not
assume that manually downgrading a future data format is safe.

Successful authenticated startup is a health check, not proof every feature of
a release works. The publishing workflow separately requires the full app
suite, desktop/mobile browser walkthrough, fresh installations and update/recovery
smoke tests on Apple silicon and Intel before publishing the feed.

## Publishing

Increase `privacy_layer/version.py`'s VERSION and BUILD, align the Python project
version, and update `docs/RELEASE_NOTES.md`. The clean main-branch workflow builds
and tests both architectures, creates the site, signs `updates.json` with its
short-lived GitHub OIDC identity, verifies the signature and negative cases, and
tests a real upgrade and failed-start recovery. No long-lived signing key is
stored in the repository or on a user's Mac. Pull requests cannot sign or publish.

Only after the update tests pass does the workflow create the numbered release
and deploy Pages. Existing version tags/assets are never overwritten. To revert
a bug, revert the source in Git and publish it with a higher build number. This
keeps monotonic update checks and a clear audit history.
