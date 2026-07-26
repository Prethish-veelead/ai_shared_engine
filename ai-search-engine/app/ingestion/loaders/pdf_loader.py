"""PDF loader with a smart OCR path (Tesseract).

Strategy:
  1. Extract the embedded text layer with PyMuPDF (fast, free, most PDFs).
  2. If a page has little/no text but DOES contain images, it is a scanned/
     image page -> render it and run Tesseract OCR.
This avoids OCR-ing every page while still handling image-based documents.
"""
from pathlib import Path

from app.ingestion.loaders.base import DocumentLoader, ExtractedPage, register
from app.ingestion.loaders.ocr import ocr_image_bytes

_MIN_TEXT_CHARS = 20   # below this, treat the page as image-based


class PdfLoader(DocumentLoader):
    def extract(self, path: Path) -> list[ExtractedPage]:
        import fitz  # PyMuPDF

        pages: list[ExtractedPage] = []
        with fitz.open(path) as doc:
            for i, page in enumerate(doc, start=1):
                text = page.get_text().strip()
                if len(text) < _MIN_TEXT_CHARS and page.get_images():
                    # Render the page to a PNG and OCR it.
                    png_bytes = page.get_pixmap(dpi=200).tobytes("png")
                    text = ocr_image_bytes(png_bytes) or text
                if text:
                    pages.append(ExtractedPage(text=text, metadata={"page": i}))
        return pages


register(".pdf", PdfLoader())
