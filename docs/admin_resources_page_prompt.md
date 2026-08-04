# Claude Code task — Admin "Resources" page: per-bot storage + system RAM/CPU + per-bot activity

Paste everything below into Claude Code, running inside the `ai_shared_engine` repo.

---

## Context

The admin portal (Next.js) has pages for Dashboard, Bots, Usage, Cost, Users,
History, Logs — all calling the backend ONLY through `admin-portal/src/lib/api.ts`,
with a `NEXT_PUBLIC_USE_MOCKS` toggle and Recharts for charts. Backend admin routes
live in `app/api/routes/admin.py`, all gated by `require_admin`.

We want a new page showing, per bot, how much **storage** it uses, plus **system
RAM/CPU/disk**, once deployed on the VM.

**Important design truth to respect (don't fake it):**
- **Storage attributes cleanly to a bot** — each bot owns its Qdrant collection, and
  list bots own their Postgres tables. These numbers are exact and real.
- **RAM/CPU do NOT attribute to a bot.** All bots share one `api` container and one
  `worker` container, so there is no OS-level "this bot uses X MB." Therefore:
  - report RAM/CPU/disk at the **container/system level** (accurate), and
  - report a **per-bot activity share** (requests/tokens/cost/sync time) explicitly
    labeled as a *proxy for load*, NOT as literal per-bot RAM.
  Do not invent a "RAM per bot" column.

## Objective

Add a `/resources` admin page (nav label e.g. "System") with three sections —
Storage by bot (exact), System resources (container/system level), and Activity by
bot (labeled load proxy) — backed by new `require_admin` endpoints, wired only
through `api.ts`, with mock data for `USE_MOCKS`, and degrading gracefully on the VM.

## Before you start (read, don't assume)

- `admin-portal/src/components/layout/Sidebar.tsx` — how nav links/pages are declared.
- An existing dashboard page (e.g. `src/app/usage/page.tsx`) and `src/lib/api.ts` —
  the typed-method + mock pattern, time-filter handling, camelCase contract, the
  403 `admin-forbidden` handling.
- `app/api/routes/admin.py` — existing endpoints, especially `/admin/index-status`
  (already returns per-bot doc/chunk counts from Qdrant) and the usage/cost-by-bot
  aggregations; reuse these rather than duplicating.
- `app/vectorstore/qdrant_store.py` (`index_stats` / collection info) and the Qdrant
  client — what it exposes for a collection (points/vectors count; size/segments if available).
- `app/db/` — the `list_tables` registry (bot_id → table_name, row_count), `session.py`,
  and the `chat_logs`/`usage_logs`/`sync_state` models.
- `app/bots/registry.py` / schema — `content_type`, so library vs list bots are handled.

Follow the code where it differs and note deltas.

## Design to implement

### Endpoint 1 — `GET /admin/storage/by-bot` (exact, per bot)

For each bot return:
- **Vector (Qdrant):** collection name, `points` (vector count), and `size_bytes`
  if the client exposes it — otherwise an **estimate** (points × vector_dim × 4 +
  overhead) clearly flagged `size_is_estimate: true`. Reuse `index_status`/`index_stats`.
- **Structured (Postgres, list bots only):** per list table from the `list_tables`
  registry — `{ list_name, table_name, rows, size_bytes }` via
  `pg_total_relation_size('"<table>"')` — plus a `structured_total_bytes`.
- **Logs:** per-bot `chat_logs` and `usage_logs` **row counts** (not bytes — those
  tables are shared, so don't claim per-bot bytes for them; row counts are the honest
  per-bot number).

Shape (camelCase for the frontend):
```
[{ botId, name, contentType,
   vectorPoints, vectorSizeBytes, vectorSizeIsEstimate,
   structuredTables: [{ listName, rows, sizeBytes }], structuredTotalBytes,
   chatRows, usageRows, totalStorageBytes }]
```
`totalStorageBytes` = vector + structured (exclude the shared-log row counts).

### Endpoint 2 — `GET /admin/resources` (container/system level)

Return real system numbers, **cgroup-aware first** (read the container's cgroup
memory limit/usage where available), falling back to `psutil`, and clearly stating
the source:
```
{ memory: { usedBytes, limitBytes, pct },
  cpu:    { pct },
  disk:   { totalBytes, usedBytes, freeBytes, pct },     // the data volume/path
  process:{ rssBytes, cpuPct },                           // this api process
  containers: { api, worker, postgres, qdrant } | null,   // per-service, IF available
  containersAvailable: bool,
  source: "cgroup" | "psutil",
  note: string }                                          // e.g. why containers is null
```
- **No Docker dependency required for the core numbers.** Process + system memory/CPU/disk
  come from cgroup files / `psutil` inside the container — works on the VM immediately.
- **Per-container breakdown is best-effort:** only if the Docker socket is mounted /
  a stats source is reachable. If not, set `containers: null`,
  `containersAvailable: false`, and a `note` like "per-container stats need Docker
  socket access on the VM." Never error because Docker isn't reachable.
- Add `psutil` to `requirements.txt` if not present (small, standard). Do NOT shell
  out to `docker` unless the socket is clearly available and access is safe.
- **Security:** return only metrics — never env vars, secrets, file paths beyond the
  monitored data path, or process command lines.

### Endpoint 3 — `GET /admin/activity/by-bot?from&to` (the honest load proxy)

Per bot over the selected period: `requests`, `tokens`, `cost`, `avgResponseTimeMs`,
plus `%share` of requests/tokens/cost, and last-sync info from `sync_state`
(`lastRunAt`, `lastStatus`, and sync duration if recorded). Reuse existing
usage/cost-by-bot aggregations where possible; add only what's missing. This is the
"which bot is doing the most work" view — the defensible stand-in for per-bot load.

Put reusable logic in a small module, e.g. `app/monitoring/storage.py` (bot storage)
and `app/monitoring/resources.py` (cgroup/psutil/docker reader); keep the route
handlers thin.

### Frontend — `/resources` page + one nav link

Add `admin-portal/src/app/resources/page.tsx` and a Sidebar entry (match the existing
pattern; a Lucide icon like `HardDrive` or `Activity`). Three sections:

1. **Storage by bot** — a table and a stacked bar chart (Recharts) of vector vs
   structured bytes per bot; format bytes human-readably; mark estimated vector sizes
   with a small "est." badge/tooltip. Exact, no time filter.
2. **System resources** — cards/gauges for memory used/limit (+ %), CPU %, disk
   used/free (+ %), and the api process RSS. If `containersAvailable`, show a small
   per-service (api/worker/postgres/qdrant) breakdown; otherwise render a muted
   "Per-container breakdown unavailable — needs Docker stats access on the VM" note.
3. **Activity by bot** — a table/bar of requests/tokens/cost share for the selected
   period (reuse the existing time-filter component). **Include a visible caption:**
   "Activity share is a proxy for load. All bots share one engine, so per-bot RAM
   isn't directly measurable — this shows each bot's share of the work." Do not label
   anything here as RAM/CPU per bot.

All three fetch via new typed methods in `api.ts` with realistic **mock data** under
`USE_MOCKS`. No page component calls `fetch()` directly.

## Guardrails / constraints

- All new endpoints are under the existing `require_admin`-gated admin router.
- Backend calls from the UI go **only** through `api.ts` (typed methods + mocks) —
  the "one file to wire" rule the other pages follow.
- Graceful degradation everywhere: a missing Docker socket, an empty registry, a bot
  with no collection yet, or a Qdrant/DB hiccup must yield partial data + a flag, not
  a 500 or a broken page.
- Performance: `pg_total_relation_size` and Qdrant collection info are a bit heavy —
  fetch on page mount only (not on every dashboard load), and consider a short
  in-memory TTL cache (e.g. 30–60s) on the storage/resources endpoints.
- Estimates are always labeled as estimates; exact values are not.
- No secrets or host internals leaked by `/admin/resources`.

## Acceptance criteria (tests + manual)

1. `/resources` is reachable from the sidebar and loads without affecting other pages.
2. **Storage by bot** is accurate: a list bot shows its Qdrant points + each list
   table's real `pg_total_relation_size` + totals; a library bot shows vector storage
   + log row counts and an empty structured section. Totals add up.
3. **System resources** shows real memory/CPU/disk from cgroup/psutil on the VM; with
   no Docker socket, `containersAvailable:false` + the muted note (no error).
4. **Activity by bot** shows correct per-bot request/token/cost shares for the period
   and is captioned as a load proxy (no "RAM per bot" anywhere).
5. `USE_MOCKS=true` renders all three sections with realistic data, no backend needed.
6. All three endpoints require admin (401/403 → existing forbidden overlay).
7. `/admin/resources` leaks no env/secret/path data (assert in a test).
8. Regression: existing pages and endpoints unchanged; heavy queries run on mount only.

## Non-goals

- No true per-bot process isolation (do NOT split bots into separate processes/containers).
- No new time-series/metrics database or external monitoring stack — point-in-time reads.
- No changes to Half 1/Half 2 storage, sync, or the query layer.

## Deliverables

- `app/monitoring/storage.py` + `app/monitoring/resources.py`, the three admin
  endpoints, `psutil` added if needed.
- `api.ts` typed methods + types + mocks; the `/resources` page + Sidebar link.
- A short doc (e.g. `docs/ADMIN_RESOURCES_PAGE.md`) stating what's exact (storage),
  what's system-level (RAM/CPU/disk), what's a proxy (per-bot activity), and the one
  infra item (Docker socket access for per-container stats on the VM).
- Tests for the acceptance criteria; small, reviewable commits; a summary of any deltas.
