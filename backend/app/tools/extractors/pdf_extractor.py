from __future__ import annotations
from pathlib import Path
import fitz  # PyMuPDF

MAX_CHARS_PER_CHUNK = 1200


def split_text(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for para in text.split("\n"):
        if len(current) + len(para) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current += "\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def extract_pdf(path: Path) -> list[dict]:
    items: list[dict] = []
    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            for chunk_index, chunk in enumerate(split_text(text), start=1):
                items.append({
                    "text": chunk,
                    "section": f"Page {page_index}" if chunk_index == 1 else f"Page {page_index}, chunk {chunk_index}",
                    "page_number": page_index,
                    "extraction_method": "pymupdf",
                })
    return items
