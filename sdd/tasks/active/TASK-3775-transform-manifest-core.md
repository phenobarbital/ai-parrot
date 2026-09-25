# TASK-3775: TransformManifest loader/verifier + resolve_ref

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3769
**Assigned-to**: unassigned

---

## Context

`transform.ref` names a catalogued, renderer-side TypeScript module by an opaque `"<name>@<semver>"`
id, pinned by SRI and governed by an **HMAC-signed manifest** served from
`STATIC_DIR/a2ui/transforms/manifest.json` (spec §3 Module 9, S6, AC9). This task is the core
(loader/verifier) half: the model, the canonical signing function, `load_manifest()` and
`resolve_ref()`. TASK-3777 (surface validation) uses `load_manifest` to reject unknown refs
(`TRANSFORM_REF_UNKNOWN`); TASK-3776 (server) reuses `sign_entries` to publish.

---

## Scope

- Create `linked/manifest.py`: `ManifestEntry`, `TransformManifest`, `canonical_entries(entries) -> bytes`,
  `sign_entries(entries, key) -> str`, `load_manifest(path=None) -> TransformManifest | None`,
  `resolve_ref(name, manifest) -> TransformRef`, `default_manifest_path() -> Path`.
- Tests: signature verified / mismatch → `None`, missing key → `None`, deprecated → warning and still
  resolves, unknown → `KeyError`, entries never carry a URL.

