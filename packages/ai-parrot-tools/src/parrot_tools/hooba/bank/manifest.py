"""Per-statement import manifest for resume and reconciliation (FEAT-602 M8)."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from parrot_tools.business_automation.ingest import checkpoint_dir_for

_OPERATION = "hooba_bbva_import"


class ImportManifest(BaseModel):
    """Progress of one statement import; ``completed`` maps row_id → purchase_invoice_id."""

    statement_digest: str
    period: str
    started_at: dt.datetime
    row_count: int
    completed: Dict[str, int] = Field(default_factory=dict)
    skipped: Dict[str, str] = Field(default_factory=dict)


def manifest_path_for(digest: str) -> Path:
    """``$PARROT_STATE_DIR/business_automation/checkpoints/hooba_bbva_import/<digest>.manifest.json``."""
    return checkpoint_dir_for(_OPERATION) / f"{digest}.manifest.json"


def load_manifest(digest: str) -> Optional[ImportManifest]:
    """Load a prior manifest or return None. Sync — call via asyncio.to_thread."""
    path = manifest_path_for(digest)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ImportManifest.model_validate(data)


def write_manifest(manifest: ImportManifest) -> Path:
    """Atomic write, file mode 0o600. Sync — call via asyncio.to_thread."""
    path = manifest_path_for(manifest.statement_digest)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    return path


def reconcile(manifest: ImportManifest, planned_rows: int) -> Dict[str, Any]:
    """``{rows_in, drafts_out, skipped, delta, reconciled}`` — reconciled iff delta == 0.

    ``rows_in`` is always ``manifest.row_count`` — the whole statement's stable, persisted
    total — never the caller's ``planned_rows`` (this-run's newly-planned count). On a
    resumed or fully-complete re-run, ``planned_rows`` only reflects the remainder this run
    actually had left to do (often 0), while ``manifest.completed``/``manifest.skipped`` are
    cumulative across every run; using ``planned_rows`` for ``rows_in`` would make a correct,
    fully-reconciled resume falsely report ``reconciled=False``. Mirrors the equivalent,
    explicitly-documented convention in
    ``business_automation/ingest.py:reconcile()`` (``bundle.row_count`` there, never
    ``registrations_out`` alone). ``planned_rows`` is retained in the signature per the
    spec's declared contract; it is intentionally not used for ``rows_in``.
    """
    rows_in = manifest.row_count
    drafts_out = len(manifest.completed)
    skipped = len(manifest.skipped)
    delta = rows_in - drafts_out - skipped
    return {
        "rows_in": rows_in,
        "drafts_out": drafts_out,
        "skipped": skipped,
        "delta": delta,
        "reconciled": delta == 0,
    }
