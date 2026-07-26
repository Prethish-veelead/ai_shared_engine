# Entra ID Setup — User Sign-In (Job B)

This is the **login** app registration, used to sign users in and check their
groups. It is a DIFFERENT registration from the SharePoint one (`Sites.Selected`,
Job A). Do these steps once per tenant: Veelead Development (dev), then Veelead
Solutions (prod).

## Create the login app registration

1. portal.azure.com → **Microsoft Entra ID** → **App registrations** →
   **New registration**.
2. Name: "HelloBot Login". Supported account types: **Single tenant**. Register.
3. On the Overview page, copy:
   - **Directory (tenant) ID**  → `<PREFIX>_TENANT_ID` (same tenant as SharePoint)
   - **Application (client) ID** → `<PREFIX>_AUTH_CLIENT_ID`

## Expose the API (this creates your API Audience)

4. Left menu → **Expose an API** → **Add** next to *Application ID URI*.
   Accept the default `api://<client-id>` → **Save**. That value is your
   **API Audience** → `<PREFIX>_API_AUDIENCE`. (No domain needed — `api://...`
   is just an identifier.)
5. Still on **Expose an API** → **Add a scope**:
   - Scope name: `access_as_user`
   - Who can consent: **Admins and users**
   - Fill the display/description fields → **Add scope**.

## Allow the local test helper (device-code sign-in)

6. Left menu → **Authentication** → scroll to **Advanced settings** →
   **Allow public client flows** → set to **Yes** → **Save**.
   (This lets `scripts/dev_login.py` sign you in from your terminal.)

## Emit group memberships in the token

7. Left menu → **Token configuration** → **Add groups claim** →
   choose **Security groups** → check **Access token** → **Add**.
   (This is what lets the backend read a user's groups for the per-bot gate.)

## For the frontend (bots + admin portal) later

8. Left menu → **Authentication** → **Add a platform** → **Single-page
   application** → add redirect URIs:
   - `http://localhost:3000` (local admin portal)
   - your production URL later.
   The frontend uses this client id + `api://<guid>/access_as_user` scope with
   MSAL to sign users in and get a token to send to the backend.

## Put the values in .env

```
AUTH_TENANT=veelead-development     # switch to veelead-solutions in prod

VEELEAD_DEVELOPMENT_TENANT_ID=<step 3>
VEELEAD_DEVELOPMENT_AUTH_CLIENT_ID=<step 3>
VEELEAD_DEVELOPMENT_API_AUDIENCE=<step 4>   # api://...
VEELEAD_DEVELOPMENT_ADMIN_GROUP_ID=<admin group object id, THIS tenant>
```

## Test locally (no frontend needed)

```bash
# 1. sign in and get a token
python -m scripts.dev_login          # open the URL, sign in with a Veelead Dev account

# 2. call a bot with the token it prints
curl -X POST localhost:8000/ask/hr \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?"}'
```

## The access rule (how allowed_groups behaves)

- Bot YAML `access.allowed_groups` **empty**  → any signed-in user can use it.
- Bot YAML `access.allowed_groups` **has ids** → only members of those groups.

So HR bot (no groups) is open to everyone in the tenant; the Security bot
(groups listed) is restricted. To restrict a bot to specific people, make a
security group in Entra, add those people, and put the group's **object id** in
that bot's `allowed_groups`.

## Quick tip: skip auth entirely while developing

Set `AUTH_ENABLED=false` in `.env` to bypass sign-in locally (the backend uses a
synthetic dev user). Set `DEV_USER_GROUPS=<group-id>` to test group-restricted
bots in bypass mode. Never run production with `AUTH_ENABLED=false`.


## Two tenants = two of everything (important)

A security group lives inside ONE tenant, so Veelead Development and Veelead
Solutions each have their OWN admin group with its OWN Object ID. Create
"HelloBot Admins" in BOTH tenants and set both variables:

```
VEELEAD_DEVELOPMENT_ADMIN_GROUP_ID=<dev tenant's group id>
VEELEAD_SOLUTIONS_ADMIN_GROUP_ID=<prod tenant's group id>
```

The active one is chosen automatically by `AUTH_TENANT` — no code change.

## Switching dev <-> production

Your `.env` holds BOTH tenants' values at all times. You only flip one line:

- Local / testing:   `AUTH_TENANT=veelead-development`
- Production VM:      `AUTH_TENANT=veelead-solutions`

Everything (tenant id, login client id, API audience, admin group) is then read
from that tenant's block. Same file shape everywhere; one line differs.

## Bot `allowed_groups` across tenants (chosen approach: simple)

A bot's `allowed_groups` in its YAML holds group Object IDs, which are also
tenant-specific. We keep it simple:

- Put the PRODUCTION (Veelead Solutions) group ids in each bot's YAML.
- Group-restricted bots (e.g. Security) enforce correctly in production.
- To test a restricted bot LOCALLY, set `AUTH_ENABLED=false` and
  `DEV_USER_GROUPS=<the group id in the YAML>` so the dev user "belongs" to it.

Open bots (empty `allowed_groups`) work everywhere with no setup.
