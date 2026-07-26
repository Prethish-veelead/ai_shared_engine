"""Stub loader for .xlsx. Not needed by any current bot.
Implement extract() and call register('.xlsx', ...) when a bot requires it.
"""
from pathlib import Path

from app.ingestion.loaders.base import DocumentLoader, ExtractedPage


class XlsxLoader(DocumentLoader):
    def extract(self, path: Path) -> list[ExtractedPage]:
        raise NotImplementedError("Xlsx loader not implemented yet.")


# register('.xlsx', XlsxLoader())  # uncomment + implement when needed
