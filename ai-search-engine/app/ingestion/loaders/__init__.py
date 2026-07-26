"""Import every loader module so its self-registration (see base.register())
actually runs. Implemented loaders (docx, pdf) register themselves on import;
stub loaders (pptx, txt, xlsx) leave their register() call commented out
until implemented, so importing them here is a harmless no-op.
"""
from app.ingestion.loaders import (  # noqa: F401
    docx_loader,
    pdf_loader,
    pptx_loader,
    txt_loader,
    xlsx_loader,
)
