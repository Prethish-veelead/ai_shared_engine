# Running Everything

Single-origin deploy (see `docs/SINGLE_ORIGIN_DEPLOY.md`): one Docker image
serves the backend AND both frontends on **one port**. You do not need to run
`admin-portal`/`bot-ui` as separate processes to use the app - that's only
for active frontend development (see section 3).

## 1. Start everything

```bash
cd ai-search-engine/docker
docker compose up --build -d
```

This builds one image (backend + both frontends compiled into it) and starts
4 containers: `postgres`, `qdrant`, `api`, `worker` (the SharePoint sync
scheduler). `--build` picks up any code change; drop it for a plain restart
of already-built images.

Open:

- **http://localhost:8000/** - bot-ui (end-user chat)
- **http://localhost:8000/admin** - admin-portal
- **http://localhost:8000/api/health** - backend health check

```bash
curl http://localhost:8000/api/health   # {"status":"ok"}
curl http://localhost:8000/api/ready    # {"status":"ready","bots":[...]}
```

`/api/admin/*` and `/api/ask/*` require a real Entra Bearer token - hitting
them directly without one correctly returns `401`. Sign in through the
frontend ("Sign In" button) to get one; the browser handles the token after
that.

**First-time only** (the named Docker volumes persist data afterward, so you
normally won't repeat this): if Postgres has no tables yet or Qdrant has no
collections -

```bash
docker compose exec api python -m scripts.init_db
docker compose exec api python -m scripts.create_collection hr
```

### Stop

```bash
cd ai-search-engine/docker
docker compose down
```

`down` removes the containers but **not** the named volumes (`pgdata`,
`qdrantdata`) - chat history, usage logs, and indexed vectors survive a
stop/start cycle. Add `-v` only if you deliberately want to wipe that data.

### Rebuild after a code change

```bash
cd ai-search-engine/docker
docker compose build api
docker compose up -d api
```

(`worker` shares the same image - rebuild/restart it too if the change
affects sync behavior: `docker compose build worker && docker compose up -d worker`.)

## 2. One-time environment note (Windows only)

This repo's parent folder name contains an `&` (`ai-search-engine & admin
portal`). On Windows, `npm.cmd`/`npx.cmd` are batch-file shims that get their
working directory wrong when the path contains `&`, so plain `npm install` /
`npm run dev` / `npx <tool>` fail with errors like:

```
'admin' is not recognized as an internal or external command...
Error: Cannot find module 'C:\Users\<you>\Downloads\next\dist\bin\next'
```

This happens in both PowerShell and Git Bash - it's the `.cmd` wrapper
itself, not a shell issue. Two ways around it:

- **Preferred long-term fix:** rename the parent folder to remove the `&`
  (e.g. `ai-search-engine-admin-portal`).
- **Workaround without renaming:** invoke the underlying binary via `node`
  directly instead of through `npm`/`npx` (used throughout section 3 below).
  `npm install` itself has no direct-`node` equivalent - if you need to
  (re)install dependencies and hit this, temporarily rename the folder, run
  `npm install`, then rename it back.
- `docker compose` itself is unaffected by the `&` - it doesn't go through
  the npm/npx shims, so section 1 above works regardless.

## 3. Frontend development (hot reload)

Only needed if you're actively editing `admin-portal`/`bot-ui` source and
want instant hot-reload instead of rebuilding the Docker image on every
change - the container from section 1 must still be running, since these
dev servers proxy `/api/*` calls to it.

One-time setup, if `node_modules` isn't there yet:

```bash
cd admin-portal   # or bot-ui
npm install
```

Start it (each app's `next.config.ts` already proxies `/api/:path*` to
`http://localhost:8000` in dev mode - no `.env` changes needed):

```bash
cd admin-portal
node ./node_modules/next/dist/bin/next dev -p 3000
```

```bash
cd bot-ui
node ./node_modules/next/dist/bin/next dev -p 3001
```

Open http://localhost:3000 (admin-portal) / http://localhost:3001 (bot-ui,
or straight to a bot, e.g. http://localhost:3001/bot/hr).

> Both apps share one Entra login app registration, which only has
> `http://localhost:3000` registered as a redirect URI. Running bot-ui on a
> different port (3001) is fine for side-by-side local testing, but for a
> real interactive Microsoft sign-in on bot-ui specifically, run it on 3000
> instead (stop admin-portal first - only one process can bind a port).

### Stop a frontend dev server

Each `next dev` process runs in the foreground of whatever terminal started
it - `Ctrl+C` there stops it. If you started it in the background and lost
track of it, find and kill whatever is listening on the port (PowerShell):

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
- **A route 404s that should exist** (seen on bot-ui's `/` and `/bot/hr`
  after several rapid `next dev` restarts) - Turbopack's dev cache can get
  stale. Stop the dev server, delete the app's `.next` folder, restart:
  ```bash
  cd bot-ui   # or admin-portal
  rm -rf .next
  node ./node_modules/next/dist/bin/next dev -p 3001
  ```
- **`docker compose` says a port is already in use** - something else (maybe
  a previous run) is still bound to 8000/5432/6343. `docker compose ps -a`
  and `docker compose down` first.
- **Editing bot-ui/admin-portal source but the running app at :8000 doesn't
  reflect it** - the container serves a *built* static export, not your
  working tree; either rebuild (`docker compose build api && docker compose
  up -d api`) or use section 3's hot-reload dev servers instead while
  iterating.
