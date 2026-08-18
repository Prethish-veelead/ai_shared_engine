# SPFx web parts calling `/api/ask/{botId}` directly

An SPFx web part running on a SharePoint origin (`https://<tenant>.sharepoint.com`)
can call this API's existing `POST /api/ask/{botId}` endpoint the same way
bot-ui does - using the logged-in SharePoint user's own Entra token, acquired
via SPFx's `AadHttpClientFactory`. **No new endpoint, no API key, no separate
SPFx code path** - it's the exact same `get_current_user()` → `can_access_bot()`
→ `chat_logs`/`usage_logs` path bot-ui already goes through, which is why an
SPFx user shows up in the admin portal's Chat History exactly like a bot-ui
user does.

Two things block a direct cross-origin call today; both are config-only fixes.

## 1. CORS (the browser-side gate)

Set `CORS_ALLOWED_ORIGINS` (comma-separated) to the SharePoint origin(s) that
should be allowed to call this API directly:

```bash
CORS_ALLOWED_ORIGINS=https://contoso.sharepoint.com
```

Left empty/unset (the default), **no CORS middleware is added to the app at
all** - bot-ui/admin-portal's existing same-origin calls are completely
unaffected either way, since this only governs which *other* browser origins
are allowed to read the response.

## 2. Token audience

Already handled - no config change needed. `app/core/security.py`'s
`get_auth_config()` already accepts both the full App ID URI (`api://<client-id>`)
and the bare `<client-id>` guid, since it derives the bare guid from the
configured `*_API_AUDIENCE` value unconditionally (not only when a separate
`*_AUTH_CLIENT_ID` is set). Whichever audience form SPFx's
`AadHttpClientFactory` requests a token for, it already validates.

## What an SPFx web part needs to do

1. Request a token for this API's scope via `AadHttpClientFactory`:
   ```
   api://<client-id>/access_as_user
   ```
   (the same App ID URI/scope bot-ui's MSAL config uses - see
   `docs/ENTRA_SETUP.md`).
2. Call `POST /api/ask/{botId}` with that token as a Bearer `Authorization`
   header:
   ```json
   // Request
   { "question": "How do I reset my VPN?", "history": [] }
   ```
   ```json
   // Response
   {
     "answer": "...",
     "citations": [{ "index": 1, "source": "...", "url": "..." }],
     "model": "gpt-4o-mini",
     "total_tokens": 512,
     "cost_usd": 0.0021,
     "response_time_ms": 1340,
     "chat_log_id": 4821
   }
   ```
3. That's it - identity extraction, `allowed_groups` enforcement, and the
   `chat_logs`/`usage_logs` stamping all happen identically to a bot-ui call,
   since the token flows through the exact same validation path.

## SharePoint Admin approval (not a code change)

The first time an SPFx web part requests this API's scope, Azure AD/SharePoint
requires a **SharePoint Admin** (or Global Admin) to approve the "API access"
request in the SharePoint Admin Center (API access → Pending requests). This
is a one-time, per-tenant approval step done by whoever administers the
SharePoint tenant - it does not involve any change to this repo.
