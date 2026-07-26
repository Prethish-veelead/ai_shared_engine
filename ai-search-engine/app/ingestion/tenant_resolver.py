"""Tenant credentials resolver.

A bot's YAML only names its tenant (e.g. `veelead-development`) — never its
secrets. This module turns that name into the three credentials that tenant's
Entra app registration provides, by convention:

    veelead-development  ->  VEELEAD_DEVELOPMENT_TENANT_ID
                             VEELEAD_DEVELOPMENT_CLIENT_ID
                             VEELEAD_DEVELOPMENT_CLIENT_SECRET

Adding a new tenant later = add those three variables to .env (or, in
production, Azure Key Vault). No code and no YAML secrets.
"""
import os
from dataclasses import dataclass

from app.core.exceptions import ConfigError


@dataclass
class TenantCredentials:
    tenant_id: str
    client_id: str
    client_secret: str


def _env_prefix(tenant: str) -> str:
    """`veelead-development` -> `VEELEAD_DEVELOPMENT`."""
    return tenant.strip().upper().replace("-", "_").replace(" ", "_")


def resolve_tenant(tenant: str) -> TenantCredentials:
    prefix = _env_prefix(tenant)
    keys = {
        "tenant_id": f"{prefix}_TENANT_ID",
        "client_id": f"{prefix}_CLIENT_ID",
        "client_secret": f"{prefix}_CLIENT_SECRET",
    }
    missing = [k for k in keys.values() if not os.environ.get(k)]
    if missing:
        raise ConfigError(
            f"Missing SharePoint credentials for tenant '{tenant}'. "
            f"Set these environment variables: {', '.join(missing)}"
        )
    return TenantCredentials(
        tenant_id=os.environ[keys["tenant_id"]],
        client_id=os.environ[keys["client_id"]],
        client_secret=os.environ[keys["client_secret"]],
    )
