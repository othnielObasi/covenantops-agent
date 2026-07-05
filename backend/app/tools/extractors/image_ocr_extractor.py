from __future__ import annotations
from pathlib import Path
from PIL import Image
import pytesseract


def extract_image(path: Path) -> list[dict]:
    image = Image.open(path)
    text = pytesseract.image_to_string(image)
    confidence = None
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confs = [float(c) for c in data.get("conf", []) if str(c).strip() not in {"", "-1"}]
        if confs:
            confidence = round(sum(confs) / len(confs), 2)
    except Exception:  # noqa: BLE001 - confidence is optional
        confidence = None
    return [{
        "text": text.strip(),
        "section": "OCR text",
        "extraction_method": "pytesseract",
        "ocr_confidence": confidence,
    }] if text.strip() else []
