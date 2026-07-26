"""Entra ID token validation + access control (Job B: user sign-in).

What this does:
  - Validates the incoming Bearer JWT against the tenant's PUBLIC keys (JWKS):
    checks signature, issuer, audience, expiry. No client secret needed.
  - Extracts the user's id (oid), email, name, and group memberships.
  - Enforces the access rule: a bot with EMPTY allowed_groups is open to every
    authenticated user; a bot with groups listed is restricted to those groups.

Single-tenant per environment: settings.auth_tenant selects which tenant (dev =
veelead-development, prod = veelead-solutions), and the tenant id + API audience
are read from the matching .env variables.
"""
import os
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


@dataclass
class User:
    id: str
    email: str | None = None
    name: str | None = None
    groups: list[str] = field(default_factory=list)


@dataclass
class AuthConfig:
    tenant_id: str
    audiences: list[str]         # accept API Audience AND the bare app id (v1/v2)

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def jwks_uri(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"


@lru_cache
def get_auth_config() -> AuthConfig:
    s = get_settings()
    p = s.auth_env_prefix()
    tenant_id = os.environ.get(f"{p}_TENANT_ID")
    audience = os.environ.get(f"{p}_API_AUDIENCE")
    client_id = os.environ.get(f"{p}_AUTH_CLIENT_ID")  # optional, for aud match
    if not (tenant_id and audience):
        raise AuthError(
            f"Auth not configured for tenant '{s.auth_tenant}'. "
            f"Set {p}_TENANT_ID and {p}_API_AUDIENCE."
        )
    audiences = [audience]
    if client_id:
        audiences.append(client_id)             # v2 tokens often use bare guid
    guid = audience.split("api://")[-1]
    if guid and guid not in audiences:
        audiences.append(guid)
    return AuthConfig(tenant_id=tenant_id, audiences=audiences)


class TokenValidator:
    """Validates Entra JWTs using the tenant's published signing keys."""

    def __init__(self, cfg: AuthConfig):
        self._cfg = cfg
        self._jwk_client = None

    def _keys(self):
        import jwt
        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(self._cfg.jwks_uri)
        return self._jwk_client

    def validate(self, token: str) -> User:
        import jwt

        try:
            signing_key = self._keys().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._cfg.audiences,
                issuer=self._cfg.issuer,
            )
        except Exception as exc:
            raise AuthError(f"Invalid token: {exc}") from exc

        groups = claims.get("groups", [])
        if "_claim_names" in claims and "groups" in claims.get("_claim_names", {}):
            # Group overage: too many groups to fit in the token. Fail safe —
            # treat as no groups (restricted bots deny). At scale, resolve via
            # Graph /me/memberOf here.
            log.warning("Group overage for user %s; treating as no groups", claims.get("oid"))
            groups = []

        return User(
            id=claims.get("oid") or claims.get("sub"),
            email=claims.get("preferred_username") or claims.get("email"),
            name=claims.get("name"),
            groups=groups,
        )


@lru_cache
def get_validator() -> TokenValidator:
    return TokenValidator(get_auth_config())


def get_admin_group_id() -> str | None:
    """The admin group's Object ID for the ACTIVE tenant (dev vs prod).
    Resolved per-tenant like everything else: {PREFIX}_ADMIN_GROUP_ID.
    A group exists only inside one tenant, so dev and prod have different ids.
    """
    s = get_settings()
    return os.environ.get(f"{s.auth_env_prefix()}_ADMIN_GROUP_ID")


def can_access_bot(bot, user: User) -> bool:
    """Access rule: empty allowed_groups = open to all authenticated users;
    otherwise the user must be in at least one allowed group."""
    allowed = bot.access.allowed_groups
    if not allowed:
        return True
    return bool(set(allowed) & set(user.groups))


def dev_user() -> User:
    """Synthetic user used only when auth_enabled is False (local dev)."""
    s = get_settings()
    groups = [g.strip() for g in s.dev_user_groups.split(",") if g.strip()]
    return User(id="dev-user", email="dev@localhost", name="Dev User", groups=groups)
