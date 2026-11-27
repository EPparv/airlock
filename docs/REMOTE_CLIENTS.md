# Connect a cloud agent

In the Mac app, select **Connect agent** and choose a provider. Airlock opens its official site and watches the grant for authenticated tool discovery or a call. A new grant has zero shared records and expires after one day or 100 calls. Selecting the same provider reuses its active grant and its existing permissions. If you have several active grants for that provider, choose the one to use. Manage access under **Privacy & connections → Connected agents**. You can share the same record with several agents.

| Agent | On first use | After setup |
| --- | --- | --- |
| Meta Muse | Airlock opens Muse and puts a setup request on the Mac clipboard. Paste it into Muse. Enter the schema URL in connector setup and the token in its secure credential prompt. | Opens Muse and prepares a status request to paste. |
| Manus | Airlock opens Manus. In **Connectors → Create → Add MCP by URL**, enter the server URL and store the token in the authentication settings. | Opens Manus and prepares a status request to paste. |
| ChatGPT | Airlock opens Plugins and starts local tunnel setup in Terminal. Associate your dedicated tunnel with the workspace, then install the private plugin. | Opens ChatGPT and prepares a status request to paste. Keep your tunnel running. |
| IronClaw | Enter the URL of your own IronClaw. In **Extensions → Registry → Add MCP server**, enter Airlock’s server URL and choose bearer authentication. Install the extension and enter its token in setup. | Opens your saved IronClaw address and prepares a status request to paste. |
| Other remote MCP client | In the app you use, add the provided server URL and save the token under bearer authentication. | Open your app and use its Airlock connection. |

