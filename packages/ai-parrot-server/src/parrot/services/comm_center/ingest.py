"""Recipient ingestion — normalize the three CommCenter transports.

``ingest_recipients`` is the single entry point that turns any of the three
accepted transports (inline JSON rows, a multipart-uploaded file already
saved to disk by ``BaseHandler.handle_upload``, or a base64-decoded file's
raw bytes) into an identical ``list[RecipientIn]`` (spec §2 G2, §3 Module 4).

Column names are normalized case-insensitively, trimmed, and alias-mapped
(``e-mail`` -> ``email``, ``nombre`` -> ``name``, etc.); any column beyond
the canonical five is preserved verbatim in ``RecipientIn.extra`` so it
becomes a valid pass-2 placeholder downstream. All ``pandas`` parsing runs
off the event loop via ``asyncio.to_thread`` — never call it directly.
"""
import asyncio
import math
from io import BytesIO
from pathlib import Path

import pandas as pd

from .models import RecipientIn

#: Maximum accepted upload size, matching the repo convention
#: (``handlers/datasets.py:40``, ``handlers/infographic_render.py:63``).
MAX_FILE_SIZE = 50 * 1024 * 1024

#: Hard cap on recipients per batch (spec G10).
MAX_RECIPIENTS = 10_000

#: Case-insensitive, trimmed alias map -> canonical column name.
_ALIASES: dict[str, str] = {
    "e-mail": "email",
    "e mail": "email",
    "correo": "email",
    "nombre": "name",
    "teléfono": "phone",
    "telefono": "phone",
    "mobile": "phone",
    "cell": "phone",
    "user": "username",
    "usuario": "username",
    "direccion": "address",
    "dirección": "address",
}

#: All fields ``RecipientIn`` recognizes as canonical (not forwarded to ``extra``).
_CANONICAL_FIELDS = frozenset(
    {"name", "username", "email", "phone", "address", "provider"}
)

#: The subset whose *presence* (any one of them) is required for a file to
#: be accepted at all (spec §3 Module 4 implementation notes).
_REQUIRED_CANDIDATE_FIELDS = frozenset({"name", "username", "email", "phone"})

#: Names bound by Notify's own render context (spec §2) — a column reusing
#: one of these shadows that binding and must be flagged, not silently used.
_RESERVED_NAMES = frozenset({"recipient", "message", "subject"})


class IngestionError(ValueError):
    """Base class for all recipient-ingestion validation failures."""


class FileTooLargeError(IngestionError):
    """Raised when the uploaded payload exceeds :data:`MAX_FILE_SIZE`."""


class RecipientCapExceededError(IngestionError):
    """Raised when the parsed row count exceeds :data:`MAX_RECIPIENTS`."""


def _normalize_column(column: str) -> str:
    """Normalize a raw column/key name to its canonical form.

    Args:
        column: The raw column or dict key as found in the source data.

    Returns:
        The case-insensitive, trimmed, alias-mapped canonical name, or the
        trimmed lower-cased original when there is no alias.
    """
    key = str(column).strip().lower()
    return _ALIASES.get(key, key)


