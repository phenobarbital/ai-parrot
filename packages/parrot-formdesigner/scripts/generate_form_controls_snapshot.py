#!/usr/bin/env python3
"""Regenerate (or check) the committed ``form-controls`` catalog snapshot.

FEAT-448 (TASK-2338): the ``GET /api/v1/form-controls`` catalog is the
single source of truth for every ``FieldType``'s metadata and value-shape
contract — the client half (navigator-svelte FEAT-515 AC7) must be able to
read it without hand-copying it into a second, driftable list. CI can't
always boot a live aiohttp server to hit that endpoint, so this script
regenerates a deterministic JSON snapshot of the same catalog data for
consumption without one.

The snapshot is a generated artifact, not a hand-maintained fixture: run
this script to refresh it whenever ``controls/builtin.py`` or the JSON
Schema renderer's per-type maps change, and run it with ``--check`` in CI
so a stale snapshot fails the build instead of silently drifting (spec
§5.5, AC7).

Usage::

    python scripts/generate_form_controls_snapshot.py            # regenerate
    python scripts/generate_form_controls_snapshot.py --check    # verify freshness (CI)
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

# Add the package src to sys.path so the script can import without installing
_SCRIPT_DIR = Path(__file__).resolve().parent
_PACKAGE_SRC = _SCRIPT_DIR.parent / "src"
if str(_PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SRC))

SNAPSHOT_PATH = _SCRIPT_DIR.parent / "tests" / "fixtures" / "form_controls_snapshot.json"


def compute_snapshot() -> dict:
    """Compute the current catalog, exactly as ``GET /api/v1/form-controls``
    would serve it, re-seeded fresh from ``controls/builtin.py``.

    Returns:
        ``{"controls": [...]}`` with entries sorted by ``type`` for a
        deterministic diff regardless of registration order.
    """
    from parrot_formdesigner.controls.registry import _REGISTRY, get_controls

    _REGISTRY.clear()
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    controls = [c.model_dump(mode="json") for c in get_controls()]
    controls.sort(key=lambda c: c["type"])
    return {"controls": controls}


def render_snapshot_text(snapshot: dict) -> str:
    """Render a snapshot dict to its committed textual form (stable, diffable)."""
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the committed snapshot is stale.",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point. Returns a process exit code."""
    args = _parse_args()
    fresh_text = render_snapshot_text(compute_snapshot())

    if args.check:
        if not SNAPSHOT_PATH.exists():
            print(f"MISSING: {SNAPSHOT_PATH}", file=sys.stderr)
            return 1
        committed_text = SNAPSHOT_PATH.read_text()
        if committed_text != fresh_text:
            print(
                f"STALE: {SNAPSHOT_PATH} does not match the current "
                "form-controls catalog. Run "
                "`python scripts/generate_form_controls_snapshot.py` to "
                "regenerate it and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {SNAPSHOT_PATH} is fresh.")
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(fresh_text)
    print(f"Wrote {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