Airlock opens official provider pages or the IronClaw host you explicitly save. A self-hosted IronClaw can use HTTPS, or HTTP on loopback on your Mac. NEAR’s former Agent Hub closed new registrations and announced a December 1, 2026 shutdown. [Agent Hub announcement](https://agent.near.ai/) Only the public setup or status request goes on the clipboard automatically. Use the explicit copy buttons in Airlock for endpoints, manifests or the one-time token. Provider sign-in, account eligibility and first-time authorization happen with the provider. Airlock shows a connection response when the agent actually contacts it. **Privacy & connections → Cloud agents** provides additional grant, bridge and test settings.

Muse Code is a separate local CLI. Select **Muse Code** in the main agent list for its local setup.

## HTTPS bridge for Muse, Manus, IronClaw and remote MCP clients

For a device test, choose **Start temporary link**. Airlock downloads the pinned Cloudflare helper on first use, verifies the package checksum, and forwards only the agent bridge. It waits for Cloudflare to register a connection over HTTP/2, then checks the local listener and an expiring verification page at the public HTTPS URL. If the Mac cannot reach the new hostname or its network requires a browser challenge, open the verification URL on a different device and enter its eight-digit code in Airlock. Select **Verify from another device** at startup to go directly to that step. During verification the public link serves only that page. The owner has ten minutes and five attempts. After success the page disappears and the scoped connector and pairing routes become available. Networks must permit outbound TCP port 7844. The service requires neither your own domain nor a Cloudflare account. Cloudflare sees credentials and data that pass through the link. Your Mac must stay awake and online.

Locking the workspace, quitting Airlock, stopping the link, or the tunnel process exiting ends the link and its grants. A new link requires a fresh pairing. Cloudflare limits temporary links to 200 in-flight requests and does not support server-sent events. Airlock MCP uses JSON responses. Clients requiring an SSE transport need a named tunnel. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) · [cloudflared 2026.11.2 release](https://github.com/cloudflare/cloudflared/releases/tag/2026.11.2).

For a persistent domain:

1. Choose **HTTPS bridge → Use my own domain**. Enter the HTTPS origin of a domain you control. The default upstream is `http://127.0.0.1:8794`. Save and enable it.
2. Configure an existing reverse proxy or HTTPS tunnel **on this Mac** to forward that dedicated hostname to the displayed upstream. The hostname must be reachable by the agent and have a certificate its service trusts. Airlock opens its agent bridge on loopback. DNS, certificates, account access and proxy operation are under your control.
3. Choose the cloud agent and create a connection. Copy the separately displayed credential to the provider's secure store. Muse receives a schema URL ending in `/openapi.json`. MCP clients receive a server URL ending in `/mcp`. The bearer token is shown once.
4. Ask the agent to call `privacy_status`. A **Last tool call** timestamp appears under Cloud agents when Airlock has served a tool request on that credential. Tool discovery alone does not produce a timestamp. If you have not shared any records, the status call still works.

For example, an existing Caddy instance on your Mac could use this site block after you set up your domain and certificate prerequisites. Replace the example hostname and use the port shown in Airlock.

```caddyfile
airlock.example.com {
    reverse_proxy 127.0.0.1:8794
}
```

The bridge serves the public API schema and authenticated agent requests. A browser can import the schema anonymously from the configured public host. Private tools require an authenticated agent request. Keep the owner URL, the owner's session fragment and the ordinary local MCP listener off the proxy. The proxy terminates TLS and can see credentials and released data. Disable request-body and authorization-header logging in that proxy. Locking the personal workspace blocks new calls. Pausing the bridge blocks HTTPS access for all cloud clients. Reopening the workspace restores approved connections within their original expiry and call budgets.

Muse can call REST tools from `/openapi.json`, including scoped memory reads and proposals, private computation, prepared actions, field-filtered reads and owner-assigned handoffs. Manus and the other MCP clients discover tools through MCP. Both transports enter the same scoped tool authorization and disclosure checks. Any text an agent receives, copies elsewhere or sends through its own tools is outside those checks.

## ChatGPT Secure MCP Tunnel

1. Have an OpenAI Platform tunnel ID, a restricted runtime key for that tunnel and the official `tunnel-client` executable on your Mac's PATH. The tunnel must be dedicated to this connection, with access limited to trusted users. Linking a shared tunnel or publishing its plugin extends the same Airlock grant to anyone who can invoke it.
2. In Airlock choose **Connect agent → ChatGPT**. Terminal opens for the dedicated tunnel ID and restricted runtime key. If it could not open, select **Open tunnel setup** in Airlock. The manual fallback command contains only local paths. The profile uses one scoped token file, separate from any Dot or Codex grant.
3. Keep that process running and the personal workspace open. In ChatGPT, choose **Plugins → Add custom MCP server → Tunnel**, select the same dedicated tunnel, and choose **No authentication** for the upstream OAuth option. The OpenAI tunnel authorizes access to the private transport and Airlock authenticates each call over stdio with the connection token.
4. Privately install the plugin and request `privacy_status`. Check **Last tool call** in Airlock. Under **Connection details**, **Check local tunnel** shows whether Terminal is waiting for credentials, checking the profile, running or stopped. **Reopen tunnel** uses the same grant. Stop the process with Ctrl-C. Revoke the grant in Airlock to end access.

ChatGPT access depends on workspace plugin permissions and tunnel association. OpenAI requires the appropriate Tunnels Read and Use permissions to run or select a tunnel. Creating or editing one also requires Manage. ChatGPT’s alternative direct HTTPS connection requires compatible OAuth for a protected server. Airlock supports its dedicated private tunnel. The static bearer-token route is for compatible remote MCP clients. Airlock does not store the runtime key. The official tunnel client receives it in the environment while running.

## Dot

Choose **Connect agent → Dot**, enter the ID of a dedicated tunnel and its restricted runtime key, and select **Connect Dot**. Airlock sets up its zero-record grant and opens Dot when the local tunnel reports ready. Install the private plugin for this tunnel in the appropriate ChatGPT workspace and select it in the intended Dot. A saved connection checks and restores its existing runtime. The Mac keeps the runtime key in the encrypted local vault. **Get tunnel-client** opens OpenAI’s official release page if the client is missing.

## Check your signed-in agent

Open **Privacy & connections → Cloud agents → Test a connection**. Start a test for the exact connection, ask the agent for its status code, then match the reply in Airlock. Each test status response contains only the code. For ChatGPT, connection help displays the tunnel setup command again when the local credential exists. [Connection tests and error recovery](CONNECTION_TESTS.md)

## Provider review and verification

Muse documents private user-created connectors and separate approval criteria for the public catalog. Manus documents adding custom MCP servers under the user's integrations. ChatGPT documents custom MCP plugins with workspace access controls. Public submission and organization-wide installation have their own provider requirements.

Protocol tests in this repository cover real loopback requests, MCP initialization, scoped REST calls, call limits, revocation, workspace locking, and tunnel command construction with a simulated runtime key. Account acceptance and authenticated use in a real Muse, Manus, IronClaw or ChatGPT session require the owner's account and reachable endpoint or associated tunnel.

- [Meta Muse custom connectors](https://www.meta.com/en-gb/help/superintelligence/1687253048996149/)
- [Meta Muse catalog guidelines](https://platform.muse.ai/docs)
- [Manus connectors](https://www.manus.im/features/connectors)
- [ChatGPT custom MCP servers](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [IronClaw hosting and setup](https://github.com/nearai/ironclaw/blob/main/docs/quickstart.mdx)
