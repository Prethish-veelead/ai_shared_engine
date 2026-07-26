# MSAL Login Test Plan

Hand this to Antigravity to implement the fix and verify it. It covers: the
confirmed bug, the required code change, and a step-by-step test case for
each app with an explicit expected result to check against.

## Confirmed root cause

Reproduced live (real Entra sign-in, dev tenant `veelead-development`,
test account `Cynthia@veeleaddev.onmicrosoft.com`) via browser automation
against `bot-ui` on `http://localhost:3000`:

1. Click "Sign in with Microsoft" -> `instance.loginPopup({ scopes: [getApiScope()] })` opens a popup.
2. Microsoft's login page loads, credentials are accepted (tenant + app
   registration are correctly configured - not the problem).
3. Microsoft redirects the **popup** to `http://localhost:3000/#code=...` - a
   valid authorization code.
4. **Bug**: the popup does not get read-and-closed by the opener. Instead the
   popup itself boots the entire Next.js app from scratch (no session of its
   own), so it just renders the sign-in wall again with the code still
   sitting unused in its URL hash.
5. The original window is left stuck on "Loading…" forever - it's still
   awaiting a `loginPopup()` promise that will never resolve, because the
   opener never got the chance to read the popup's redirected URL before the
   popup's own app finished loading and took over.

This is a known MSAL popup failure mode in SPA dev servers: the popup's
redirect target is the full app route, so nothing stops the popup from
fully hydrating before the opener's polling/monitoring can catch the
redirect and close it. It reproduces in a clean single-profile browser
automation run, so it is not specific to Edge profile-switching (that may be
a secondary aggravating factor for the reporting user, but is not the root
cause).

## Required fix

Switch the interactive sign-in call from `loginPopup()` to `loginRedirect()`
in **both** apps, so login is a single-window navigation with nothing to
lose track of:

- `admin-portal/src/components/layout/Header.tsx` - `instance.loginPopup({ scopes: [getApiScope()] })` -> `instance.loginRedirect({ scopes: [getApiScope()] })`
- `bot-ui/src/components/layout/AppShell.tsx` - same change
- Correspondingly switch `instance.logoutPopup()` -> `instance.logoutRedirect()` in both files (a popup logout has the identical failure mode as popup login).

No other files need to change for this specific fix - `Providers.tsx`'s
`AuthGate` (gates rendering on `inProgress === InteractionStatus.None`) and
`msal.ts`'s `acquireApiToken()` (silent-first, guarded interactive fallback)
were already built to handle the redirect flow correctly; they just were
never exercised by the *initial* login before now.

## Test environment

- Backend: `cd ai-search-engine/docker && docker compose up --build -d`, confirm `curl http://localhost:8000/health` returns `{"status":"ok"}`.
- bot-ui **must run on port 3000** - it is the only redirect URI registered on the "HelloBot Login" Entra app registration. `cd bot-ui && node ./node_modules/next/dist/bin/next dev -p 3000`.
- Test account: `Cynthia@veeleaddev.onmicrosoft.com` (dev tenant `veelead-development`).

---

## Test Case 1 - Sign-in completes without a loop or stuck screen

**Steps:**
1. Open `http://localhost:3000/bot/hr` in a fresh browser session (clear cookies/sessionStorage first, or use a new profile).
2. Click "Sign in with Microsoft".
3. Complete the Microsoft login form with the test account (handle the "Stay signed in?" prompt either way).

**Expected result:**
- The **same tab** navigates to Microsoft and back - no second window/popup opens.
- After Microsoft redirects back, the app briefly shows "Loading…" (the `AuthGate`), then renders the actual HR chat interface - not the sign-in wall again, and not stuck on "Loading…".
- No `BrowserAuthError` (`timed_out`, `interaction_in_progress`, or otherwise) appears in the browser console.

**Fail if:** you see the sign-in wall again after the redirect, a console error, or the app hangs on "Loading…" for more than a few seconds.

## Test Case 2 - Chat call carries a token and gets a real answer

