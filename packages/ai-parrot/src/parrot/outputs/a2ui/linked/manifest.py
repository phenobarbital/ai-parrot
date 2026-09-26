"""Signed manifest of catalogued ``transform.ref`` modules (FEAT-598 M9, S6, AC9)."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.outputs.a2ui.linked.models import TransformRef

logger = logging.getLogger(__name__)

MANIFEST_KEY_ENV = "PARROT_A2UI_MANIFEST_KEY"
_ID_RE = re.compile(r"^[a-z0-9_-]+@\d+\.\d+\.\d+$")


class ManifestEntry(BaseModel):
    """One published module: file name (relative, ``<id>.js``), SRI integrity, deprecation flag."""

    model_config = ConfigDict(extra="forbid")
    file: str
    integrity: str
    deprecated: bool = False


class TransformManifest(BaseModel):
    """``{version: 1, entries: {id: ManifestEntry}, signature}`` — no absolute URLs anywhere (S6)."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    entries: dict[str, ManifestEntry] = Field(default_factory=dict)
    signature: str = ""

    @model_validator(mode="after")
    def _check_entries(self) -> TransformManifest:
        for key, entry in self.entries.items():
            if not _ID_RE.match(key):
                raise ValueError(f"manifest entry key {key!r} must match '<name>@<semver>' (never a URL)")
            if entry.file != f"{key}.js":
                raise ValueError(f"manifest entry {key!r}.file must equal {key}.js (no path, no scheme)")
            if not entry.integrity.startswith("sha384-"):
                raise ValueError(f"manifest entry {key!r}.integrity must be a 'sha384-…' SRI hash")
        return self


def canonical_entries(entries: Mapping[str, ManifestEntry]) -> bytes:
    """Canonical bytes signed by the HMAC (sorted keys, compact separators, UTF-8)."""
    payload = {name: entry.model_dump(mode="json") for name, entry in entries.items()}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_entries(entries: Mapping[str, ManifestEntry], key: str) -> str:
    """Return the lowercase-hex HMAC-SHA256 of ``canonical_entries(entries)``."""
    return hmac.new(key.encode("utf-8"), canonical_entries(entries), hashlib.sha256).hexdigest()


def default_manifest_path() -> Path:
    """``STATIC_DIR/a2ui/transforms/manifest.json``."""
    from parrot.conf import STATIC_DIR  # local import: keep module import-light

    return Path(STATIC_DIR) / "a2ui" / "transforms" / "manifest.json"


def load_manifest(path: Path | None = None) -> TransformManifest | None:
    """Read and HMAC-verify the manifest; ``None`` when absent, invalid, unkeyed or tampered."""
    target = path or default_manifest_path()
    key = os.environ.get(MANIFEST_KEY_ENV, "")

    if not target.exists():
        logger.debug("transform manifest not found at %s", target)
        return None

    if not key:
        logger.warning("transform manifest key %s is unset; refusing to load %s", MANIFEST_KEY_ENV, target)
        return None

    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
        manifest = TransformManifest.model_validate(data)
    except Exception:
        logger.warning("transform manifest at %s is invalid", target, exc_info=True)
        return None

    expected = sign_entries(manifest.entries, key)
    if not hmac.compare_digest(manifest.signature, expected):
        logger.warning("transform manifest at %s failed signature verification", target)
        return None

    return manifest


def resolve_ref(name: str, manifest: TransformManifest) -> TransformRef:
    """Return ``TransformRef(name, integrity)`` for an opaque id; ``KeyError`` when missing."""
    entry = manifest.entries[name]
    if entry.deprecated:
        logger.warning("transform ref %s is deprecated", name)
    return TransformRef(name=name, integrity=entry.integrity)
