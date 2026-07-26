# Running Everything Manually

This is the manual, step-by-step version of what Claude Code has been running
for you in this session: the backend (FastAPI + Postgres + Qdrant, via
Docker), and the two Next.js frontends (`admin-portal`, `bot-ui`).

Directory layout referenced below (paths are relative to the repo root,
`ai-search-engine & admin portal/`):

- `ai-search-engine/` - the backend
- `admin-portal/` - Next.js admin UI (port 3000)
- `bot-ui/` - Next.js end-user chat UI (port 3001)

## 0. One-time environment note (Windows only)

This repo's parent folder name contains an `&` (`ai-search-engine & admin
portal`). On Windows, `npm.cmd` / `npx.cmd` are batch-file shims that get
their working directory wrong when the path contains `&`, so plain `npm
install` / `npm run dev` / `npx <tool>` fail with errors like:

```
'admin' is not recognized as an internal or external command...
Error: Cannot find module 'C:\Users\<you>\Downloads\next\dist\bin\next'
```

This happens in both PowerShell and Git Bash - it's not shell-specific, it's
the `.cmd` wrapper itself. Two ways around it:

- **Preferred long-term fix:** rename the parent folder to remove the `&`
  (e.g. `ai-search-engine-admin-portal`). Once there's no `&` in the path,
  `npm install` / `npm run dev` / `npx` all work normally.
- **Workaround without renaming:** invoke the underlying binary via `node`
  directly instead of through `npm`/`npx` (shown below for `next dev`). This
  is what every command in this doc uses, so it works either way.

`npm install` itself doesn't have a direct-`node` equivalent - if you ever
need to (re)install dependencies and hit this, temporarily rename the folder,
run `npm install`, then rename it back (or just fix the folder name for good).

## 1. Start the backend

```bash
cd ai-search-engine/docker
docker compose up --build -d
```

This starts 4 containers: `postgres`, `qdrant`, `api` (FastAPI on port 8000),
and `worker` (the SharePoint sync scheduler). Check it came up:

```bash
curl http://localhost:8000/health   # {"status":"ok"}
curl http://localhost:8000/ready    # {"status":"ready","bots":["audit","hr","it"]}
```

**First-time only** (already done once for this repo - the named Docker
volumes persist the data, so you normally won't need to repeat this): if
`docker compose ps` shows the containers but Postgres has no tables yet, or
Qdrant has no collections, run:

```bash
docker compose exec api python -m scripts.init_db
docker compose exec api python -m scripts.create_collection hr
```

By default `AUTH_ENABLED` is `true` (see `ai-search-engine/.env`), so
`/admin/*` and `/ask/*` require a real Entra Bearer token - hitting them
without one correctly returns `401`. That's expected; sign in through the
frontend to get a token.

### Stop the backend

```bash
cd ai-search-engine/docker
docker compose down
```

`down` removes the containers but **not** the named volumes (`pgdata`,
`qdrantdata`), so chat history, usage logs, and indexed vectors survive a
stop/start cycle. Add `-v` only if you deliberately want to wipe that data.

## 2. Run admin-portal (port 3000)

One-time setup, if `node_modules` isn't there yet:

```bash
cd admin-portal
npm install   # see the folder-name note above if this fails
```

`.env.local` already has `NEXT_PUBLIC_API_BASE=/api`, `NEXT_PUBLIC_USE_MOCKS=false`,
and the Entra dev-tenant values, and `next.config.ts` already has the
`/api/:path*` -> `http://localhost:8000/:path*` rewrite. Start it:

```bash
cd admin-portal
node ./node_modules/next/dist/bin/next dev -p 3000
```

Open http://localhost:3000.

## 3. Run bot-ui (port 3001)

Same pattern:

```bash
cd bot-ui
npm install   # if needed
node ./node_modules/next/dist/bin/next dev -p 3001
```

Open http://localhost:3001 (or navigate straight to a bot, e.g.
http://localhost:3001/bot/hr).

> Note: the two apps share one Entra login app registration, which only has
> `http://localhost:3000` registered as a redirect URI. Running bot-ui on
> a different port (3001) is fine for local side-by-side testing, but for a
> real interactive Microsoft sign-in on bot-ui specifically, run it on 3000
> instead (stop admin-portal first, since only one process can bind a port).

### Stop a frontend

Each `next dev` process keeps running in the foreground of whatever terminal
started it - `Ctrl+C` there stops it. If you started it in the background and
lost track of it, find and kill whatever is listening on the port (PowerShell):

```powershell
$conn = Get-NetTCPConnection -LocalPort 3000 -State Listen
Stop-Process -Id $conn.OwningProcess -Force
```

(Swap `3000` for `3001` for bot-ui.)

## 4. Troubleshooting

- **401 on every admin/ask call before you've signed in** - expected; the
  backend enforces real Entra auth. Sign in via the app's "Sign In" button.
- **Stuck on a blank "Loading…" screen** - this is the auth gate waiting for
  `inProgress === "none"` from MSAL (see `src/components/Providers.tsx` in
  each app). It should clear in well under a second; if it doesn't, check the
  browser console for MSAL errors.
- **A route 404s that should exist** (seen once with bot-ui's `/` and
  `/bot/hr` after several rapid restarts) - Turbopack's dev cache can get
  stale. Stop the dev server, delete the app's `.next` folder, restart:
  ```bash
  cd bot-ui   # or admin-portal
  rm -rf .next
  node ./node_modules/next/dist/bin/next dev -p 3001
  ```
- **`docker compose` says a port is already in use** - something else (maybe
  a previous run) is still bound to 8000/5432/6343. `docker compose ps -a`
  and `docker compose down` first.
