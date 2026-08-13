"""Force a full re-index of one bot (ignores delta token).
Usage: python -m scripts.reindex_bot <bot_id>
Wire to run_sync() with a reset delta token once SharePoint creds are set.
"""
import sys

from app.bots.registry import registry

if __name__ == "__main__":
    registry.load()
    bot = registry.get(sys.argv[1])
    if bot.sharepoint is not None:
        sites = ", ".join(s.site_url for s in bot.sharepoint.sites)
        print(f"Would re-index bot '{bot.id}' from site(s): {sites}")
        print("Implement: reset SyncState.delta_token=None then call run_sync().")
    else:
        # content_type=web bots never set bot.sharepoint (see
        # app/bots/schema.py's _valid_content_source) - they have no delta
        # token to reset, run_web_sync always does a full re-pull.
        print(f"Would re-index bot '{bot.id}' from web source: {bot.web.site_url}")
        print("Implement: call run_web_sync() directly - no delta token to reset for web bots.")
