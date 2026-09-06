"""Atomic per-plane local enrichment digest state (FEAT-532 TASK-2909).

Tracks, per Luau source file, the last
:attr:`~parrot.knowledge.wiki.roblox.models.RobloxFileEnrichment.dependency_digest`
enrichment was computed against — one small JSON file inside the ACTIVE
LOCAL PLANE's own storage directory (``<storage_dir>/roblox-enrichment.json``),
written atomically (temp file + ``os.replace``, matching the convention
already used by ``project.py``'s ``save_global_registry``/
``roblox/generations.py``'s pointer writes).

Deliberately a **separate** file from the source manifest's raw file
hashes (``sources.py``) — this state answers "did the enrichment
*context* (mapping/catalog/renderer schema/namespace) change", never
"did the file's bytes change", and must never be confused with or
overwrite that unrelated structural-freshness state.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STATE_FILENAME = "roblox-enrichment.json"


def state_path(storage_dir: Path) -> Path:
    """Path of the digest state file inside one plane's storage directory."""
    return storage_dir / STATE_FILENAME


def load_state(storage_dir: Path) -> dict[str, str]:
    """Load the ``rel_path -> last-recorded dependency_digest`` map.

    Never raises: a missing, unreadable, or malformed state file is
    treated identically to "nothing recorded yet" (every Luau file then
    looks like it needs enrichment, which is the safe default — a false
    "needs enrichment" costs a re-render, a false "up to date" would
    silently skip a real change).
    """
    path = state_path(storage_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_state(storage_dir: Path, state: dict[str, str]) -> None:
    """Atomically persist the full digest map.

    Writes to a temp file in the same directory, then ``os.replace``s it
    into place — a crash mid-write can never leave a truncated or
    half-written state file behind.
    """
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = state_path(storage_dir)
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(storage_dir), prefix=".roblox-enrichment-", suffix=".json")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def files_needing_enrichment(candidates: dict[str, str], stored: dict[str, str]) -> set[str]:
    """rel_paths whose freshly computed digest differs from (or was never
    recorded in) ``stored`` — these need enrichment even when their
    source bytes are byte-for-byte unchanged, because the mapping, the
    active API generation, the renderer schema, or the configured
    namespace changed underneath them.

    Args:
        candidates: ``rel_path -> freshly computed dependency_digest``
            for every Luau file in the current scan.
        stored: The previously recorded state (:func:`load_state`).

    Returns:
        The set of rel_paths needing enrichment.
    """
    return {rel for rel, digest in candidates.items() if stored.get(rel) != digest}
