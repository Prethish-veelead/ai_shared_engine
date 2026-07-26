"""Local sign-in helper — get a real Entra token to test the API, no frontend.

Uses device-code flow: run it, open the URL it prints, sign in with your
Veelead Development account, and it prints an access token you can paste into
curl / Swagger as `Authorization: Bearer <token>`.

Requires (in .env, for the active AUTH_TENANT):
    <PREFIX>_TENANT_ID, <PREFIX>_AUTH_CLIENT_ID, <PREFIX>_API_AUDIENCE
The login app registration must allow public client flows and expose the scope
`access_as_user` (see docs/ENTRA_SETUP.md).

Usage: python -m scripts.dev_login
"""
import os

from app.core.config import get_settings


def main() -> None:
    import msal

    s = get_settings()
    p = s.auth_env_prefix()
    tenant_id = os.environ[f"{p}_TENANT_ID"]
    client_id = os.environ[f"{p}_AUTH_CLIENT_ID"]
    audience = os.environ[f"{p}_API_AUDIENCE"]
    scope = f"{audience}/access_as_user"

    app = msal.PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant_id}"
    )
    flow = app.initiate_device_flow(scopes=[scope])
    if "user_code" not in flow:
        raise SystemExit(f"Failed to start device flow: {flow}")

    print("\n" + flow["message"] + "\n")   # tells you the URL + code to enter
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise SystemExit(f"Login failed: {result.get('error_description')}")

    print("\n=== ACCESS TOKEN (paste as: Authorization: Bearer <token>) ===\n")
    print(result["access_token"])
    print("\nTest it, e.g.:")
    print('  curl -X POST localhost:8000/ask/hr \\')
    print('    -H "Authorization: Bearer <token>" \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"question":"What is the leave policy?"}\'')


if __name__ == "__main__":
    main()
