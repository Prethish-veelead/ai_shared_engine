"""Pure-logic unit tests for the library-side Publish Gate
(app/workers/sync_job.py's _is_published) and its explicit opt-out flag
(SharePointSite.require_publish_gate). No I/O - pure function + schema
defaults.

The Publish Gate is per-SITE (SharePointSite), not per-bot - two library
sites on the same bot commonly use different status schemas, so each site's
own gate settings are read independently. The key invariant under test:
require_publish_gate defaults to True on every site (every existing bot's
config, real or shimmed, behaves exactly as it did before this field
existed) and turning it off for a given site is only ever a deliberate,
explicit choice - never inferred from status_column/published_value being
absent or left at their defaults.
"""
from app.bots.schema import (
    BotConfig,
    ListPlusLibraryConfig,
    PromptConfig,
    SharePointConfig,
    SharePointSite,
    VectorStoreConfig,
)
from app.ingestion.sharepoint_client import ChangedItem
from app.workers.sync_job import _is_published, _library_shim


def _item(fields: dict) -> ChangedItem:
    return ChangedItem(doc_id="1", name="doc.pdf", deleted=False, download_url="x",
                       last_modified=None, fields=fields)


# ---- schema defaults: require_publish_gate is on by default, per site ----

def test_sharepoint_site_require_publish_gate_defaults_true():
    site = SharePointSite(site_url="https://x", libraries=["KB"])
    assert site.require_publish_gate is True
    assert site.status_column == "Status"
    assert site.published_value == "Published"


# ---- _is_published: gate ON (default) behaves exactly as before ----

def test_gate_on_matching_status_is_published():
    site = SharePointSite(site_url="https://x", libraries=["KB"])
    assert _is_published(_item({"Status": "Published"}), site) is True


def test_gate_on_non_matching_status_is_not_published():
    site = SharePointSite(site_url="https://x", libraries=["KB"])
    assert _is_published(_item({"Status": "Draft"}), site) is False


def test_gate_on_missing_status_column_is_not_published():
    # Unlike the list-side gate (_is_list_item_published), the library gate
    # has no "column absent -> include" leniency - a library relying on the
    # gate with no Status column at all excludes everything, which is
    # exactly the problem require_publish_gate=False exists to solve.
    site = SharePointSite(site_url="https://x", libraries=["KB"])
    assert _is_published(_item({}), site) is False


def test_gate_on_case_and_whitespace_insensitive():
    site = SharePointSite(site_url="https://x", libraries=["KB"])
    assert _is_published(_item({"Status": "  PUBLISHED  "}), site) is True


def test_gate_on_custom_column_and_value():
    site = SharePointSite(site_url="https://x", libraries=["KB"],
                          status_column="ReviewState", published_value="Approved")
    assert _is_published(_item({"ReviewState": "Approved"}), site) is True
    assert _is_published(_item({"Status": "Published"}), site) is False


# ---- _is_published: gate OFF is an explicit, deliberate bypass ----

def test_gate_off_includes_everything_regardless_of_status():
    site = SharePointSite(site_url="https://x", libraries=["KB"], require_publish_gate=False)
    assert _is_published(_item({"Status": "Draft"}), site) is True
    assert _is_published(_item({}), site) is True
    assert _is_published(_item({"Status": "Published"}), site) is True


# ---- two sites on the same bot can have genuinely different gates ----

def test_two_sites_have_independent_gates():
    site_a = SharePointSite(site_url="https://a", libraries=["KB-A"],
                            status_column="Status", published_value="Published")
    site_b = SharePointSite(site_url="https://b", libraries=["KB-B"],
                            status_column="ReviewState", published_value="Approved")
    doc = {"Status": "Published", "ReviewState": "Draft"}
    assert _is_published(_item(doc), site_a) is True
    assert _is_published(_item(doc), site_b) is False


def test_one_site_gated_other_site_no_gate():
    site_a = SharePointSite(site_url="https://a", libraries=["KB-A"])          # gate on
    site_b = SharePointSite(site_url="https://b", libraries=["KB-B"], require_publish_gate=False)
    assert _is_published(_item({}), site_a) is False
    assert _is_published(_item({}), site_b) is True


# ---- _library_shim passes real SharePointSite objects through unmapped ----
# (the shim used to remap bot-level gate fields onto a SimpleNamespace before
# the gate moved per-site - now library_sites entries already carry their
# own gate fields, so there's nothing left for the shim to translate.)

def _combined_bot(library_sites: list[SharePointSite]) -> BotConfig:
    return BotConfig(
        id="helpdesk", name="Helpdesk", route="/ask/helpdesk", content_type="list+library",
        list_plus_library=ListPlusLibraryConfig(
            tenant="acme",
            library_sites=library_sites,
            list_sites=[SharePointSite(site_url="https://acme.sharepoint.com/sites/helpdesk",
                                       lists=["Tickets"])],
        ),
        vectorstore=VectorStoreConfig(library_collection="helpdesk_kb", list_collection="helpdesk_tickets"),
        prompt=PromptConfig(system="sys"),
    )


def test_library_shim_sites_default_to_gate_on():
    shim = _library_shim(_combined_bot([
        SharePointSite(site_url="https://acme.sharepoint.com/sites/helpdesk", libraries=["KB"]),
    ]))
    site = shim.sharepoint.sites[0]
    assert site.require_publish_gate is True
    assert site.status_column == "Status"
    assert site.published_value == "Published"


def test_library_shim_preserves_per_site_custom_gate():
    shim = _library_shim(_combined_bot([
        SharePointSite(site_url="https://a", libraries=["KB-A"],
                       status_column="ReviewState", published_value="Approved"),
        SharePointSite(site_url="https://b", libraries=["KB-B"], require_publish_gate=False),
    ]))
    site_a, site_b = shim.sharepoint.sites
    assert site_a.status_column == "ReviewState"
    assert site_a.published_value == "Approved"
    assert site_b.require_publish_gate is False


def test_library_shim_gate_off_end_to_end_via_is_published():
    shim = _library_shim(_combined_bot([
        SharePointSite(site_url="https://a", libraries=["KB-A"], require_publish_gate=False),
    ]))
    site = shim.sharepoint.sites[0]
    assert _is_published(_item({}), site) is True
    assert _is_published(_item({"Status": "Draft"}), site) is True


# ---- SharePointConfig.status_column/published_value remain list-bot-only,
# unrelated to the per-site library gate above ----

def test_sharepoint_config_status_column_unaffected_by_site_gate_move():
    cfg = SharePointConfig(tenant="t", sites=[])
    assert cfg.status_column == "Status"
    assert cfg.published_value == "Published"
    assert not hasattr(cfg, "require_publish_gate")
