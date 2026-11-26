# Connect a cloud agent

Open **Connect agent → Other agents** in the Mac app and choose the online agent you use. Create a separate connection for each agent. A new connection can check its status. It starts with zero shared records and no permission to propose changes, compute on records or request email/calendar follow-ups. Use **Choose permissions** to select records and permissions. Assign local actions or handoffs separately. The same record can be selected for multiple agents.

| Client | Connection | Setup in the client |
| --- | --- | --- |
| Meta Muse | HTTPS REST with an OpenAPI schema and a dedicated bearer token | Ask Muse to make a custom connector from the schema URL. Enter the token in its secure credential flow. |
| Manus | Streamable HTTP MCP with a dedicated bearer token | Open Settings → Integrations → Custom MCP Servers, add the URL, select bearer authentication and test the connection. |
| ChatGPT | OpenAI Secure MCP Tunnel with a dedicated local stdio grant | Use an existing dedicated tunnel associated with your ChatGPT workspace, then install its private plugin. |
| IronClaw | HTTPS MCP extension and dedicated bearer token | Review the generated extension manifest with your actual bridge URL. Install it through your host’s extension process and set its secret handle. |
| Other remote MCP clients | Streamable HTTP MCP with a dedicated bearer token | Enter the HTTPS MCP URL and store the bearer token in the client's secret settings. The client must support bearer authentication. |

Muse Code is a separate local CLI. Select **Muse Code** in the main agent list for its stdio setup. The cloud integrations here depend on the provider’s custom-connector access for your account.

## HTTPS bridge for Muse, Manus, IronClaw and remote MCP clients

For a device test, choose **Start temporary link**. Airlock downloads the pinned Cloudflare helper on first use, verifies the package checksum, and forwards only the agent bridge. It waits for Cloudflare to register a connection over HTTP/2, then checks the local listener and an expiring verification page at the public HTTPS URL. If the Mac cannot resolve the new hostname, open the verification URL on a different device and enter its eight-digit code in Airlock. Select **Verify from another device** at startup to go directly to that step. During verification the public link serves only that page. The owner has ten minutes and five attempts. After success the page disappears and the scoped connector and pairing routes become available. Networks must permit outbound TCP port 7844. The service requires neither your own domain nor a Cloudflare account. Cloudflare sees credentials and data that pass through the link. Your Mac must stay awake and online.

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

The bridge serves the public API schema and authenticated agent requests. Keep the owner URL, the owner's session fragment and the ordinary local MCP listener off the proxy. The proxy terminates TLS and can see credentials and released data. Disable request-body and authorization-header logging in that proxy. Locking the personal workspace blocks new calls. Pausing the bridge blocks HTTPS access for all cloud clients. Reopening the workspace restores approved connections within their original expiry and call budgets.

Muse can call REST tools from `/openapi.json`, including scoped memory reads and proposals, private computation, prepared actions, field-filtered reads and owner-assigned handoffs. Manus and the other MCP clients discover tools through MCP. Both transports enter the same scoped tool authorization and disclosure checks. Any text an agent receives, copies elsewhere or sends through its own tools is outside those checks.

## ChatGPT Secure MCP Tunnel

1. Have an OpenAI Platform tunnel ID, a restricted runtime key for that tunnel and the official `tunnel-client` executable on your Mac's PATH. The tunnel must be dedicated to this connection, with access limited to trusted users. Linking a shared tunnel or publishing its plugin extends the same Airlock grant to anyone who can invoke it.
2. In Airlock choose **ChatGPT → Create connection**. Run the displayed terminal command on your Mac. It prompts locally for the tunnel ID and runtime key and configures an independent stdio profile. The command contains only local paths. The profile uses one scoped token file, separate from any Dot or Codex grant.
3. Keep that process running and the personal workspace open. In ChatGPT, choose **Plugins → Add custom MCP server → Tunnel**, select the same dedicated tunnel, and choose **No authentication** for the upstream OAuth option. The OpenAI tunnel authorizes access to the private transport and Airlock authenticates each call over stdio with the connection token.
4. Privately install the plugin and request `privacy_status`. Check **Last tool call** in Airlock. Stop the process with Ctrl-C. Revoke the grant in Airlock to end access.

ChatGPT access depends on workspace plugin permissions and tunnel association. OpenAI requires the appropriate Tunnels Read and Use permissions to run or select a tunnel. Creating or editing one also requires Manage. A custom HTTPS adapter for ChatGPT OAuth is outside this version. Airlock does not store the runtime key. The official tunnel client receives it in the environment while running.

## Check your signed-in agent

Open **Privacy & connections → Cloud agents → Test a connection**. Start a test for the exact connection, ask the agent for its status code, then match the reply in Airlock. Each test status response contains only the code. For ChatGPT, connection help displays the tunnel setup command again when the local credential exists. [Connection tests and error recovery](CONNECTION_TESTS.md)

## Provider review and verification

Muse documents private user-created connectors and separate approval criteria for the public catalog. Manus documents adding custom MCP servers under the user's integrations. ChatGPT documents custom MCP plugins with workspace access controls. Public submission and organization-wide installation have their own provider requirements.

Protocol tests in this repository cover real loopback requests, MCP initialization, scoped REST calls, call limits, revocation, workspace locking, and tunnel command construction with a simulated runtime key. Account acceptance and authenticated use in a real Muse, Manus, IronClaw or ChatGPT session require the owner's account and reachable endpoint or associated tunnel.

- [Meta Muse custom connectors](https://www.meta.com/en-gb/help/superintelligence/1687253048996149/)
- [Meta Muse catalog guidelines](https://platform.muse.ai/docs)
- [Manus custom MCP servers](https://manus.im/docs/integrations/custom-mcp)
- [ChatGPT custom MCP servers](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
