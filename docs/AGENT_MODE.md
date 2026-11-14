# Agent mode: a Claude agent orders through the gateway's MCP

In the chef app, the **Agent** toggle next to the chat input hands the request to a real Claude agent
(`claude-haiku-5-5` by default; `AIMO_AGENT_MODEL=claude-sonnet-5-5` to change). The agent runs on the server
(`gateway/chat_agent.py`) in a manual tool-use loop and talks to the gateway's own **`POST /mcp`** (Streamable HTTP)
with the kitchen's agent credential, so every call crosses the same MCP interface any external agent uses: the
playbook rails, signed offers, the gateway's rules and the named-human approval all apply unchanged. The model only
chooses the next tool; the gateway decides.

- Each MCP call and result streams into the chat as it happens (refusals show the gateway's own message and `fix`).
- There is no approve tool. When an OK is needed, the approval card appears in the thread; the approver's **OK, order it**
  uses her own credential (`POST /v1/approvals/{id}`), and the agent, waiting in `wait_for_update`, is woken and orders.
- Limits: 25 steps, 4,096 output tokens per step, 60,000 per run. Without `ANTHROPIC_API_KEY` the toggle is disabled
  with a one-line reason. The key never appears in any response or log; errors report only their class.
- API: `GET /v1/agent/status`, `POST /v1/agent/runs {text}`, `GET /v1/agent/runs/{id}/events?after=N&wait=20`
  (the kitchen's chef-app credential; agents and operations get 403).
- Tests: `tests/gateway/test_chat_agent.py` (a scripted client: the loop over /mcp, the step cap, the approval wake-up,
  no approve tool, no key → disabled).

## Live runs (14 Nov 2026, Claude Haiku 5.5, mock API prices)

| Request | What the agent did over MCP | Outcome |
|---|---|---|
| "I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability." | start_session → parse_request → recall (no gaps) → plan_basket → check_basket (AUTO) → render_cards → place_order with the cited offer and its own idempotency key | Ordered ORD-C6F2B3A8, 1,000 L Kaarna lactose-free milk, €1,370, Mon 16.11.; no approval needed |
| "I need 3,000 litres of lactose-free milk by Monday." | … check_basket (NEEDS_OK, over €2,000) → request_approval → wait_for_update ×2; Laura pressed **OK, order it** → approval.decided → place_order | Ordered ORD-0133023A, €4,110, approved by Laura Virtanen |

Screenshots: `docs/screenshots/v2/v5-agent-1280-dark.png`, `v5-agent-390-light.png` (`scripts/screenshots_agent.py`).
