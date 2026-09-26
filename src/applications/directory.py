"""Load the board directory."""

import csv
from pathlib import Path

from applications.models import Board


def load_boards(path: Path) -> list[Board]:
    boards: list[Board] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            vendor = (row.get("ats_vendor") or "").strip().lower()
            slug = (row.get("board_slug") or "").strip()
            if vendor not in {"greenhouse", "ashby", "lever"} or not slug:
                continue
            boards.append(
                Board(
                    vendor=vendor,
                    company_name=(row.get("company_name") or "").strip(),
                    slug=slug,
                    source=(row.get("source") or "").strip(),
                    source_date=(row.get("source_date") or "").strip(),
                    confirmed=(row.get("confirmed") or "").strip(),
                    http_status=(row.get("http_status") or "").strip(),
                )
            )
    return boards