**NOT in scope**: copying files / writing the manifest (TASK-3776); the validation hook (TASK-3777); the TS loader (TASK-3794).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/manifest.py` | CREATE | manifest model + loader/verifier |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_manifest.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.linked.models import TransformRef   # created by TASK-3769 (name regex ^[a-z0-9_-]+@\d+\.\d+\.\d+$, integrity "sha384-…")
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from parrot.conf import STATIC_DIR   # parrot/conf.py:51 — LOCAL import inside the function (infographic_render.py:649 precedent)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py:51
STATIC_DIR = config.get("STATIC_DIR", fallback=BASE_DIR.joinpath("static"))   # may be a str when configured → wrap in Path()

# packages/ai-parrot-server/src/parrot/handlers/infographic_render.py:632-663 publish_to_static_dir
#   `from parrot.conf import STATIC_DIR  # local import: keep module import-light` (L649); files served by add_static("/static/", …)
```

### Does NOT Exist
- ~~`PARROT_A2UI_MANIFEST_KEY` usage anywhere~~ — net-new env var (read from `os.environ` only, never config files).
- ~~`/static/a2ui/transforms/`, `manifest.json`~~ — net-new; only the generic `/static/` route exists.
- ~~`TransformRef.url`, absolute URLs in manifest entries~~ — forbidden (S6): a renderer joins `file` onto ITS configured base.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/manifest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_manifest.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Manifest JSON shape (binding; the UI loader in TASK-3794 reads the same file)
```json
{
  "version": 1,
  "entries": {
    "group_by_day@1.0.0": {"file": "group_by_day@1.0.0.js", "integrity": "sha384-…", "deprecated": false}
  },
  "signature": "<lowercase hex HMAC-SHA256>"
}
```
- `entries` keys match `^[a-z0-9_-]+@\d+\.\d+\.\d+$`; `file` MUST equal `f"{key}.js"` (no `/`, no scheme) — the validator enforces it.
- Signature = `hmac.new(key.encode(), canonical_entries(entries), hashlib.sha256).hexdigest()`, where
  `canonical_entries` = `json.dumps({k: e.model_dump(mode="json") for k, e in entries.items()}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
  Compare with `hmac.compare_digest`.
- `load_manifest` returns `None` (and logs one `warning`) when: the file is absent, JSON/model invalid,
  `PARROT_A2UI_MANIFEST_KEY` is unset/empty, or the signature does not verify. `None` ⇒ validation reports
  `TRANSFORM_REF_UNKNOWN` for every ref (TASK-3777). It never raises.
- `resolve_ref` raises `KeyError(name)` when absent; logs `warning` when `deprecated` and still returns.
- Sync file I/O is acceptable here: `validate_envelope` is sync and the file is tiny; do not cache
  (tests toggle the env key and files).

### Key Constraints
- Core module: no aiohttp, no server imports. `self.logger`-equivalent = module `logger = logging.getLogger(__name__)`.
- Secrets from environment only (`os.environ.get("PARROT_A2UI_MANIFEST_KEY")`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `manifest.py` — *why*: single definition of the signed-manifest contract for loader and publisher.
2. Write the tests with a local `manifest_file` fixture (signed via `sign_entries`) — *why*: the conftest from TASK-3769 must not grow.
3. Run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/manifest.py` (CREATE)
```python
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
        # FILL IN: every key matches _ID_RE, entry.file == f"{key}.js", entry.integrity startswith "sha384-"
        #          else ValueError — bounded by S6 (opaque ids, never URLs)
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
    # FILL IN: missing file → None (debug log); empty key → None (warning); parse JSON + model_validate
    #          (errors → None, warning); hmac.compare_digest(manifest.signature, sign_entries(manifest.entries, key))
    #          False → None (warning "signature mismatch"); else return manifest — bounded by AC9, never raises
    return None


def resolve_ref(name: str, manifest: TransformManifest) -> TransformRef:
    """Return ``TransformRef(name, integrity)`` for an opaque id; ``KeyError`` when missing."""
    entry = manifest.entries[name]
    if entry.deprecated:
        logger.warning("transform ref %s is deprecated", name)
    return TransformRef(name=name, integrity=entry.integrity)
```
**Why this shape**: `sign_entries`/`canonical_entries` are public so TASK-3776 signs with the exact same bytes;
the signature covers `entries` only (not `version`/`signature`), as spec M9 fixes.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_manifest.py` (CREATE)
```python
"""Tests for the signed transforms manifest (FEAT-598 M9)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from parrot.outputs.a2ui.linked.manifest import (
    MANIFEST_KEY_ENV, ManifestEntry, TransformManifest, load_manifest, resolve_ref, sign_entries,
)

KEY = "test-manifest-key"
SRI = "sha384-" + "A" * 64


@pytest.fixture
def manifest_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Signed manifest with group_by_day@1.0.0 and a deprecated group_by_day@0.9.0."""
    monkeypatch.setenv(MANIFEST_KEY_ENV, KEY)
    entries = {
        "group_by_day@1.0.0": ManifestEntry(file="group_by_day@1.0.0.js", integrity=SRI),
        "group_by_day@0.9.0": ManifestEntry(file="group_by_day@0.9.0.js", integrity=SRI, deprecated=True),
    }
    manifest = TransformManifest(entries=entries, signature=sign_entries(entries, KEY))
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return path


def test_manifest_signature_verified(manifest_file: Path) -> None:
    assert load_manifest(manifest_file) is not None


def test_manifest_tampered_returns_none(manifest_file: Path) -> None:
    # FILL IN: flip one entry's integrity in the JSON on disk → load_manifest(...) is None
    ...
```
(FILL IN the rest from Test Specification.)

### FILL IN checklist
- [ ] `TransformManifest._check_entries` — id/file/integrity rules; bounded by S6
- [ ] `load_manifest` body — five `None` branches, never raises; bounded by AC9
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] A manifest whose HMAC verifies loads; any tamper, missing key, missing file or bad JSON yields `None` (AC9).
- [ ] Deprecated entries resolve with a `warning` log (AC9).
- [ ] Unknown ids raise `KeyError` from `resolve_ref`.
- [ ] An entry whose `file` is a URL or path (`https://…`, `../x.js`, `a/b.js`) is rejected (S6).
- [ ] `ruff check` + `black --check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_manifest.py -q`

---

## Test Specification

```python
def test_manifest_signature_verified(manifest_file): ...
def test_manifest_tampered_returns_none(manifest_file): ...
def test_manifest_missing_key_returns_none(manifest_file, monkeypatch): ...   # delenv → None
def test_manifest_missing_file_returns_none(tmp_path): ...
def test_manifest_deprecated_warns(manifest_file, caplog): ...                 # resolve 0.9.0 → warning, returns ref
def test_resolve_ref_unknown(manifest_file): ...                              # KeyError
def test_manifest_entry_rejects_url(): ...                                    # file="https://cdn/x.js" → ValidationError
def test_default_path_uses_static_dir(monkeypatch, tmp_path): ...             # monkeypatch parrot.conf.STATIC_DIR
```

---

## Agent Instructions

1. Read spec §3 Module 9, §7 risks on `ref`, §9 S6, AC9.
2. Confirm TASK-3769 done. Index → `in-progress`.
3. Implement; run Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
4. Move to `sdd/tasks/completed/`, index → `done`, Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
