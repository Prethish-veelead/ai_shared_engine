# API Contract — Admin Portal ↔ Backend

This is the glue between the two apps. Antigravity designs the admin UI to this
contract; Claude Code wires the UI to these endpoints. All admin calls go to
base URL `/api` (Nginx proxies `/api` → FastAPI).

> Auth: once Entra ID is added, every admin call sends
> `Authorization: Bearer <token>`. Until then, endpoints are open on localhost.

---

## Endpoints that EXIST today (ready to wire)

### `GET /api/admin/bots`
List all bots.
Response: `[{ "id": "hr", "name": "HR Assistant", "route": "/ask/hr", "enabled": true }]`

### `POST /api/admin/bots/reload`
Re-read the YAML bot configs (after adding/editing a bot file).
Response: `{ "reloaded": 3 }`

### `GET /api/admin/chat-history`
Query params: `bot_id?`, `user_id?`, `keyword?`, `limit?` (default 100).
Response: `[{ "id", "bot_id", "user_id", "question", "answer",
"total_tokens", "cost_usd", "response_time_ms", "created_at" }]`

### `GET /api/admin/cost/by-bot`
Response: `[{ "bot_id", "tokens", "cost", "requests" }]`

### `GET /api/admin/cost/by-model`
Response: `[{ "model", "cost", "tokens" }]`

### `POST /api/ask/{bot_id}` (the chatbot endpoint, for reference)
Body: `{ "question": "...", "user_id": "...", "user_email": "..." }`
Response: `{ "answer", "citations": [...], "model", "total_tokens",
"cost_usd", "response_time_ms" }`

### `GET /api/health` · `GET /api/ready`
Health checks. `/ready` also returns the list of loaded bot ids.

---

## Endpoints (NOW BUILT — all live in the backend)

These were previously "to ADD" and are now implemented and tested. Design the
UI to these shapes. All support the time filters below via `period` or
`start`/`end` query params.

### Bot management (CRUD)
- `POST /api/admin/bots` — create a bot (writes a new YAML).
- `PUT /api/admin/bots/{bot_id}` — edit a bot.
- `PATCH /api/admin/bots/{bot_id}` — enable/disable.
- `DELETE /api/admin/bots/{bot_id}` — delete a bot.
- `POST /api/admin/bots/{bot_id}/reindex` — force re-index.

### Usage dashboard
- `GET /api/admin/usage/summary?bot_id&from&to&model`
  → `{ total_requests, prompt_tokens, completion_tokens, total_tokens,
  estimated_cost, avg_response_time_ms, active_users, documents_indexed,
  index_size }`
- `GET /api/admin/usage/trend?bot_id&granularity=day|week|month`
  → `[{ period, requests, tokens, cost }]`

### Cost dashboard
- `GET /api/admin/cost/summary?bot_id&from&to`
  → `{ total_cost, embedding_cost, llm_cost }`
- `GET /api/admin/cost/by-user?bot_id&from&to`
  → `[{ user_id, cost, tokens, requests }]`

### User analytics
- `GET /api/admin/users?bot_id&from&to`
  → `[{ user_id, email, last_login, questions_asked, tokens_used }]`

### Logs & monitoring
- `GET /api/admin/logs?type=error|sync|auth|ai|indexing&from&to`
  → `[{ timestamp, type, bot_id, message }]`

---

## Time filters (all dashboards should support)

Today · Yesterday · Last 7 days · Last 30 days · Monthly · Custom range.
Pass as `from` / `to` ISO date query params.

## Rule for the frontend

Put **every** backend call in one file (`admin-portal/src/lib/api.ts`). For
endpoints not built yet, return realistic mock data from that same file with a
clear `// TODO: real endpoint` marker. That way, when Claude Code wires things,
it changes only that one file — the UI never changes.
