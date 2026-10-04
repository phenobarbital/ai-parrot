# TASK-3714: Offline export bundle for one manual revision (M14 Q9)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3699
**Assigned-to**: unassigned

> Parallelism: renders ManualCard/Tip/Applicability from TASK-3699 (manuals/models.py); FakeFileManager comes transitively from TASK-3698.

---

## Context

Spec §2 Overview "Export (Q9)", §3 **Module 14**, goal **G12**, **AC22**. `parrot manuals export <manual_id>`
(CLI in TASK-3727) produces `<manual_id>-<revision>.bundle/` — `manifest.json`, `procedures.json`,
`captions.json`, `videos.json`, `figures/<media_id>.png` pulled from object storage — plus an optional `.zip`,
for a per-device offline viewer (the viewer is out of scope). Deterministic output (sorted keys, stable names)
so bundles diff across revisions; **no presigned URLs, no graph internals**; missing storage objects are listed,
not fatal. Curator-only authorization is enforced by the caller (TASK-3727), not here.

---

## Scope

- Create `manuals/export.py`: `BUNDLE_SCHEMA_VERSION`, `BundleManifest`, `ExportReport`, `render_procedures`
  (pure), `export_bundle` (async).
- Tests: `test_export_bundle_layout_and_manifest`, `test_export_excludes_orphaned_tips`.

