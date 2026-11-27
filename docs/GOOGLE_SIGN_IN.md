# Gmail sign-in for the Mac

Open **Privacy & connections → Apps & data → Gmail search**. If the publisher included its Google Desktop identity, choose **Connect Gmail**, continue to Google and grant read-only access. No developer credentials are needed on that Mac. When the setup screen asks for a Google Desktop app file, the download supports a user-owned Google Cloud project instead.

The authorization page opens in the Mac’s default browser. Google sends its response to a one-use localhost callback on that same Mac. A proof key binds the request to the open Airlock session. Finishing the Google flow on an iPhone cannot connect Gmail to a different Mac. Open **Check connection** in Airlock after consent succeeds. That check reads Gmail profile status; it does not import messages or grant an agent access. Reviewed excerpts or the existing automatic Gmail mode require a separate Airlock grant.

## Testing with your own Google project

1. Create or select your project in Google Cloud. Enable the Gmail API.
2. Configure Google Auth Platform branding, audience, and data access. For an external app in Testing, add the Gmail account you plan to use to its test users.
3. Create an OAuth client with application type **Desktop app**. Download its JSON.
4. Choose **Add Google Desktop app** on the Mac and pick that file, then **Connect Gmail**. Before connecting an account you can replace a mistaken file. Airlock ignores redirect and token endpoints in downloaded JSON and uses Google’s documented destinations.

Google controls sign-in eligibility and token lifetimes. Google can require reauthorization, including for external apps in testing.

## Publisher distribution

Register a dedicated Desktop OAuth identity, enable the Gmail API and configure the Google Auth Platform consent screen for your chosen audience. Airlock requests verified account email and the restricted scope `https://www.googleapis.com/auth/gmail.readonly`. For broad external availability, complete the applicable restricted-scope verification or confirm a Google-recognized exception. Google may require a security assessment depending on the data flow. Releasing a binary or moving the consent screen to production does not establish verification.

Set the protected repository Actions secret **AIRLOCK_GOOGLE_DESKTOP_CLIENT_JSON** to the downloaded Desktop app JSON for your project. A trusted main release uses the two application identity fields to package the public desktop client into the Mac app. Pull-request builds omit the publisher credential. Each user supplies their own Google consent and account tokens are stored locally in the encrypted Airlock vault.

The official packaging input is the `installed` Desktop OAuth JSON. Service-account keys, web-client JSON, personal access tokens and Gmail refresh tokens are rejected. Desktop client credentials are distributed inside every build that includes them. Keep other credentials out of this secret.

A trusted build can require the identity by running `python scripts/prepare_google_oauth.py --require "$RUNNER_TEMP/airlock-google.json"` and passing that file to `macos/package.py --google-client`. The release checker verifies the bundled bytes against the digest of the approved input. Give a clean Mac and a separately authorized test account the finished download for a real Google acceptance check.

[Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) · [Restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
