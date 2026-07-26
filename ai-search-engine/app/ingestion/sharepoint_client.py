"""SharePoint access via Microsoft Graph with app-only auth (client
credentials). Uses DELTA queries so each sync returns only changed items.

Auth notes (from the design discussion):
  - App-only via client credentials + certificate/secret.
  - Least-privilege 'Sites.Selected' permission, granted per site.
  - Each M365 tenant needs its own app registration + admin consent.

This is a working skeleton: token acquisition is real; the Graph calls show the
shape you need. Fill in your tenant/app IDs via env + per-tenant config.
"""
from dataclasses import dataclass

from app.core.logging import get_logger

log = get_logger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class ChangedItem:
    doc_id: str            # driveItem id (stable id used across re-indexing)
    name: str
    deleted: bool
    download_url: str | None
    last_modified: str | None
    fields: dict | None = None   # SharePoint column values (Status, Category, ...)


class SharePointClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret

    def _token(self) -> str:
        import msal

        app = msal.ConfidentialClientApplication(
            client_id=self._client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            client_credential=self._client_secret,
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"Graph token failed: {result.get('error_description')}")
        return result["access_token"]

    def resolve_site(self, site_url: str) -> str:
        """Turn a friendly site URL into the Graph site ID.

        'https://veelead.sharepoint.com/sites/HR'
          -> GET /sites/veelead.sharepoint.com:/sites/HR
          -> returns the site's id
        """
        import requests
        from urllib.parse import urlparse

        parsed = urlparse(site_url)
        hostname = parsed.netloc                    # veelead.sharepoint.com
        site_path = parsed.path.rstrip("/")         # /sites/HR
        headers = {"Authorization": f"Bearer {self._token()}"}
        url = f"{GRAPH}/sites/{hostname}:{site_path}"
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()["id"]

    def resolve_drives(self, site_id: str) -> dict[str, str]:
        """Return {library display name -> drive id} for a site.
        Match these against the bot YAML `libraries` names.
        """
        import requests

        headers = {"Authorization": f"Bearer {self._token()}"}
        url = f"{GRAPH}/sites/{site_id}/drives"
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return {d["name"]: d["id"] for d in resp.json().get("value", [])}

    def delta(self, drive_id: str, delta_link: str | None) -> tuple[list[ChangedItem], str]:
        """Return (changed_items, next_delta_link).
        Pass the saved next_delta_link back next time to get only new changes.
        """
        import requests

        headers = {"Authorization": f"Bearer {self._token()}"}
        url = delta_link or f"{GRAPH}/drives/{drive_id}/root/delta"
        items: list[ChangedItem] = []
        next_link = url

        while True:
            resp = requests.get(next_link, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            for it in data.get("value", []):
                if "folder" in it:
                    continue
                items.append(ChangedItem(
                    doc_id=it["id"],
                    name=it.get("name", ""),
                    deleted="deleted" in it,
                    download_url=it.get("@microsoft.graph.downloadUrl"),
                    last_modified=it.get("lastModifiedDateTime"),
                ))
            if "@odata.nextLink" in data:
                next_link = data["@odata.nextLink"]
                continue
            return items, data.get("@odata.deltaLink", "")

    def get_download_url(self, drive_id: str, item_id: str) -> str | None:
        """@microsoft.graph.downloadUrl isn't reliably present on /delta
        responses (confirmed empty for every item on this tenant's library),
        but a direct item lookup always includes it. Fetch it explicitly for
        items /delta didn't provide one for."""
        import requests

        headers = {"Authorization": f"Bearer {self._token()}"}
        url = f"{GRAPH}/drives/{drive_id}/items/{item_id}"
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json().get("@microsoft.graph.downloadUrl")

    def get_fields(self, drive_id: str, item_id: str) -> dict:
        """Return the SharePoint column values (Status, Category, ...) for a
        file. Columns live on the file's associated listItem, not the driveItem,
        so we read listItem.fields. (Delta responses don't reliably include
        these, so we fetch per changed item — correct and simple.)

        Note: Graph uses each column's INTERNAL name, which can differ from the
        display name (spaces become '_x0020_', etc.). Confirm internal names in
        the SharePoint list settings and set them in the bot YAML if needed.
        """
        import requests

        headers = {"Authorization": f"Bearer {self._token()}"}
        url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/listItem?$expand=fields"
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json().get("fields", {})

    def download(self, download_url: str, dest_path) -> None:
        import requests

        resp = requests.get(download_url, timeout=120)
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            fh.write(resp.content)
