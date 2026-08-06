# Single-Origin Deploy

One `uvicorn` process, one port, serves the API and both frontends. No nginx,
no Node process at runtime, no CORS (everything is same-origin).

## Routing map

| Path | Serves |
|---|---|
| `/` | bot-ui (end users) |
| `/admin` | admin-portal (admins) |
| `/api/*` | FastAPI routers (`health`, `ask`, `admin`) |
| `/bot/{any-id}` | bot-ui's chat page, for any bot id - see below |

`/api` composes from `app.include_router(router, prefix="/api")` in
`app/main.py` for all three routers - `admin.router`'s own internal
`prefix="/admin"` stacks on top, so its routes land at `/api/admin/...`. Both
frontends already build their requests as `NEXT_PUBLIC_API_BASE=/api` +
`/admin/bots` etc., so no frontend request-path code changed for this.

## How a bot created after the image was built still works

`bot-ui/src/app/bot/[botId]/page.tsx` can't enumerate real bot ids at build
time (they're created dynamically via the admin API), so it exports exactly
**one** synthetic static page via `generateStaticParams() { return [{ botId:
"_shell" }] }` - producing `out/bot/_shell/index.html`. That HTML references
the real JS bundle for the `[botId]` route; `botId` itself is read
**client-side**, off the actual browser URL, inside `ChatClient.tsx` (split
out from `page.tsx` because `generateStaticParams` requires a Server
Component file, and the actual chat UI is `"use client"`).

`app/main.py` has one explicit route, `GET /bot/{bot_id}`, that always returns
that same `_shell/index.html` file via `FileResponse` - registered before the
static mounts, so it wins for every `/bot/*` request regardless of whether the
id is one FastAPI has ever heard of. The browser loads the chat page, resolves
the real id from its own URL, and calls `/api/ask/{realBotId}`. Net effect:
adding a bot through the admin UI never requires rebuilding or redeploying
either frontend.

`admin-portal` needed no equivalent trick - it has zero dynamic route
segments, so every page is a real, finite, pre-built file and
`StaticFiles(html=True)` resolves deep-link refreshes (e.g. `/admin/usage`)
directly.

## Authorization is the boundary, not file-serving

Serving `/admin`'s static files does not gate access - that's normal for a
SPA. `require_admin` still sits on every `/api/admin/*` route exactly as
before; a non-admin who loads `/admin` gets a working page shell and then a
403 on every API call it makes. `can_access_bot`'s per-bot `allowed_groups`
check is equally untouched. Nothing about this change loosens auth - it only
changes how HTML/JS/CSS bytes reach the browser.

## Local development is unchanged

`admin-portal/next.config.ts` and `bot-ui/next.config.ts` set `output:
'export'` **only when `NODE_ENV=production`** (i.e. only during `next build`,
set automatically by the Next CLI). `next dev` still uses the old
`rewrites()` proxy to `localhost:8000` - Next.js disallows `rewrites()`
together with `output: 'export'` in both `next dev` and `next build`, so the
two modes can't share one config shape. Run each app with `npm run dev` and
the backend with `uvicorn`/Docker exactly as before; nothing here changes that
workflow.

## Docker build

`docker-compose.yml`'s build context moved from `ai-search-engine/` to the
**repo root**, since the Dockerfile now also needs `admin-portal/` and
`bot-ui/` (siblings of `ai-search-engine/`, not inside it). The Dockerfile is
multi-stage: a `node:20-slim` stage runs `npm ci && npm run build` for both
frontends, then a `python:3.12-slim` stage installs backend deps and copies
each frontend's `out/` into `app/static/admin` / `app/static/root`
(`Settings.admin_static_dir` / `root_static_dir`, `app/core/config.py`).
`worker` builds from the identical Dockerfile/context (cached, not rebuilt
twice) and only overrides its `command` - it never serves the static files it
also contains, same as before this change.

`main.py` only mounts a static directory if it actually exists, so a plain
local `uvicorn app.main:app` (no Docker, no frontend build) still runs the API
standalone - useful for backend-only local iteration.
