"""Shared OCR helper (Tesseract).

One place that turns image bytes into text, used by every loader that needs OCR
(PDF scanned pages, images embedded in DOCX, etc.). Keeping it here means the OCR
engine can be swapped in a single file without touching any loader.

Requires the system package `tesseract-ocr` (installed in the Dockerfile) plus
the Python packages `pytesseract` and `Pillow`.
"""
import io

from app.core.logging import get_logger

log = get_logger(__name__)


def ocr_image_bytes(image_bytes: bytes) -> str:
    """Return the text Tesseract reads from a PNG/JPEG image.

    Never raises: OCR failure on one image must not stop ingestion of the whole
    document — it just yields an empty string for that image.
    """
    try:
        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            return pytesseract.image_to_string(img).strip()
    except Exception as exc:
        log.error("Tesseract OCR failed on an image: %s", exc)
        return ""