def _clean_value(value):
    """Coerce pandas' NaN/blank-string cells to ``None``.

    Args:
        value: A raw cell value from a parsed row (JSON, CSV, or Excel).

    Returns:
        ``None`` for NaN/blank values; the original value otherwise.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _check_file_size(size: int) -> None:
    """Raise :class:`FileTooLargeError` when ``size`` exceeds the cap.

    Args:
        size: The payload size in bytes.
    """
    if size > MAX_FILE_SIZE:
        raise FileTooLargeError(
            f"Uploaded file is {size} bytes, exceeding the "
            f"{MAX_FILE_SIZE // (1024 * 1024)}MB cap"
        )


def _dataframe_from_path_sync(path: Path) -> pd.DataFrame:
    """Blocking: read a CSV/XLSX file at ``path`` into a DataFrame.

    Every column is read as ``str`` — recipient fields (phone numbers in
    particular) must never be silently coerced to numeric dtypes, which
    would strip a leading ``+`` or leading zeros.
    """
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl", dtype=str)
    return pd.read_csv(path, dtype=str)


def _dataframe_from_bytes_sync(data: bytes, suffix: str) -> pd.DataFrame:
    """Blocking: read raw CSV/XLSX ``data`` (already-decoded bytes) into a DataFrame.

    See :func:`_dataframe_from_path_sync` — every column is read as ``str``.
    """
    buffer = BytesIO(data)
    if suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(buffer, engine="openpyxl", dtype=str)
    return pd.read_csv(buffer, dtype=str)


def _rows_from_path_sync(path: Path) -> list[dict]:
    """Blocking: parse ``path`` and return its rows as plain dicts."""
    return _dataframe_from_path_sync(path).to_dict(orient="records")


def _rows_from_bytes_sync(data: bytes, suffix: str) -> list[dict]:
    """Blocking: parse raw ``data`` and return its rows as plain dicts."""
    return _dataframe_from_bytes_sync(data, suffix).to_dict(orient="records")


def _row_to_recipient(raw: dict, reserved_used: set) -> RecipientIn:
    """Normalize one raw row dict into a :class:`RecipientIn`.

    Args:
        raw: A single raw row (JSON object, or a parsed CSV/Excel record).
        reserved_used: Accumulator of reserved column names encountered
            across the whole batch (mutated in place).

    Returns:
        The normalized :class:`RecipientIn`.
    """
    canonical: dict = {}
    extra: dict = {}
    for key, value in raw.items():
        norm = _normalize_column(key)
        cleaned = _clean_value(value)
        if norm in _RESERVED_NAMES:
            reserved_used.add(norm)
        if norm in _CANONICAL_FIELDS:
            canonical[norm] = cleaned
        else:
            extra[norm] = cleaned
    return RecipientIn(
        name=canonical.get("name"),
        username=canonical.get("username"),
        email=canonical.get("email"),
        phone=canonical.get("phone"),
        address=canonical.get("address"),
        provider=canonical.get("provider"),
        extra=extra,
    )


async def ingest_recipients(
    *,
    rows: list[dict] | None = None,
    file_path: str | Path | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    return_warnings: bool = False,
) -> list[RecipientIn] | tuple[list[RecipientIn], list[str]]:
    """Normalize any one of the three CommCenter transports into recipients.

    Exactly one of ``rows``, ``file_path``, or ``file_bytes`` must be
    provided. ``file_path`` is the multipart transport (the handler already
    wrote the upload to a temp file via ``BaseHandler.handle_upload``);
    ``file_bytes`` is the base64-embedded transport (already decoded by the
    caller); ``rows`` is the inline-JSON transport.

    Args:
        rows: Inline JSON recipient rows (list of plain dicts).
        file_path: Path to a CSV/XLSX file already saved to disk.
        file_bytes: Raw (already base64-decoded) CSV/XLSX file content.
        filename: Original filename for ``file_bytes``, used to pick the
            CSV vs. Excel parser. Required when ``file_bytes`` is given.
        return_warnings: When ``True``, return ``(recipients, warnings)``
            instead of just ``recipients``.

    Returns:
        The normalized recipients, or a ``(recipients, warnings)`` tuple
        when ``return_warnings`` is ``True``.

    Raises:
        FileTooLargeError: The payload exceeds :data:`MAX_FILE_SIZE`.
        RecipientCapExceededError: More than :data:`MAX_RECIPIENTS` rows.
        IngestionError: The file is empty, or has none of the recognized
            recipient columns.
    """
    if rows is not None:
        raw_rows = list(rows)
    elif file_path is not None:
        path = Path(file_path)
        _check_file_size(path.stat().st_size)
        raw_rows = await asyncio.to_thread(_rows_from_path_sync, path)
    elif file_bytes is not None:
        if not filename:
            raise IngestionError(
                "filename is required to ingest recipients from file_bytes"
            )
        _check_file_size(len(file_bytes))
        raw_rows = await asyncio.to_thread(
            _rows_from_bytes_sync, file_bytes, Path(filename).suffix
        )
    else:
        raise IngestionError(
            "one of rows, file_path, or file_bytes must be provided"
        )

    if not raw_rows:
        raise IngestionError("0 recipients: the source contains no data rows")

    if len(raw_rows) > MAX_RECIPIENTS:
        raise RecipientCapExceededError(
            f"{len(raw_rows)} recipients exceeds the {MAX_RECIPIENTS} "
            "(10 000) per-batch cap"
        )

    normalized_keys = {_normalize_column(key) for row in raw_rows for key in row}
    if not normalized_keys & _REQUIRED_CANDIDATE_FIELDS:
        raise IngestionError(
            "No recognized recipient columns found; expected at least one "
            f"of {sorted(_REQUIRED_CANDIDATE_FIELDS)}"
        )

    reserved_used: set = set()
    recipients = [_row_to_recipient(row, reserved_used) for row in raw_rows]

    warnings = [
        f"Column '{name}' shadows a reserved placeholder name and will not "
        "be applied as a recipient field."
        for name in sorted(reserved_used)
    ]

    if return_warnings:
        return recipients, warnings
    return recipients
