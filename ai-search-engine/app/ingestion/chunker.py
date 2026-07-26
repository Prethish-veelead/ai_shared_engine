"""Token-aware chunking. Splits page text into overlapping chunks sized by
tokens (not characters) so chunks fit the embedding model cleanly.
"""
from dataclasses import dataclass

from app.ingestion.loaders.base import ExtractedPage


@dataclass
class Chunk:
    text: str
    metadata: dict


def _encoder():
    import tiktoken
    # cl100k_base matches the text-embedding-3-* and gpt-4o families.
    return tiktoken.get_encoding("cl100k_base")


def chunk_pages(pages: list[ExtractedPage], *, chunk_size: int, overlap: int,
                base_metadata: dict) -> list[Chunk]:
    enc = _encoder()
    chunks: list[Chunk] = []
    for page in pages:
        tokens = enc.encode(page.text)
        start = 0
        while start < len(tokens):
            window = tokens[start:start + chunk_size]
            text = enc.decode(window).strip()
            if text:
                meta = {**base_metadata, **page.metadata}
                chunks.append(Chunk(text=text, metadata=meta))
            if start + chunk_size >= len(tokens):
                break
            start += chunk_size - overlap
    return chunks
