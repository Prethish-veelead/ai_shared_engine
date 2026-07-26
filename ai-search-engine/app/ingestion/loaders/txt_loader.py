"""Stub loader for .txt. Not needed by any current bot.
Implement extract() and call register('.txt', ...) when a bot requires it.
"""
from pathlib import Path

from app.ingestion.loaders.base import DocumentLoader, ExtractedPage


class TextLoader(DocumentLoader):
    def extract(self, path: Path) -> list[ExtractedPage]:
        raise NotImplementedError("Text loader not implemented yet.")


# register('.txt', TextLoader())  # uncomment + implement when needed
