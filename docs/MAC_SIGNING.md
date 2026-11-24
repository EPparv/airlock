# Mac signing and notarization

Airlock can produce a Developer ID-signed, Apple-notarized universal ZIP. The Intel and Apple silicon checks install the same archive. The downloadable release metadata records its notarization status.

## Publisher setup

You need membership in the Apple Developer Program, a valid **Developer ID Application** signing certificate with its private key and credentials for Apple's notary service. For CI, use an App Store Connect **team API key** authorized for notarization. Keep private keys in your account's secret store.

For the main branch workflow in GitHub, set these repository Actions secrets:

| Secret | Value |
| --- | --- |
| `AIRLOCK_SIGNING_P12_BASE64` | Base64 of the password-protected PKCS#12 export containing the Developer ID Application certificate and its private key |
| `AIRLOCK_SIGNING_P12_PASSWORD` | Export password |
| `AIRLOCK_NOTARY_KEY_P8_BASE64` | Base64 of the App Store Connect team API key's .p8 file |

Set the repository Actions variables `AIRLOCK_APPLE_TEAM_ID`, `AIRLOCK_NOTARY_KEY_ID` and `AIRLOCK_NOTARY_ISSUER_ID` to your Apple team, key and issuer IDs. Setting `AIRLOCK_REQUIRE_NOTARIZATION=true` requires an Apple-notarized archive on main. Partial configuration stops the publisher and reports the missing names. With no Apple configuration, the test build uses an ad-hoc signature. Pull requests always run the credential-free test build.

## Build on your own Mac

Install the Developer ID Application certificate and private key in your login Keychain and configure a `notarytool` keychain profile on that Mac. With Xcode command-line tools available, run:

```sh
python3 macos/package.py artifacts/Airlock_Mac_Latest.zip \
  --developer-id "Developer ID Application: Your Organization (YOURTEAMID)" \
  --apple-team YOURTEAMID --notary-profile airlock-notary \
  --report artifacts/mac-build.json
```

Signing enables the hardened runtime, a secure timestamp and the Apple events entitlement. The publisher verifies the Team ID and Developer ID certificate chain, submits the signed bundle, waits for Apple's acceptance, staples the ticket, and packages the distribution archive. It then extracts that ZIP through Airlock's updater, validates its stapled ticket and asks Gatekeeper to assess the extracted app. An unsuccessful check stops publication. The archive digest, submission ID and team ID identify the verified result.

Run the same validation on a Mac using:

```sh
python3 -m macos.distribution artifacts/Airlock_Mac_Latest.zip artifacts/mac-build.json
```

The app still asks for the user's permission before using protected Mac applications. Notarization covers the submitted app bundle. Airlock's first-run installer separately checks the pinned downloads it installs locally.

[Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates) · [Apple notarization guide](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
