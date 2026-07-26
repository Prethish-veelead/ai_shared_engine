"""Manually trigger one bot's SharePoint sync (for testing, no waiting on cron).
Usage: python -m scripts.sync_bot <bot_id>
"""
import sys

from app.bots.registry import registry
from app.workers.sync_scheduler import sync_one_bot

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.sync_bot <bot_id>")
        raise SystemExit(1)
    registry.load()
    print(f"Running sync for bot '{sys.argv[1]}'...")
    sync_one_bot(sys.argv[1])
    print("Done. Check logs above for indexed/skipped counts.")
