"""Tests for SPFx cross-origin API access (docs/SPFX_API_ACCESS.md):
- CORSMiddleware is only added when CORS_ALLOWED_ORIGINS is configured, and
  behaves correctly (allowed origin gets headers, disallowed origin doesn't).
- The Entra token audience an SPFx web part's AadHttpClientFactory-acquired
  token carries (either the full App ID URI or the bare client-id guid) is
  ALREADY accepted by get_auth_config() with no code change - this test
  documents/locks in that existing behavior rather than adding new config.
No live server, no live Postgres/Qdrant - CORS preflight is fully handled by
CORSMiddleware before any route/dependency runs, and get_auth_config() is
pure env-var parsing.
"""
from starlette.testclient import TestClient

from app.core.config import Settings, get_settings


# ---- cors_allowed_origins_list(): pure parsing ----

def test_cors_allowed_origins_list_parses_comma_separated_and_trims():
    s = Settings(cors_allowed_origins="https://a.sharepoint.com, https://b.sharepoint.com ,, ")
    assert s.cors_allowed_origins_list() == ["https://a.sharepoint.com", "https://b.sharepoint.com"]


def test_cors_allowed_origins_list_empty_by_default():
    assert Settings().cors_allowed_origins_list() == []


# ---- CORSMiddleware wiring in app/main.py ----

def _fresh_app(monkeypatch, cors_origins: str):
    from app.main import create_app

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", cors_origins)
    get_settings.cache_clear()
    try:
        return create_app()
    finally:
        get_settings.cache_clear()   # don't leak this override into other tests


def test_cors_preflight_succeeds_for_configured_origin(monkeypatch):
    app = _fresh_app(monkeypatch, "https://contoso.sharepoint.com")
    client = TestClient(app)
    resp = client.options(
        "/api/ask/anybot",
        headers={
            "Origin": "https://contoso.sharepoint.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://contoso.sharepoint.com"
    assert "POST" in resp.headers["access-control-allow-methods"]
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_cors_preflight_rejects_unconfigured_origin(monkeypatch):
    app = _fresh_app(monkeypatch, "https://contoso.sharepoint.com")
    client = TestClient(app)
    resp = client.options(
        "/api/ask/anybot",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    # The preflight request itself doesn't error, but a disallowed origin
    # never gets an allow-origin header - that's what makes the BROWSER
    # block the real request from proceeding.
    assert "access-control-allow-origin" not in resp.headers


def test_no_cors_middleware_at_all_when_unset(monkeypatch):
    # Not just "an empty allow-list" - no CORSMiddleware in the stack, so
    # bot-ui/admin-portal's existing same-origin calls are byte-for-byte
    # today's behavior.
    app = _fresh_app(monkeypatch, "")
    client = TestClient(app)
    resp = client.options(
        "/api/ask/anybot",
        headers={"Origin": "https://contoso.sharepoint.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in resp.headers
    assert not any(m.cls.__name__ == "CORSMiddleware" for m in app.user_middleware)


# ---- Audience: confirm SPFx's token form is ALREADY accepted, no new config ----

def test_auth_config_already_accepts_both_audience_forms(monkeypatch):
    from app.core.security import get_auth_config

    # Pin auth_tenant explicitly - get_settings() reads AUTH_TENANT from the
    # real environment too, and the active .env may already point at a
    # different tenant (e.g. veelead-solutions), which would make this test
    # read THAT tenant's real prefix/values instead of the ones set below.
    monkeypatch.setenv("AUTH_TENANT", "veelead-development")
    monkeypatch.setenv("VEELEAD_DEVELOPMENT_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("VEELEAD_DEVELOPMENT_API_AUDIENCE", "api://22222222-2222-2222-2222-222222222222")
    monkeypatch.delenv("VEELEAD_DEVELOPMENT_AUTH_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    get_auth_config.cache_clear()
    try:
        cfg = get_auth_config()
        # An SPFx AadHttpClientFactory-acquired token's `aud` claim is either
        # the full App ID URI or the bare client-id guid - both forms must
        # already validate. Confirmed here WITHOUT setting AUTH_CLIENT_ID at
        # all: the bare guid is unconditionally derived from API_AUDIENCE
        # itself (app/core/security.py's get_auth_config), so this is not new
        # behavior added for SPFx - it already worked for any v2-token caller.
        assert "api://22222222-2222-2222-2222-222222222222" in cfg.audiences
        assert "22222222-2222-2222-2222-222222222222" in cfg.audiences
    finally:
        get_settings.cache_clear()
        get_auth_config.cache_clear()
