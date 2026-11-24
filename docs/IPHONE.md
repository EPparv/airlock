# Test Airlock on iPhone

**On the phone alone**, open the [Airlock iPhone workspace](https://airlock-iphone-lab.parv223885.chatgpt.site) in Safari using the same ChatGPT account. It has its own encrypted vault for testing permissions. All test-session requests and filtering run in the browser on this device. Use fictional records for a first run.

1. Choose **Context & memory → Create vault**. Keep the passphrase. Under **Memories**, add a note such as “Pilot contact alex@example.com.” Add a second memory and mark it **Device only**.
2. Go to **Connect agent → New test session**. Name it Research. Choose **Try session → Read shared memory**. The result should be empty.
3. Open **Shared records**, select the pilot contact, and save. The device-only memory is excluded. Read again. The session receives the note with a token in place of the email.
4. Create a second session. It starts empty and gets a different token if you share the same note. Use **Propose a memory** in either session, then review it under **Context & memory → Proposed changes**. Approving a proposal adds it to your library. Choose the audience separately.
5. Under a session’s settings, choose **Revoke session** to cut off future requests. Under **Privacy & connections**, choose **Lock iPhone vault**. Opening the library again requires your passphrase.

Safari stores the vault as encrypted website data on this device. Clearing that website’s data deletes it. Private Browsing can discard it when the session ends. Keep the passphrase somewhere you control.

**With your Mac**, open **Connect agent → Pair iPhone** in the running Mac app. Enable the HTTPS bridge, then open the one-time pairing link in Safari. The page at that link checks the permissions issued by the Mac. It has a separate origin and serves a different purpose from the iPhone-local vault. Keep the Mac awake and Airlock unlocked during the test.

See [Pair an iPhone to your Mac](IPHONE_COMPANION.md) for the exact sequence.

The downloadable Mac app sets up external agents and native Mail, Calendar, file, database, and API actions. The phone-only sessions are local test clients. Full-text privacy filtering is best effort.
