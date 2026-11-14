"""Compiled procedure index: one JSON file, published atomically (FEAT-891)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.procedure.models import INDEX_FILE, INDEX_SCHEMA_VERSION, ProbeCost, ProcedureSpec

_MANIFEST_DIR = Path("sdd") / "procedures"
_LOGGER = logging.getLogger(__name__)


def _sha1_file(path: Path) -> str:
    """sha1 hex digest of the file's bytes."""
    return hashlib.sha1(path.read_bytes()).hexdigest()  # noqa: S324 — content fingerprint, not security


def _relative_posix(path: Path, root: Path) -> str:
    """Return ``path`` relative to ``root`` as a POSIX string."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def compile_index(
    specs: Sequence[ProcedureSpec],
    sources: Sequence[Path],
    *,
    root: Path,
    probe_costs: Mapping[str, ProbeCost],
) -> dict[str, Any]:
    """Return the index document; 'generation' is the sha1 of its canonical JSON.

    Args:
        specs: Procedure specifications, in order.
        sources: Manifest files the specs were built from.
        root: Repository root that source paths are made relative to.
        probe_costs: Probe name to cost; an unknown probe is treated as remote.

    Returns:
        The index document including its ``generation`` key.
    """
    document: dict[str, Any] = {"schema_version": INDEX_SCHEMA_VERSION}
    entries = [{"path": _relative_posix(path, root), "sha1": _sha1_file(path)} for path in sources]
    document["sources"] = sorted(entries, key=lambda entry: entry["path"])

    guards: list[dict[str, Any]] = []
    procedures: dict[str, Any] = {}
    for spec in specs:
        for guard in spec.guards:
            scope: dict[str, dict[str, Any]] = {}
            for key, arg in guard.scope.items():
                scope[key] = {"argv": arg.argv} if arg.argv is not None else {"flag": arg.flag}
            guards.append(
                {
                    "procedure": spec.id,
                    "kind": guard.kind,
                    "executable": guard.executable,
                    "argv_prefix": list(guard.argv_prefix),
                    "path_globs": list(guard.path_globs),
                    "scope": scope,
                }
            )
        procedures[spec.id] = {
            "title": spec.title,
            "mode": spec.mode,
            "command": spec.command,
            "use_instead": spec.use_instead,
            "advice": spec.advice,
            "preconditions": [
                {
                    "probe": check.probe,
                    "expect": check.expect,
                    "args": dict(check.args),
                    "cost": probe_costs.get(check.probe, "remote"),
                }
                for check in spec.preconditions
            ],
        }
    document["guards"] = guards
    document["procedures"] = procedures

    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    document["generation"] = hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324
    return document


def publish_index(plane_dir: Path, document: Mapping[str, Any]) -> Path:
    """Write procedures.json via a temp file in plane_dir + os.replace; return the path."""
    plane_dir.mkdir(parents=True, exist_ok=True)
    target = plane_dir / INDEX_FILE
    fd, tmp_name = tempfile.mkstemp(dir=plane_dir, prefix=f".{INDEX_FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _LOGGER.debug("published procedure index %s generation=%s", target, document.get("generation"))
    return target


def read_index(plane_dir: Path) -> dict[str, Any] | None:
    """Return the document, or None when absent, unreadable or of another schema version."""
    try:
        payload = json.loads((plane_dir / INDEX_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != INDEX_SCHEMA_VERSION:
        return None
    return payload


def is_stale(document: Mapping[str, Any] | None, *, root: Path) -> bool:
    """True when document is None, a listed source is missing or its sha1 differs, or a manifest
    under sdd/procedures is not listed."""
    if document is None:
        return True
    listed: set[str] = set()
    for entry in document.get("sources", []):
        path = entry.get("path", "")
        listed.add(path)
        file_path = root / path
        try:
            if _sha1_file(file_path) != entry.get("sha1"):
                return True
        except OSError:
            return True
    manifest_dir = root / _MANIFEST_DIR
    if manifest_dir.is_dir():
        for found in manifest_dir.glob("*.yaml"):
            if _relative_posix(found, root) not in listed:
                return True
    return False
