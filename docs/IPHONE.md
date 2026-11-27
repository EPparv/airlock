# Test Airlock on iPhone

Open Airlock in Safari. **Try a sample** lets anyone try two fictional agents without signing in. [Open Airlock](https://epparv.github.io/airlock/iphone/)

**Test with your own agent on iPhone.** Tap **Connect agent → Share an excerpt**, type `My demo word is cedar. Contact alex@example.com.`, then tap **Review excerpt**. With the default filters the email becomes an `[email-…]` token. Tap **Share reviewed text** and choose Messages for your Instinct conversation, or use **Copy reviewed text** and paste into Muse or Manus. Ask for the demo word. This sends the excerpt you approved and grants no continuing access to your vault.

**Test live tools in Muse or Manus.** Set up the connector once from **Connect agent** in Airlock on your Mac. Use Muse’s secure key field or Manus’s **Import MCP by JSON** in that same provider account. Keep your Mac awake with Airlock unlocked and the HTTPS bridge running. From the agent on your iPhone, ask it to call `privacy_status`, then check Airlock on the Mac for the successful call. [Cloud agent setup](REMOTE_CLIENTS.md)

To test access to memories in your encrypted iPhone vault, use fictional records. These sessions run locally in Safari.

1. Choose **Context & memory → Memories → Create vault**. Keep the passphrase. Add a note such as “Pilot contact alex@example.com.” Add a second memory and mark it **Device only**.
2. Go to **Privacy & connections → Local test sessions → New test session**. Name it Research. Choose **Try session → Read shared memory**. The result should be empty.
3. Open **Shared records**, select the pilot contact, and save. The device-only memory is excluded. Read again. The session receives the note with a token in place of the email.
4. Create a second session. It starts empty and gets a different token if you share the same note. Use **Propose a memory** in either session, then review it under **Context & memory → Proposed changes**. Approving a proposal adds it to your library. Choose the audience separately.
5. Under a session’s settings, choose **Revoke session** to cut off future requests. Under **Privacy & connections**, choose **Lock iPhone vault**. Opening the library again requires your passphrase.

Safari stores the vault as encrypted website data on this device. Clearing that website’s data deletes it. Private Browsing can discard it when the session ends. Keep the passphrase somewhere you control.

**With your Mac**, open **Privacy & connections → Pair iPhone** in the running Mac app. Enable the HTTPS bridge, then open the one-time pairing link in Safari. The page at that link checks the permissions issued by the Mac. It has a separate origin and serves a different purpose from the iPhone-local vault. Keep the Mac awake and Airlock unlocked during the test.

See [Pair an iPhone to your Mac](IPHONE_COMPANION.md) for the exact sequence.

The downloadable Mac app sets up external agents and native Mail, Calendar, file, database, and API actions. The phone-only sessions are local test clients. Full-text privacy filtering is best effort.
