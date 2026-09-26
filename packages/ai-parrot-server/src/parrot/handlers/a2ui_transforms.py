"""Publish catalogued A2UI ``transform.ref`` modules into STATIC_DIR (FEAT-598 M9).

Files land in ``STATIC_DIR/a2ui/transforms/`` and are served anonymously by the existing
``add_static("/static/", …)`` route. Sync by design — call via ``run_in_executor`` from async code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import shutil
from pathlib import Path

from parrot.outputs.a2ui.linked.manifest import (
    ManifestEntry,
    TransformManifest,
    default_manifest_path,
    sign_entries,
)

logger = logging.getLogger(__name__)

_MODULE_RE = re.compile(r"^(?P<id>[a-z0-9_-]+@\d+\.\d+\.\d+)\.js$")


def compute_sri(data: bytes) -> str:
    """Return the W3C SRI string ``sha384-<base64>`` for ``data``."""
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")


def _load_existing(path: Path, key: str) -> TransformManifest:
    """Return the verified existing manifest, or an empty one when absent."""
    if not path.exists():
        return TransformManifest()
    manifest = TransformManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if not hmac.compare_digest(manifest.signature, sign_entries(manifest.entries, key)):
        raise ValueError(f"existing manifest {path} failed signature verification; refusing to re-sign")
    return manifest


def publish_transforms(source_dir: Path, *, key: str) -> TransformManifest:
    """Copy ``<name>@<version>.js`` modules from ``source_dir``, compute SRI, write + sign ``manifest.json``.

    Never deletes existing versions (retirement = ``deprecated: true``); refuses to overwrite a
    published version with different bytes.

    Args:
        source_dir: Directory containing ``<name>@<semver>.js`` module files to publish.
        key: The HMAC signing key (must be non-empty).

    Returns:
        The signed :class:`TransformManifest` now on disk.

    Raises:
        ValueError: empty key, tampered manifest, or an immutable version would change.
    """
    if not key:
        raise ValueError("publish_transforms requires a non-empty manifest key")
    manifest_path = default_manifest_path()
    dest = manifest_path.parent
    dest.mkdir(parents=True, exist_ok=True)
    manifest = _load_existing(manifest_path, key)
    entries: dict[str, ManifestEntry] = dict(manifest.entries)
    for src in sorted(Path(source_dir).glob("*.js")):
        match = _MODULE_RE.match(src.name)
        if match is None:
            logger.warning("skipping %s: not '<name>@<semver>.js'", src.name)
            continue
        module_id = match.group("id")
        data = src.read_bytes()
        target = dest / src.name
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError(f"published version {src.name} is immutable; bytes differ from {target}")
        else:
            shutil.copyfile(src, target)
        existing_entry = entries.get(module_id)
        entries[module_id] = ManifestEntry(
            file=src.name,
            integrity=compute_sri(data),
            deprecated=existing_entry.deprecated if existing_entry is not None else False,
        )
    signed = TransformManifest(entries=entries, signature=sign_entries(entries, key))
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(signed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)
    logger.info("published %d transform module(s) to %s", len(entries), dest)
    return signed
