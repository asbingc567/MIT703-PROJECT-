"""Read raw records from CSV and JSON files.

This module only reads files and reports file-level problems. Checking
the content of each record is the job of ``data_processor``.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Refuse very large files so a mistaken input cannot exhaust memory.
MAX_FILE_BYTES = 50 * 1024 * 1024
SUPPORTED_SUFFIXES = (".csv", ".json")

# A raw record is (row number in the source file, field dictionary).
RawRecord = tuple[int, Any]


class DataLoadError(Exception):
    """Raised when an input file cannot be opened, read or parsed."""


def load_records(
    path: Path, required_fields: tuple[str, ...] = ()
) -> list[RawRecord]:
    """Load every record from a CSV or JSON file.

    Args:
        path: File to read. The format is chosen from the file extension.
        required_fields: Column names a CSV header must contain.

    Returns:
        A list of ``(row_number, record)`` tuples.

    Raises:
        DataLoadError: If the file is missing, too large, has an
            unsupported extension, or cannot be parsed.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DataLoadError(
            f"{path.name}: unsupported file type {suffix!r} "
            f"(expected one of {', '.join(SUPPORTED_SUFFIXES)})"
        )
    _check_file(path)
    logger.info("Loading %s", path.name)
    if suffix == ".csv":
        records = _load_csv(path, required_fields)
    else:
        records = _load_json(path)
    logger.info("Read %d record(s) from %s", len(records), path.name)
    return records


def _check_file(path: Path) -> None:
    """Make sure the path is an existing, readable file of sensible size."""
    if not path.exists():
        raise DataLoadError(f"File not found: {path}")
    if not path.is_file():
        raise DataLoadError(f"Not a file: {path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise DataLoadError(
            f"{path.name} is {size} bytes, which exceeds the "
            f"{MAX_FILE_BYTES}-byte limit"
        )


def _load_csv(path: Path, required_fields: tuple[str, ...]) -> list[RawRecord]:
    """Read a CSV file row by row with ``csv.DictReader``."""
    records: list[RawRecord] = []
    try:
        # utf-8-sig strips the byte-order mark that Excel adds to CSVs.
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            header = [h.strip() for h in (reader.fieldnames or [])]
            if not header:
                raise DataLoadError(f"{path.name}: file is empty")
            reader.fieldnames = header
            missing = [f for f in required_fields if f not in header]
            if missing:
                raise DataLoadError(
                    f"{path.name}: missing required column(s): "
                    f"{', '.join(missing)}"
                )
            if len(set(header)) != len(header):
                raise DataLoadError(f"{path.name}: duplicate column names")
            # Data starts on line 2 because line 1 is the header.
            for row_number, row in enumerate(reader, start=2):
                records.append((row_number, row))
    except PermissionError as exc:
        raise DataLoadError(f"Permission denied: {path}") from exc
    except UnicodeDecodeError as exc:
        raise DataLoadError(f"{path.name}: file is not UTF-8 text") from exc
    except csv.Error as exc:
        raise DataLoadError(f"{path.name}: malformed CSV ({exc})") from exc
    return records


def _load_json(path: Path) -> list[RawRecord]:
    """Read a JSON file holding a list of objects.

    A top-level object with a ``"records"`` list is also accepted.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except PermissionError as exc:
        raise DataLoadError(f"Permission denied: {path}") from exc
    except UnicodeDecodeError as exc:
        raise DataLoadError(f"{path.name}: file is not UTF-8 text") from exc
    except json.JSONDecodeError as exc:
        raise DataLoadError(
            f"{path.name}: invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}"
        ) from exc

    if isinstance(data, dict) and isinstance(data.get("records"), list):
        data = data["records"]
    if not isinstance(data, list):
        raise DataLoadError(
            f"{path.name}: expected a JSON list of records "
            "(or an object with a 'records' list)"
        )
    return list(enumerate(data, start=1))
