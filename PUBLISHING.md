# Publishing Airlock

## Current state

This repository is prepared for GitHub Pages and, alternatively, Netlify. The existing public Airlock preview remains separate until a repository deployment succeeds. The workflow does not publish until Pages is enabled and its `PUBLISH_PAGES` repository variable is set to `true`.

## GitHub repository

The public repository is https://github.com/EPparv/airlock. NEAR requires judges to be able to open it. Keep it public through judging. The packaged allowlist excludes personal vaults, secrets and historical personal reports.

Start further development from a fresh clone:

```sh
git clone https://github.com/EPparv/airlock.git
cd airlock
git switch -c your-change
```

The public import preserves the reviewed baseline and current source as separate commits. Keep `pre-hackathon`, `hackathon-baseline` and `hackathon-submission` as fixed review branches; continue normal development on `main` through pull requests. A local preparation bundle may contain equivalent tags and a different commit history. Do not force-push that bundle over the public repository.

## GitHub Pages: automatic updates after tests

In repository Settings → Pages, select GitHub Actions as the source. Set the repository Actions variable `PUBLISH_PAGES` to `true`, then run the `Validate and publish Airlock` workflow. The deploy job depends on successful tests and artifact checks, runs only on `main`, and publishes only `dist/`. Pull requests run checks without changing the live site.

Verify the URL returned by the successful deployment; an expected GitHub Pages URL is not proof of publication. A custom domain can later be added through Pages settings with the DNS records GitHub provides. No domain has been chosen yet.

## Alternative: Netlify

In Netlify, choose **Add new project → Import an existing project → GitHub**, select this repository and production branch `main`. Use:

| Setting | Value |
| --- | --- |
| Base directory | Repository root |
| Build command | `python3 scripts/build_site.py && python3 scripts/check_site.py` |
| Publish directory | `dist` |

The checked-in `netlify.toml` supplies the build configuration. A successful initial deployment provides the stable `.netlify.app` address. Check the commit shown by `release.json` against GitHub before sharing it as the latest release.

Add your domain in that project's **Domain management** screen. Use the exact DNS records Netlify returns for that domain, then wait for DNS and HTTPS validation. Do not change unrelated mail records. A domain has not been chosen or connected by this source setup.

## Each update

1. Make changes on a branch and open a pull request.
2. Review the GitHub checks and any enabled host preview.
3. Merge to `main`; the configured host builds and publishes at the same address. GitHub Pages deployment waits for the checks in this workflow.
4. Check the deployed version and download checksum. People opening the shared link see the newly published site. Installed local copies must download and install an update separately.

Use a Git revert commit if a released change needs to be undone. The next successful deployment publishes the reverted source. Keep `.agent-demo`, `.private`, `.env`, tokens and keys outside commits and releases.

## Official references

- https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
- https://docs.netlify.com/start/quickstarts/deploy-from-repository/
- https://docs.netlify.com/build/git-workflows/overview/
