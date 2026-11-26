# Test an agent connection

In the unlocked Mac workspace, choose **Privacy & connections → Cloud agents → Test a connection**. Select the connection you intend to test, then choose **Start test**. Paste the displayed request in your signed-in agent and enter its eight-character reply in Airlock.

A listening bridge or a saved ChatGPT credential confirms local setup. A new status request using the tested credential returns only a code and uses one call. A tool catalog refresh alone cannot produce the code. Matching the code from your agent confirms that it received the Airlock reply. It does not verify the legal identity of the caller or the permissions of everyone with access to the same credential. Each check expires in ten minutes or when the grant expires, whichever comes first. Revoke a credential to invalidate its pending check.

Muse, Manus, IronClaw and other remote clients must call over the configured HTTPS bridge for this check. With ChatGPT, the dedicated stdio tunnel grant is the credential being tested. Use a connection with zero selected records for a first test. Starting a test preserves the grant’s other permissions.

## If the agent cannot return the code

- **Muse:** Ask it to use the personal custom connector you set up from the current Airlock schema URL. Store the token in its secure credentials flow. [Meta Help Center](https://www.meta.com/help/superintelligence/1687253048996149/)
- **Manus:** Open **Settings → Integrations → Custom MCP Servers**, verify the HTTPS URL and bearer authentication, and test the server there. Then request the code in a conversation. [Manus custom MCP servers](https://manus.im/docs/integrations/custom-mcp)
- **ChatGPT:** Select your installed plugin in ChatGPT on the web. Ensure the right workspace can use the tunnel and the connector's status tool is enabled. The Mac setup command validates its local profile using OpenAI’s `tunnel-client doctor` before running it. Keep the tunnel running during the test. [Custom MCP plugins](https://developers.openai.com/api/docs/guides/custom-mcp-server) · [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- **HTTP 429:** Check the service name and error details in the agent. For a rate limit, wait for the supplied `Retry-After` before retrying. If the response identifies a quota or a workspace policy, address it with the provider. If Airlock shows no status call, the origin of the rejection cannot be determined from the Mac. Existing scopes and credentials can be retained while checking. [OpenAI rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits)
