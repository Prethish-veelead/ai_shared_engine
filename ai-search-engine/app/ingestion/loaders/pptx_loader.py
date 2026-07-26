"""Stub loader for .pptx. Not needed by any current bot.
Implement extract() and call register('.pptx', ...) when a bot requires it.
"""
from pathlib import Path

from app.ingestion.loaders.base import DocumentLoader, ExtractedPage


class PptxLoader(DocumentLoader):
    def extract(self, path: Path) -> list[ExtractedPage]:
        raise NotImplementedError("Pptx loader not implemented yet.")


# register('.pptx', PptxLoader())  # uncomment + implement when needed
