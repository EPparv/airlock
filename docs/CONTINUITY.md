# Check that Airlock actually remembers

These steps test the installed app with your real AI clients. Automated tests use fictional records and exercise Airlock's actual store, permissions and retrieval. They do not establish model quality or native ChatGPT/Claude parity.

1. In **Add context**, copy the new transfer prompt. Paste it into the source AI and review the resulting import. The prompt asks for accessible sources, dates, corrections, ongoing work, complete workflows and coverage gaps. It cannot recover unavailable chats.
2. In **Shared memory**, pin up to six short core records, such as communication preferences and enduring background. Set each agent's selected records and excerpt permission. Private, retired or stale records remain unavailable even if pinned. Reimporting an identical record marked `[CORE]` pins the existing record; it does not duplicate it. Manage these pins in Shared memory.
3. Start a new conversation in your connected AI. Ask a natural question requiring your background. Check **Last context request** in Airlock and inspect the AI's tool result. A connected badge alone proves no recall. Explicitly request Airlock context if the client does not call it.
4. Ask about a detailed project and its complete workflow. The AI should follow `next_query` when more results or parts are needed. Questions with no lexical overlap can still miss non-core facts; repeat with the project name or aliases, or ask for the available context. A miss is not proof that Airlock lacks the fact.
5. Correct an imported fact in Shared memory. Ask the same question in a fresh conversation and a second authorized client. Both should use the correction on their next context request. Linked files must be edited at their original source. Already disclosed text cannot be recalled from a client's chat.
6. Retire an outdated record. It and notes derived from it should disappear from subsequent requests. Restore it to make it eligible again. New approved derived notes are also withheld when their recorded source text changes; older notes created before this release have no retrospective source hash guarantee.
7. Enable **Allow memory proposals**, then tell the AI an explicit durable preference or project update. Ask it to propose the memory. Verify it is pending and absent from active recall; approve it, include it in another scoped agent's selected records, then ask that agent about it. Airlock does not watch hidden chats or save every conversation automatically.
8. Quit and reopen Airlock and the AI. Repeat the core preference and project questions. Check the renewed context request time. Expired connections or exhausted call budgets must be renewed through the existing connection controls.

An honest pass means the client requested current context, received authorized facts, and used them correctly. Treat a plausible answer without a context request, a guessed completion, an ignored correction, or leakage outside the selected scope as a failure.

## Implementation limits

- The prompt is an import aid, not a replacement for a model, tools, account history or native app features.
- Core profile inclusion and pagination apply to automatic and scoped context requests. The legacy reviewed-excerpt mode still returns only its explicitly approved views.
- Retrieval is deterministic and local. No embedding service or additional AI installation is required. More complex semantic recall remains future work.
- Paging is bound to the requesting connection and its current authorized content; pages expire after 30 minutes and fail if content or permission changes. The AI must repeat the original query after such a change.
- New memory proposals need owner approval. Approved additions do not silently broaden another scoped agent's access.
- MCP instructions request context refresh but cannot enforce it inside another vendor's app. The visible request timestamp measures a successful retrieval, not whether the host model used it correctly.

Run the focused regressions with `python -m pytest -q tests/test_continuity.py`. They cover encrypted restart, two clients, core recall on unrelated queries, full workflows, pagination, scope isolation, private records, corrections, derived-note staleness, owner-only controls, duplicate imports, revision changes and cursor expiry/revocation.
