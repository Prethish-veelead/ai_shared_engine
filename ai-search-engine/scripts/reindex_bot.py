"""Force a full re-index of one bot (ignores delta token).
Usage: python -m scripts.reindex_bot <bot_id>
Wire to run_sync() with a reset delta token once SharePoint creds are set.
"""
import sys

from app.bots.registry import registry

if __name__ == "__main__":
    registry.load()
    bot = registry.get(sys.argv[1])
    print(f"Would re-index bot '{bot.id}' from site {bot.sharepoint.site_url}")
    print("Implement: reset SyncState.delta_token=None then call run_sync().")
