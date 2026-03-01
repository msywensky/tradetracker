from __future__ import annotations

import re
from datetime import datetime

DEFAULT_SYMBOL = "UNK"
SYMBOL_PATTERN = re.compile(r"\b(SPY|TSLA|MSFT|NBIS)\b", re.IGNORECASE)

DATE_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M %p",
    "%m/%d %I:%M %p",
    "%m/%d/%Y",
    "%m/%d",
]
YEARLESS_FORMATS = {"%m/%d %I:%M %p", "%m/%d"}


def normalize_header(value: str) -> str:
    return " ".join(value.strip().lower().split())


def parse_money(value: str) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    raw = raw.replace("$", "").replace(",", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    if value is None:
        return None
    raw = value.strip().replace(",", "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_datetime(value: str, default_year: int | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    for fmt in DATE_FORMATS:
        try:
            if fmt in YEARLESS_FORMATS:
                if default_year is None:
                    continue
                dt = datetime.strptime(f"{default_year}/{raw}", f"%Y/{fmt}")
            else:
                dt = datetime.strptime(raw, fmt)
            if dt.year == 1900 and default_year is not None:
                dt = dt.replace(year=default_year)
            return dt
        except ValueError:
            continue
    return None


def infer_symbol_from_notes(notes: str) -> str:
    if not notes:
        return DEFAULT_SYMBOL

    match = SYMBOL_PATTERN.search(notes)
    if not match:
        return DEFAULT_SYMBOL

    return match.group(1).upper()
