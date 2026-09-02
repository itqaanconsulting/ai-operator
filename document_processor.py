import hashlib
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_MODEL_CHARACTERS = 100_000
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def extract_document(filename: str, data: bytes) -> tuple[str, str]:
    if not filename:
        raise ValueError("A filename is required")
    extension = Path(filename).suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("Supported file types are PDF, DOCX, and TXT")
    if not data:
        raise ValueError("The uploaded document is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("The uploaded document exceeds the 10 MB limit")

    if extension == ".pdf":
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif extension == ".docx":
        document = Document(BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs]
        parts.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        text = "\n".join(parts)
    else:
        text = data.decode("utf-8-sig", errors="replace")

    text = text.strip()
    if not text:
        raise ValueError(
            "No extractable text was found. Scanned PDFs require OCR, which is not yet supported."
        )
    return text[:MAX_MODEL_CHARACTERS], hashlib.sha256(data).hexdigest()