**NOT in scope**: the CLI command and curator gate (TASK-3727); fetching tips from the graph (callers pass
`tips`); the viewer app (Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/export.py` | CREATE | bundle writer |
| `packages/ai-parrot/tests/knowledge/manuals/test_export.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.manuals.models import ManualCard, Tip      # created by TASK-3699 (spec §3 M2)
from pydantic import BaseModel, Field
import asyncio, hashlib, json, shutil, zipfile                   # stdlib
```

### Existing Signatures to Use
```python
# FileManagerInterface (navigator-api 4.0.0) — .venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py
async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path    # :93-105

# TASK-3699 model contract (spec §2/§3 M2):
class ManualCard: manual_id, equipment, revision, source_sha256, procedures: list[Procedure], figures: list[MediaRef],
                  versions: list[ManualVersion], ...
class Procedure: procedure_id, slug, kind, title: Extracted[str], steps: list[Step], estimated_minutes, active
class Step: identity (step_id), order, text: Extracted[str], torque, duration_minutes, applicability, figure_refs,
            parts, tools, hazards, media: list[MediaLink], cross_refs
class MediaRef: media_id, kind ("figure"|"photo"|"video_segment"), storage_key, uri, page, caption, label, t_start, t_end, callouts
class ManualVersion: n, revision, source_sha256, ...
class Tip: tip_id, text, origin, author_employee_id, created_at, active, orphaned, source_revision, attached_step_id
# Test double: FakeFileManager (tests/knowledge/_support/files.py, TASK-3698) — download_file writes deterministic bytes, missing keys raise.
```

### Does NOT Exist
- ~~A bundle exporter anywhere in the tree~~ (spec §6) — created here.
- ~~Presigned URLs in the bundle~~ — forbidden (AC22); `MediaRef.uri` of a video is the public deep link (vendor URL) and is the only URL allowed, in `videos.json`.
- ~~`FileManagerInterface.download(...)`~~ — the method is `download_file(source, destination)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/export.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_export.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Determinism: `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)` + trailing newline; procedures
  sorted by slug, steps by order; zip entries written in sorted order with a fixed `date_time` (1980-01-01).
- `procedures.json` carries steps with applicability, hazards, prerequisites (union of step parts/tools), media
  roles/callouts and **active, non-orphaned** tips; no `_key/_id/_from/_to`, no storage keys, no http(s) strings
  except video deep links in `videos.json` (the no-URL assertion in the test scans every file except videos.json).
- `generated_at` is the only time-varying field: take it from an injectable `now` (default UTC now) so tests freeze it.
- File writes are blocking — wrap them in `asyncio.to_thread` or keep them small; downloads go through `await fm.download_file`.
- No new third-party dependency; Google docstrings, type hints, Pydantic v2, `logger`.

---

## Implementation Blueprint

### Steps (in order)
1. Models + constants — *why*: the manifest shape is the viewer's contract (AC22).
2. `render_procedures` pure renderer — *why*: separating rendering from I/O makes determinism testable.
3. `export_bundle` — *why*: writes files, downloads figures, hashes everything into the manifest, optional zip.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/manuals/export.py` (CREATE)
```python
"""Offline export bundle for one manual revision (FEAT-601 M14, Q9)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.models import ManualCard, Tip

logger = logging.getLogger(__name__)

BUNDLE_SCHEMA_VERSION = "1.0"


class BundleManifest(BaseModel):
    schema_version: str = BUNDLE_SCHEMA_VERSION
    manual_id: str
    revision: str
    version_n: int
    generated_at: datetime
    source_sha256: str
    files: dict[str, str] = Field(default_factory=dict)   # relative path → sha256


class ExportReport(BaseModel):
    bundle_dir: Path
    zip_path: Path | None = None
    procedures: int = 0
    steps: int = 0
    figures: int = 0
    figures_missing: list[str] = Field(default_factory=list)
    tips: int = 0
    bytes: int = 0


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def render_procedures(card: ManualCard, tips: Sequence[Tip]) -> dict[str, Any]:
    """Pure, sorted rendering of procedures/steps/applicability/hazards/prerequisites/media roles/active tips; no URLs."""
    live_tips = [t for t in tips if t.active and not t.orphaned]
    # FILL IN: {"manual_id", "revision", "procedures": [ {procedure_id, slug, kind, title, estimated_minutes,
    #   prerequisites: {parts, tools} (dedup by id, sorted), steps: [{step_id, order, text, torque, duration_minutes,
    #   applicability: {models, serial_ranges}, hazards: [{severity, text}], media: [{media_id, role, confidence}],
    #   callouts, tips: [{tip_id, text, created_at}] for live_tips attached_step_id == step_id}] } sorted by slug ]}
    #   — bounded by AC22: no storage_key, no http(s), no graph internals.
    return {"manual_id": card.manual_id, "revision": card.revision, "procedures": []}


async def export_bundle(
    card: ManualCard,
    *,
    file_manager: Any,
    out_dir: Path,
    include_tips: bool = True,
    zip_bundle: bool = True,
    tips: Sequence[Tip] = (),
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> ExportReport:
    """Write <manual_id>-<revision>.bundle/{manifest,procedures,captions,videos}.json + figures/<media_id>.png."""
    bundle = Path(out_dir) / f"{card.manual_id}-{card.revision}.bundle"
    (bundle / "figures").mkdir(parents=True, exist_ok=True)
    report = ExportReport(bundle_dir=bundle)
    files: dict[str, bytes] = {
        "procedures.json": _dump(render_procedures(card, tips if include_tips else ())),
    }
    # FILL IN: captions.json = sorted [{media_id, label, page, caption}] for figure/photo MediaRefs;
    #   videos.json = sorted [{media_id, uri, t_start, t_end, label}] for video_segment refs;
    #   for each figure: await file_manager.download_file(ref.storage_key, bundle/"figures"/f"{ref.media_id}.png"),
    #   on exception append media_id to report.figures_missing and continue (not fatal);
    #   write JSON files; sha256 every written file (json + figures) into manifest.files (sorted keys);
    #   version_n = card.versions[-1].n if card.versions else 1; write manifest.json last; optional deterministic zip
    #   (sorted entries, ZipInfo date_time=(1980,1,1,0,0,0)); fill report counters + bytes — bounded by AC22.
    logger.info("export_bundle: %s → %s", card.manual_id, bundle)
    return report
```
**Why**: rendering is pure so the "no URL / sorted / deterministic" rules are asserted without storage; the
manifest is written last so its hashes cover every other file.

### `packages/ai-parrot/tests/knowledge/manuals/test_export.py` (CREATE)
```python
"""FEAT-601 M14 — export bundle (AC22)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from parrot.knowledge.manuals import export as ex

FROZEN = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


async def test_export_bundle_layout_and_manifest(tmp_path, fake_file_manager) -> None:
    # FILL IN: build a ManualCard (2 procedures, figures with storage keys, one video segment), pre-load
    #   fake_file_manager with one figure and leave the other missing; export twice with now=lambda: FROZEN ⇒
    #   identical bytes; manifest sha256s match files; "http" absent from every file except videos.json;
    #   figures_missing lists the missing one; zip_bundle=False ⇒ zip_path None.
    ...


async def test_export_excludes_orphaned_tips(tmp_path, fake_file_manager) -> None:
    # FILL IN: tips [active attached, orphaned, inactive] ⇒ only the active one in procedures.json; include_tips=False ⇒ none.
    ...
```

### FILL IN checklist
- [ ] `render_procedures` body — AC22.
- [ ] `export_bundle` captions/videos/figures/manifest/zip — AC22, missing-not-fatal.
- [ ] Test bodies (card builders from TASK-3699 models).

---

## Acceptance Criteria

- [ ] Bundle layout `<manual_id>-<revision>.bundle/{manifest.json, procedures.json, captions.json, videos.json, figures/}` (AC22).
- [ ] Manifest sha256s match files; output byte-identical across two runs with a frozen clock.
- [ ] No presigned URLs / storage keys / graph internals; orphaned or inactive tips excluded; missing figures listed, not fatal.
- [ ] `ruff check` + `black --check -l 120` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_export.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_export_bundle_layout_and_manifest` | manifest sha256s match; procedures.json sorted/deterministic; no http(s) outside videos.json; missing figure listed not fatal; zip optional |
| `test_export_excludes_orphaned_tips` | orphaned/inactive tips absent from the bundle |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/training-agent.spec.md` (module section named in Context).
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/` (or merged in your feature branch).
3. **Verify the Codebase Contract** — before writing ANY code confirm every import, signature and line anchor
   above still holds (`grep -n` / `read`). Symbols marked "created by TASK-<X>" must exist now that the
   dependency landed; if a name differs, follow the landed code and record the deviation.
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes.
6. **Verify** — run every command in *Validation Commands* (with the worktree `PYTHONPATH`), plus `ruff check`
   and `black --check -l 120` on the touched files.
7. **Move this file** to `sdd/tasks/completed/`, set the index entry to `"done"`, fill in the Completion Note.

---

## Completion Note


- Task: TASK-3714
- Feature: training-agent
- Implementation SHA: 808ddbab234992cfec13bcd30488c0203aa9afac
- Closed at (UTC): 2026-09-25T13:54:50+00:00
- Fix commits: 0b6527c4b224e82ba536ed0c67dde339a572e64a

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: glm (retry after codex-spark infra failure) · Backend: nova · Model: zai.glm-4.7-flash · Attempts: 2 (1 infra failure + 1 completed) · Duration: 166.3s · Tokens: 1490456/8447 |
| supplementary_test_evidence | 127 passed, 1 skipped, 0 failed (scoped direct pytest over knowledge/manuals/ + contracts/test_ontology_domain.py, after fix commit 0b6527c4b) |
