# Admin Notification Bell

An Azure-Portal-style bell in the admin portal header: sync start/complete,
sync errors, and RAM/disk threshold alerts all show up there, with an
unread badge and a "mark all read."

## Design: reuse, don't rebuild

This bell reads the **same `event_logs` table and the same `GET /admin/logs`
endpoint** the existing Logs & Monitoring page already uses - no new backend
read path, no new database table. The only new work was:

1. **Writing more events than before.** Previously only a sync *failure*
   wrote an `EventLog` row (`type="sync"`). `sync_one_bot()`
   (`app/workers/sync_scheduler.py`) now also writes one when a sync
   **starts** and when it **completes successfully** - covering both the
   cron-scheduled path and the admin portal's manual "Sync Now"/"Full
   Reindex" buttons, since both call this exact same function.
2. **A new event source: resource thresholds.** `app/monitoring/alerts.py`'s
   `check_resource_thresholds()` calls the existing
   `app/monitoring/resources.get_resources()` (built for the `/resources`
   page) and writes an `EventLog` row (`type="resource"`) whenever memory or
   disk usage crosses `resource_alert_threshold_pct` (default 90%). Run
   every `resource_alert_check_interval_minutes` (default 5) via a new job
   on the worker's existing APScheduler - the same scheduler that already
   runs each bot's cron sync, just one more periodic job alongside them.
3. **The bell itself** (`admin-portal/src/components/layout/NotificationBell.tsx`)
   - net new frontend UI - polls `GET /admin/logs` every 15 seconds.

## Simplification vs. a literal Azure Portal card

Azure Portal's notification cards update **in place** - a spinner on
"Deploying..." morphs into a checkmark on the same card. Building that
would mean tracking a job's live status (a job id, a mutable status field,
`updated_at`) - a real piece of new infrastructure. What's built here is
simpler and reuses the append-only `event_logs` table as-is: a sync
produces **two separate notifications**, "Sync started" and later "Sync
completed successfully" (or a failure message instead), not one card that
changes state. For sync/error/threshold alerts - none of which need
sub-second precision - this is a reasonable trade, not a compromise anyone
is likely to notice in practice.

## Unread tracking: client-side only, on purpose

`EventLog` has no `read`/`acked` column, and none was added - the live
Postgres table already exists with its current 5 columns
(`Base.metadata.create_all()` only creates missing tables, it doesn't
`ALTER` existing ones, so adding a column would need a manual migration).
Instead, "unread" is computed purely in the browser: the bell keeps the
highest notification `id` it's shown the admin in `localStorage`
(`notif_last_seen_id`), and anything with a higher `id` counts as unread.
"Mark all read" just bumps that stored value to the newest id currently
loaded. Each browser/tab tracks its own read state independently - there is
no server-side "read by whom" concept, which is an intentional scope limit,
not an oversight.

## Debounce (resource alerts only)

A sustained high-memory period would otherwise write a new `EventLog` row
every single check interval forever. Before writing, `check_resource_thresholds()`
checks for a same-metric alert already logged within
`resource_alert_debounce_minutes` (default 30) and skips if one exists -
verified live: forcing a threshold crossing wrote exactly one alert, and
running the check again immediately afterward wrote zero more.

## Settings (`app/core/config.py`)

- `resource_alert_threshold_pct` (default 90.0)
- `resource_alert_check_interval_minutes` (default 5)
- `resource_alert_debounce_minutes` (default 30)

## Testing

Pure logic (threshold comparison, debounce suppression, both metrics
firing independently, a `get_resources()` failure not crashing the check)
has unit tests in `tests/unit/test_alerts.py`, using monkeypatched stand-ins
for `get_resources()`/`record_event()`/the debounce query - no DB needed.
Stateful behavior - a real manual sync producing real "started"/"completed"
rows, and a forced real threshold crossing actually writing to (and the
debounce correctly protecting) the live `event_logs` table - was verified
live against the real dev Postgres instance, consistent with how the rest
of this repo's work has been verified throughout. The two live-test
"resource" rows were deleted afterward so they don't show up as fake
alerts in the real notification feed.
