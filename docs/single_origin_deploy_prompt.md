# Claude Code task — Single-origin build: FastAPI serves the UI + API on one port

Paste into Claude Code, running inside the `ai_shared_engine` repo. Goal: collapse
the stack so **one FastAPI process on one port** serves both the built frontend(s) as
static files AND the `/api`, replacing the two separate Next.js server processes.

---

## Context

Today: FastAPI backend (`api`, port 8000) + a `worker`, Postgres, Qdrant, plus two
**Next.js** apps run as their own Node processes — `admin-portal` and `bot-ui` — with
Nginx routing `/` → a frontend and `/api/` → the backend.

We want a **single-origin monolith**: build each Next.js app to static assets
(`output: 'export'`), and have **FastAPI serve those static files + the API on one
port**. Benefits: no CORS, one container, ~0.5–0.8 GB less RAM (no Node servers at
runtime). Authorization is unchanged and stays the real boundary.

## Routing decision (the one knob — confirm before building)

Default layout, all on the same origin/port:
- `/`         → **bot-ui** (end users)
- `/admin`    → **admin-portal** (admins; API-gated by the admin group)
- `/api/...`  → the FastAPI backend
- `/bot/{id}` → bot-ui SPA (must work for bots added *after* build — see Design §2)

If instead the admin portal should be at `/` (per the earlier "admin at root" task),
swap: admin at `/`, bot-ui at `/chat`. Implement the default but keep the base paths
in a single obvious place so it's a one-line change.

## Before you start (read, don't assume)

- `admin-portal/next.config.*`, `bot-ui/next.config.*` — current config; whether
  either uses server-only features (server actions, route handlers, middleware,
  `next/image` with the default loader) that block static export.
- `admin-portal/src/lib/api.ts`, `bot-ui/src/lib/api.ts`, and the MSAL config
  (`src/lib/msal.ts`) — how `NEXT_PUBLIC_API_BASE` and the redirect URI are used.
- `bot-ui/src/app/bot/[botId]/page.tsx` — the dynamic route; how `botId` is read.
- `app/main.py` — how routers (`ask`, `admin`, `health`) are mounted today; the
  backend base URL assumption (Nginx currently strips `/api`).
- `ai-search-engine/docker/` — Dockerfile + compose (you'll produce a single image).

**If a frontend cannot be statically exported cleanly, STOP and report exactly which
feature blocks it and the minimal change to remove it — do not silently degrade.**

## Design to implement

### 1. Export each Next.js app to static

In each app's `next.config`:
- `output: 'export'`, `images: { unoptimized: true }`, `trailingSlash: true`.
- `NEXT_PUBLIC_API_BASE=/api` (same origin — drop any absolute backend URL / CORS).
- For the app served under a sub-path, set `basePath` + `assetPrefix` accordingly
  (e.g. admin-portal `basePath: '/admin'`). The root app has no basePath.
- MSAL `redirectUri` = the current public origin (+ basePath). The public origin is
  unchanged, so the existing Entra redirect URI still matches — just confirm both
  apps compute it from `window.location.origin`.

`npm ci && npm run build` in each app must produce a static export dir (Next 16
emits to `out/`). Verify no server-only output is required at runtime.

### 2. Make `/bot/[botId]` survive bots added *after* build (critical)

Bots are created dynamically (YAML), so the export can't know all ids at build.
Implement so that:
- the build **succeeds** (provide `generateStaticParams` — current bot ids, or a
  minimal safe set), AND
- direct-navigating to `/bot/<a-bot-added-later>` still loads the chat UI, by having
  **FastAPI serve the bot-ui app shell (its `index`/`[botId]` HTML) for any
  unmatched `/bot/*` path** (SPA fallback), with the page reading `botId` from the
  URL client-side and calling `/api/ask/{botId}`.
Pick whichever Next 16 mechanism achieves this cleanly; the requirement is
"new bot ⇒ no frontend rebuild needed."

### 3. FastAPI serves API + static + SPA fallback (order matters)

In `app/main.py`, in this precedence:
1. **API first** — mount the existing routers under **`/api`** (add an `/api` prefix
   or mount an API sub-app at `/api`) so `NEXT_PUBLIC_API_BASE=/api` hits them
   same-origin. (Nginx no longer strips `/api`; the app owns that prefix now.)
2. **Static assets** — `StaticFiles` for each export dir (e.g. bot-ui `out/` at `/`,
   admin-portal `out/` at `/admin`), including `_next`/asset paths.
3. **SPA fallback** — a catch-all `GET` that returns the correct app's `index.html`
   for client-side deep links (`/bot/hr`, `/admin/usage` on refresh) so a hard reload
   doesn't 404. `/api/*` must never fall through to this.

### 4. Authorization stays the boundary (do not weaken)

Serving `/admin` static files does not restrict them — that's expected for a SPA.
Keep `require_admin` on all `/admin/*` API routes and per-bot `allowed_groups` exactly
as-is; a non-admin loading `/admin` simply gets 403 on every admin API call.
Optionally add a client-side redirect for non-admins as UX, but it is NOT the
security control. Do not remove or loosen any existing API authz.

### 5. One image, one process

Multi-stage `Dockerfile`:
- Stage 1 (node): build both apps → their `out/` dirs.
- Stage 2 (python): install backend deps; COPY each `out/` into the app (e.g.
  `app/static/root` and `app/static/admin`); run **only** `uvicorn app.main:app`.
Update `docker-compose`: **remove the two frontend services**; the `api` service now
serves everything on its one port. `worker`, `postgres`, `qdrant` unchanged (named
volumes untouched). Result: no Node process at runtime.

## Acceptance criteria (tests)

1. `GET /` returns the bot-ui page; `GET /admin` returns the admin portal page
   (or the swapped layout if configured).
2. `GET /api/health` → `{"status":"ok"}`; `GET /api/ask/hr` unauthenticated → **401**
   (route intact + gated), not 404. Admin endpoints still `require_admin`.
3. **Deep-link refresh works:** `GET /bot/hr` and `GET /admin/usage` return the app
   shell (SPA fallback), not 404.
4. **New bot needs no rebuild:** create a bot via the admin API, then
   `GET /bot/<newid>` still loads the chat UI and can call `/api/ask/<newid>`.
5. MSAL sign-in works from the single origin on both `/` and `/admin`; redirect URI
   unchanged.
6. Runtime has **no Node/Next server process** — only uvicorn; one container serves
   UI + API.
7. Regression: backend business logic, the query layer, the worker, and DB/Qdrant
   data are unchanged; `chat_logs`/`usage_logs` still written.
8. If static export required a config/code change to a frontend, it's documented.

## Non-goals

- Do NOT merge the two frontends into one codebase; keep them as two apps served
  under one origin.
- Do NOT change backend business logic, the RAG/query layer, sync, or DB schema.
- Do NOT weaken any authorization.

## Deliverables

- `next.config` changes + any minimal fixes to make each app statically exportable
  (with the `/bot/[botId]` handling in §2).
- `app/main.py` API-under-`/api` + static mounts + SPA fallback.
- Multi-stage `Dockerfile` + slimmed `docker-compose` (frontend services removed).
- A short `docs/SINGLE_ORIGIN_DEPLOY.md`: the routing map, how the SPA fallback keeps
  dynamic bots working, and the note that authz (not file-serving) is the boundary.
- Tests for the acceptance criteria; small commits; a summary of any repo deltas —
  especially anything that blocked static export.
```
