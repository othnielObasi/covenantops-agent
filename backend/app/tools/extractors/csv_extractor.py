from __future__ import annotations
from pathlib import Path
import csv

MAX_ROWS_PER_CHUNK = 60


def extract_csv(path: Path) -> list[dict]:
    items: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        rows: list[str] = []
        start_row = 2
        for index, row in enumerate(reader, start=2):
            line = " | ".join(f"{h}: {row.get(h, '')}" for h in headers)
            rows.append(line)
            if len(rows) >= MAX_ROWS_PER_CHUNK:
                items.append({"text": "\n".join(rows), "section": f"Rows {start_row}-{index}", "row_number": start_row, "extraction_method": "csv"})
                rows = []
                start_row = index + 1
        if rows:
            end = start_row + len(rows) - 1
            items.append({"text": "\n".join(rows), "section": f"Rows {start_row}-{end}", "row_number": start_row, "extraction_method": "csv"})
    return items
