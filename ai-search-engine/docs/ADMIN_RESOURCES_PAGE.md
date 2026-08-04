# Admin Resources Page ("System")

A `/resources` admin page showing per-bot storage, host resource usage, and
per-bot activity. Three sections, three different honesty levels - the whole
point of this feature is not blurring them together.

## What's exact: Storage by bot

Each bot cleanly owns its own Qdrant collection and, for list bots, its own
Postgres tables - so these numbers are real:

- **Vector points** (`vectorPoints`): exact, from `VectorStore.index_stats()`.
- **Vector byte size** (`vectorSizeBytes`): an **estimate**
  (`points x embedding_dim x 4 bytes + a fixed per-point overhead`), always
  returned with `vectorSizeIsEstimate: true`. Qdrant's client doesn't expose
  real on-disk size for these collections, so this is the honest label for
  it - never presented as exact.
- **Structured tables** (list bots only): exact, via
  `pg_total_relation_size()` per table from the `list_tables` registry -
  includes indexes and TOAST data, not just raw row bytes.
- **Chat/usage row counts**: exact row counts, not bytes -
  `chat_logs`/`usage_logs` are shared across every bot, so claiming a
  per-bot BYTE size for a slice of a shared table would be fabricated
  precision. Row counts are the honest per-bot number here.

Backend: `app/monitoring/storage.py`, `GET /admin/storage/by-bot`. Cached
in-process for 45s (a full pass does one Qdrant stats call per bot plus one
`pg_total_relation_size` per list table - fine on page load, wasteful on
every poll).

## What's real but NOT per-bot: System resources

All bots share one `api` container and one `worker` container - there is no
OS-level "this bot used X MB of RAM." `GET /admin/resources` reports real
memory/CPU/disk, but only at the container/system level:

- Reads cgroup files directly first (`/sys/fs/cgroup/memory.current` +
  `memory.max`, v2; falls back to the v1 paths) - accurate for the actual
  container, no extra dependency needed.
- Falls back to `psutil`'s host-level view when cgroup files aren't usable -
  either running outside a container, or (as observed live in this
  deployment) the container has no memory limit configured at all
  (`memory.max` reads `"max"`, i.e. unlimited), in which case reporting
  "0% of unlimited" would be meaningless, so it falls back to the whole
  VM's view instead. `source` in the response tells you which one happened.
- **Per-container breakdown needs the Docker socket mounted** into this
  container, which `docker-compose.yml` does not do. `containers` is
  always `null` and `containersAvailable` is always `false` on this
  deployment, with a `note` explaining why - never an error just because
  Docker isn't reachable. Mounting `/var/run/docker.sock` and adding a
  Docker-stats reader is the one infra change that would light this up.

Cached in-process for 20s. Never returns env vars, secrets, or file paths
beyond the fixed data-volume path - verified in
`tests/unit/test_monitoring.py`.

## What's a proxy, not a measurement: Activity by bot

`GET /admin/activity/by-bot` reuses the existing cost-by-bot aggregation
(`usage_repository.cost_by_bot`) plus average response time and last-sync
info, and computes each bot's **%share** of requests/tokens/cost for the
selected period. This is the defensible stand-in for "which bot is doing the
most work" - it is explicitly **not** a RAM/CPU measurement, and the
`/resources` page captions it as such:

> "Activity share is a proxy for load. All bots share one engine, so per-bot
> RAM isn't directly measurable - this shows each bot's share of the work."

Backend: `app/monitoring/activity.py`. Not cached (the queries are cheap
GROUP BYs, same as the existing Usage/Cost dashboards) and does respect the
time-filter period like every other dashboard endpoint.

## Frontend

`admin-portal/src/app/resources/page.tsx`, linked from the sidebar as
"System" (`HardDrive` icon). Storage and System Resources fetch once on
mount (no time filter - they're current-state, not historical); Activity
re-fetches when the period filter changes, mirroring the Usage page's
pattern. All three go through typed `api.ts` methods
(`getStorageByBot`, `getResources`, `getActivityByBot`) with realistic
`NEXT_PUBLIC_USE_MOCKS` mock data, same as every other admin-portal page -
no page component calls `fetch()` directly.

## Testing

Pure logic (the vector-size estimate math, the cgroup reader's handling of
missing/malformed/"max" files, the %share math, and - per this feature's own
requirement - that `/admin/resources`'s response never contains anything
secret-shaped) has unit tests in `tests/unit/test_monitoring.py`. Stateful
behavior (real `pg_total_relation_size` against the real `list_test` bot's
tables, real Qdrant point counts, the actual cgroup fallback behavior inside
the real container, and that all three endpoints correctly 401 without auth)
was verified live, consistent with how the rest of this repo's work has been
verified throughout.