**Steps:**
1. Continuing from Test Case 1 (now signed in), open DevTools -> Network.
2. Type a question (e.g. "What is the leave policy?") and send it.

**Expected result:**
- A `POST /api/ask/hr` request appears with an `Authorization: Bearer <token>` header present.
- That request returns **200**, not 401/403.
- The response body has `{ answer, citations, model, total_tokens, cost_usd, response_time_ms }` and the UI renders the answer (and any citations).

**Fail if:** the request has no `Authorization` header, or returns 401/403. If it 401s with `"message": "Invalid issuer"` specifically, **stop and report that separately** - it's a different, already-partially-diagnosed issue (see "Known separate issue" below), not something this fix addresses.

## Test Case 3 - Refresh keeps you signed in (silent token, no re-login)

**Steps:**
1. Still signed in from Test Case 1, refresh the page (F5).
2. Send another chat message.

**Expected result:**
- No redirect to Microsoft happens on refresh - the app goes straight from "Loading…" to the authenticated chat UI.
- The chat message in step 2 still gets a 200 response with a Bearer token attached (silent token acquisition via `acquireTokenSilent`, not a fresh interactive login).

**Fail if:** refreshing bounces you back to Microsoft's login page, or to the sign-in wall.

## Test Case 4 - Token audience and scope are correct

**Steps:**
1. While signed in, get the access token used for `/api/ask/hr` (copy it from the `Authorization` header of that request in DevTools Network tab).
2. Decode it at https://jwt.ms.

**Expected result / report back these exact values:**
- `aud` should be `api://d7e5a281-2473-4caa-9d33-253ff2f7abe1` (or the bare guid `d7e5a281-2473-4caa-9d33-253ff2f7abe1`).
- `scp` should include `access_as_user`.
- `iss` should be `https://login.microsoftonline.com/08a7d6c3-ef04-48a8-be88-dc96b69ab9a4/v2.0`.

**Fail if:** `aud` is anything else (e.g. Microsoft Graph's `00000003-0000-0000-c000-000000000000`), `scp` doesn't include `access_as_user`, or `iss` doesn't match the exact v2 format above.

## Test Case 5 - Sign out works cleanly

**Steps:**
1. While signed in, click "Sign Out".

**Expected result:**
- The app returns to the sign-in wall (no error, no stuck state).
- No leftover session lets you access `/bot/hr` without signing in again (refresh and confirm the sign-in wall still shows).

## Test Case 6 - Repeat Test Cases 1-5 for admin-portal

Same steps and same expected results, but:
- admin-portal must be the one running on port 3000 for this pass (only one app can hold the registered redirect URI at a time locally) - stop bot-ui, start admin-portal on 3000 instead.
- In Test Case 2's equivalent, check any of the admin dashboard's real API calls (e.g. `GET /api/admin/bots`) instead of `/ask/hr`.
- `aud`/`scp`/`iss` checks in Test Case 4 are identical (same login app, same audience).

---

## Known separate issue - do not try to fix this as part of the popup/redirect change

Independently of the popup bug, one earlier attempt produced:
```json
{"error":{"code":"unauthorized","message":"Invalid token: Invalid issuer"}}
```
If this reappears after the `loginRedirect` fix (check via Test Case 4's `iss` value), it means the access token's issuer doesn't exactly match `https://login.microsoftonline.com/08a7d6c3-ef04-48a8-be88-dc96b69ab9a4/v2.0`. The most likely cause is the "HelloBot Login" Entra app registration issuing v1-format tokens (`iss` like `https://sts.windows.net/08a7d6c3-ef04-48a8-be88-dc96b69ab9a4/`) because its manifest doesn't have `"accessTokenAcceptedVersion": 2` set. That's an Azure Portal app-registration change, not a frontend code change - report the exact `iss` value back rather than guessing at a fix.

## What to report back

For each test case: pass/fail, and for any failure - a screenshot, the browser console output, and (for Test Case 2/4) the exact response body / decoded token claims. Test Case 4's three claim values should be reported every time, pass or fail, since they're the fastest way to catch a misconfiguration even if everything looks like it's working.
