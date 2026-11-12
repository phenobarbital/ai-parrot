"""Chart-of-accounts snapshot builders (FEAT-713 M4). Never opens a connection."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import yaml

from .models import ChartAccount, ChartSnapshot

if TYPE_CHECKING:
    import pyarrow as pa


def _text(value: Any) -> str | None:
    """Return *value* as a stripped string, or None when it is missing or blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tags(value: Any) -> tuple[str, ...]:
    """Normalise a tag list or a comma-separated string to a sorted, de-duplicated tuple."""
    if value is None:
        return ()
    items = value.split(",") if isinstance(value, str) else list(value)
    return tuple(sorted({text for text in (_text(item) for item in items) if text}))


def snapshot_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    account_key: str,
    nature_column: str | None,
    parent_column: str | None = None,
    tags_column: str | None = None,
    source: str,
    taken_at: date,
) -> ChartSnapshot:
    """Build the sorted, hashed snapshot from account-master rows (dict rows from the executor).

    Args:
        rows: Account-master rows, one mapping per account.
        account_key: Column holding the account id.
        nature_column: Column holding the account nature (``debit``/``credit``, any case); None when the
            account master carries no nature.
        parent_column: Optional column holding the parent account id.
        tags_column: Optional column holding tags (a list or a comma-separated string).
        source: Provenance label recorded on the snapshot.
        taken_at: Date the account master was read.

    Returns:
        The snapshot, accounts sorted by account id.

    Raises:
        ValueError: A row lacks an account id, carries an invalid nature, or an account id repeats.
    """
    accounts: dict[str, ChartAccount] = {}
    for index, row in enumerate(rows):
        account_id = _text(row.get(account_key))
        if account_id is None:
            raise ValueError(f"row {index} has no value for account column {account_key!r}")
        if account_id in accounts:
            raise ValueError(f"duplicate account id {account_id!r} in the account master")
        nature = _text(row.get(nature_column)) if nature_column is not None else None
        accounts[account_id] = ChartAccount(
            account_id=account_id,
            nature=nature.lower() if nature is not None else None,  # type: ignore[arg-type]
            parent_id=_text(row.get(parent_column)) if parent_column is not None else None,
            tags=_tags(row.get(tags_column)) if tags_column is not None else (),
        )
    ordered = tuple(accounts[account_id] for account_id in sorted(accounts))
    return ChartSnapshot(accounts=ordered, taken_at=taken_at, source=source)


def snapshot_from_arrow(
    table: "pa.Table",
    *,
    account_key: str,
    nature_column: str | None,
    parent_column: str | None = None,
    tags_column: str | None = None,
    source: str,
    taken_at: date,
) -> ChartSnapshot:
    """Same as snapshot_from_rows over ``table.to_pylist()``.

    Args:
        table: Arrow table of account-master rows.
        account_key: Column holding the account id.
        nature_column: Column holding the account nature, or None.
        parent_column: Optional column holding the parent account id.
        tags_column: Optional column holding tags.
        source: Provenance label recorded on the snapshot.
        taken_at: Date the account master was read.

    Returns:
        The snapshot, accounts sorted by account id.
    """
    return snapshot_from_rows(
        table.to_pylist(),
        account_key=account_key,
        nature_column=nature_column,
        parent_column=parent_column,
        tags_column=tags_column,
        source=source,
        taken_at=taken_at,
    )


def _mtime_date(path: Path) -> date:
    """Calendar date of the file's last modification."""
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _manifest_date(value: Any, path: Path) -> date:
    """Parse the manifest ``taken_at``; fall back to the file modification date when absent."""
    if value is None:
        return _mtime_date(path)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def snapshot_from_manifest(path: Path) -> ChartSnapshot:
    """YAML (``taken_at`` + ``accounts`` list) or CSV (columns account_id, nature, parent_id, tags) manifest.

    Args:
        path: ``.yaml``/``.yml`` or ``.csv`` manifest file.

    Returns:
        The snapshot, with ``source`` set to ``manifest:<path>``.

    Raises:
        ValueError: Unsupported suffix or malformed manifest.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("accounts"), list):
            raise ValueError(f"manifest {str(path)!r} needs a mapping with an 'accounts' list")
        rows = document["accounts"]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"manifest {str(path)!r}: every entry of 'accounts' must be a mapping")
        taken_at = _manifest_date(document.get("taken_at"), path)
    elif suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        taken_at = _mtime_date(path)
    else:
        raise ValueError(f"unsupported manifest suffix {path.suffix!r}; expected .yaml, .yml or .csv")
    return snapshot_from_rows(
        rows,
        account_key="account_id",
        nature_column="nature",
        parent_column="parent_id",
        tags_column="tags",
        source=f"manifest:{path}",
        taken_at=taken_at,
    )
