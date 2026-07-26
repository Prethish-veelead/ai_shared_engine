"""Loader interface + registry. Adding a new file type = add one file that
implements DocumentLoader and register it against its extension. No pipeline
changes anywhere else.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedPage:
    text: str
    metadata: dict = field(default_factory=dict)   # e.g. {"page": 3}


class DocumentLoader(ABC):
    @abstractmethod
    def extract(self, path: Path) -> list[ExtractedPage]:
        """Return text split by natural unit (page / slide / sheet)."""


# extension -> loader instance
_REGISTRY: dict[str, DocumentLoader] = {}


def register(extension: str, loader: DocumentLoader) -> None:
    _REGISTRY[extension.lower()] = loader


def get_loader(path: Path) -> DocumentLoader:
    ext = path.suffix.lower()
    if ext not in _REGISTRY:
        raise ValueError(f"No loader registered for '{ext}'")
    return _REGISTRY[ext]


def supported_extensions() -> list[str]:
    return sorted(_REGISTRY)
