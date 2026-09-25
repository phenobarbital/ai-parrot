# TASK-3776: publish_transforms server helper (SRI + signed manifest)

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3775
**Assigned-to**: unassigned

---

## Context

Catalogued `transform.ref` modules are anonymous static files at
`/static/a2ui/transforms/<name>@<version>.js`, served by the existing navigator
`add_static("/static/", …)` route from `STATIC_DIR` — no new route code. An operator publishes a
release's modules with `publish_transforms()`, which copies them, computes SRI (`sha384-…`) and writes
the HMAC-signed `manifest.json` that TASK-3775's `load_manifest` verifies (spec §3 Module 9, AC9, S6).

---

## Scope

- Create `parrot/handlers/a2ui_transforms.py` (ai-parrot-server) with `compute_sri(data) -> str` and
  `publish_transforms(source_dir, *, key) -> TransformManifest`.
- Rules: copies only files named `<name>@<semver>.js`; merges into the existing manifest; **never deletes**
  an entry (retirement = `deprecated: true`, set by hand or a later helper); refuses to overwrite an
  already-published version whose bytes differ (versions are immutable — cached forever by clients).
- Tests with `STATIC_DIR` monkeypatched to `tmp_path`.

**NOT in scope**: any aiohttp route or handler class (the generic `/static/` route already serves the
files); a CLI; the loader/verifier (TASK-3775); deprecating entries.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/a2ui_transforms.py` | CREATE | publish helper |
| `packages/ai-parrot-server/tests/handlers/test_a2ui_transforms.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.linked.manifest import (   # created by TASK-3775
    ManifestEntry, TransformManifest, canonical_entries, default_manifest_path, sign_entries,
)
from parrot.conf import STATIC_DIR   # parrot/conf.py:51 — LOCAL import only (infographic_render.py:649)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/infographic_render.py:632-663
async def publish_to_static_dir(html: str, artifact_id: str) -> str:   # precedent: STATIC_DIR local import,
    # STATIC_DIR.mkdir(parents=True, exist_ok=True); served by add_static("/static/", ...) (docstring L644-647)
# TASK-3775 linked/manifest.py:
#   default_manifest_path() -> Path            # Path(STATIC_DIR) / "a2ui" / "transforms" / "manifest.json"
#   sign_entries(entries, key) -> str          # lowercase-hex HMAC-SHA256 over canonical_entries(entries)
#   ManifestEntry(file, integrity, deprecated=False); TransformManifest(version=1, entries, signature)
# packages/ai-parrot-server/tests/handlers/test_infographic_render_route.py:282
#   monkeypatch.setattr("parrot.conf.STATIC_DIR", tmp_path)   # test precedent
```
`parrot.handlers` in ai-parrot-server has no `__init__.py` (PEP 420 satellite); the core distribution owns
`packages/ai-parrot/src/parrot/handlers/__init__.py`.

### Does NOT Exist
- ~~`parrot/handlers/a2ui_transforms.py`~~ — created here.
- ~~a dedicated `/static/a2ui/transforms` aiohttp route~~ — not needed; do not add one.
- ~~`load_manifest(key=...)`~~ — TASK-3775's loader reads the key from the environment; this helper takes `key` explicitly and verifies the existing manifest itself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/a2ui_transforms.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_a2ui_transforms.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/infographic_render.py#publish_to_static_dir"
  ]
}
```

---

## Implementation Notes

- SRI: `"sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")` (W3C SRI format — the
  browser compares exactly this string; TASK-3794 recomputes it with `crypto.subtle.digest("SHA-384", …)`).
- Destination directory = `default_manifest_path().parent` (so loader and publisher can never disagree).
- Existing manifest: read `manifest.json` if present; verify `hmac.compare_digest(existing.signature,
  sign_entries(existing.entries, key))`; a mismatch raises `ValueError` (never silently re-sign a tampered catalogue).
- Immutability: if `<dest>/<file>` exists and its bytes differ from the source → `ValueError`; identical bytes → skip copy.
- Write order: copy modules first, then write the manifest atomically (write `manifest.json.tmp`, then `Path.replace`),
  so a crash never leaves a manifest pointing at a missing file.
- Sync I/O by design (operator helper); document "call via `loop.run_in_executor` from async code".
- `key` must be non-empty (`ValueError`); never log the key.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module — *why*: the only writer of the signed catalogue.
2. Write tests with `monkeypatch.setattr("parrot.conf.STATIC_DIR", tmp_path)`.
3. Run the Validation Commands.

### `packages/ai-parrot-server/src/parrot/handlers/a2ui_transforms.py` (CREATE)
```python
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
        # FILL IN: data = src.read_bytes(); target = dest / src.name; existing file with different bytes → ValueError;
        #          otherwise shutil.copyfile when absent; entries[id] = ManifestEntry(file=src.name, integrity=compute_sri(data),
        #          deprecated=<keep the existing entry's flag if present>) — bounded by "never deletes / immutable versions"
    signed = TransformManifest(entries=entries, signature=sign_entries(entries, key))
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(signed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)
    logger.info("published %d transform module(s) to %s", len(entries), dest)
    return signed
```

### `packages/ai-parrot-server/tests/handlers/test_a2ui_transforms.py` (CREATE)
```python
"""Tests for publish_transforms (FEAT-598 M9)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.handlers.a2ui_transforms import compute_sri, publish_transforms
from parrot.outputs.a2ui.linked.manifest import MANIFEST_KEY_ENV, load_manifest

KEY = "publish-test-key"


@pytest.fixture
def static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("parrot.conf.STATIC_DIR", tmp_path / "static")
    monkeypatch.setenv(MANIFEST_KEY_ENV, KEY)
    return tmp_path / "static"


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "group_by_day@1.0.0.js").write_text("export default (rows) => rows;\n", encoding="utf-8")
    return src


def test_publish_writes_signed_manifest(static_dir: Path, source_dir: Path) -> None:
    published = publish_transforms(source_dir, key=KEY)
    assert load_manifest() == published   # TASK-3775 loader verifies the same bytes
    # FILL IN: file copied under static_dir/a2ui/transforms; integrity == compute_sri(bytes)
```
(FILL IN the rest from Test Specification.)

### FILL IN checklist
- [ ] per-file copy/immutability/entry block; bounded by "never deletes, immutable versions" (spec M9)
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] A published manifest verifies under `load_manifest()` with the same key (AC9).
- [ ] SRI strings are `sha384-<base64>` of the exact file bytes.
- [ ] Re-publishing keeps earlier versions and their `deprecated` flags; different bytes for an existing version → `ValueError`.
- [ ] A tampered existing manifest → `ValueError`, nothing written.
- [ ] `ruff check` + `black --check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_a2ui_transforms.py -q`

---

## Test Specification

```python
def test_publish_writes_signed_manifest(static_dir, source_dir): ...
def test_publish_keeps_existing_versions(static_dir, source_dir, tmp_path): ...   # second dir with @1.1.0 → both entries
def test_publish_refuses_changed_version(static_dir, source_dir): ...            # rewrite @1.0.0 bytes → ValueError
def test_publish_rejects_tampered_manifest(static_dir, source_dir): ...
def test_publish_skips_non_versioned_files(static_dir, source_dir): ...          # "helper.js" skipped
def test_publish_requires_key(static_dir, source_dir): ...
def test_compute_sri_format(): ...
```

---

## Agent Instructions

1. Read spec §3 Module 9, AC9.
2. Confirm TASK-3775 done. Index → `in-progress`.
3. Implement; run Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`).
4. Move to `sdd/tasks/completed/`, index → `done`, Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
