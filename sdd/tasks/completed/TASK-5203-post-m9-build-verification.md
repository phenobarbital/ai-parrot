# TASK-5203: Post-M9 strict build and overlay verification

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-5196, TASK-5197, TASK-5198, TASK-5199, TASK-5200, TASK-5201, TASK-5202
**Assigned-to**: unassigned

---

## Context

Final gate: strict build, landing overlay, project-prefix URLs, wiki targets (AC6, AC7, AC12). M9 must have landed first. Implements spec §3 Module 7 (Post-M9 Build Verification).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Confirm M9 landed: no `mkdocstrings` in `mkdocs.yml`, `requirements-docs.txt` or `.github/workflows/docs.yml`. If it has not, STOP — mark `done-with-issues` and do not edit those files.
- Run `mkdocs build --strict`, then `cp -R landing/. site/`, serve `site/` under `/ai-parrot/` and check docs CTA, CSS/JS, favicon, social card resolve. Save logs to `artifacts/logs/feat-803-build.log`.
- Verify every wiki URL in docs/ against the released `techwiki-manifest.json`.
- Write `tests/docs_site/test_site_build.py` (static checks of the workflow and deps contract).

**NOT in scope**: Editing requirements-docs.txt, the workflow, or mkdocs.yml — verification only (spec M7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/docs_site/test_site_build.py` | CREATE | workflow/deps contract checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified (dev @ 0b8c3a1fa2 — pre-M9; refresh after M9)
```text
.github/workflows/docs.yml:35-36  Install doc tooling: pip install -r requirements-docs.txt
.github/workflows/docs.yml:38-39  editable install for mkdocstrings  — M9 removes
.github/workflows/docs.yml:42-43  Build site: mkdocs build
.github/workflows/docs.yml:45-46  cp -R landing/. site/
requirements-docs.txt: mkdocs>=1.6.1, mkdocs-material>=9.8.0, mkdocstrings[python]>=1.0.8 (M9 removes), pymdown-extensions>=11.0.2, mkdocs-glightbox>=0.5.2
```

### Does NOT Exist
- ~~`docs/overrides/`~~ — does not exist on dev; created by TASK-5197
- ~~`docs/tutorials/`~~ — does not exist on dev; created by TASK-5201 / TASK-5202
- ~~favicon / social-card raster assets~~ — do not exist yet on dev; created by TASK-5195
- ~~`tests/docs_site/`~~ — does not exist; each task creates its own test module there (no `__init__.py`, no `conftest.py`)
- ~~Wiki page slugs derived from section labels~~ — section labels (e.g. "Bots & Agents") are NOT page slugs; take targets from `wiki/_index.yaml` / the released `techwiki-manifest.json`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "tests/docs_site/test_site_build.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Content/design only — no product Python code. Test modules are plain-pytest, filesystem-only (no `parrot` import needed except where stated).
- Two-surface doctrine: Pages = what/why; Wiki = technical reference. Cross-link, never copy (AC11).


---

## Implementation Blueprint

### Steps (in order)
1. Check M9 gate — *why*: spec §7 merge gate.
2. Build + overlay + serve, record evidence — *why*: AC6/AC12.
3. Write tests.

### `tests/docs_site/test_site_build.py` (CREATE)
```python
"""FEAT-803 AC7/AC12: inherited post-M9 pipeline contract."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
REQS = (ROOT / "requirements-docs.txt").read_text(encoding="utf-8")
MINIMUMS = {"mkdocs": (1, 6, 1), "mkdocs-material": (9, 8, 0), "pymdown-extensions": (11, 0, 2), "mkdocs-glightbox": (0, 5, 2)}


def test_overlay_preserved() -> None:
    assert "cp -R landing/. site/" in WORKFLOW


def test_no_mkdocstrings_after_m9() -> None:
    for text in (WORKFLOW, REQS, (ROOT / "mkdocs.yml").read_text(encoding="utf-8")):
        assert "mkdocstrings" not in text


def test_dependency_minimums_not_lowered() -> None:
    for name, floor in MINIMUMS.items():
        match = re.search(rf"^{re.escape(name)}>=([\d.]+)", REQS, re.MULTILINE)
        assert match, name
        # FILL IN: compare tuple(int(p) for p in match.group(1).split('.')) >= floor
```
### FILL IN checklist
- [ ] Version comparison
- [ ] Build/serve evidence in artifacts/logs/

---

## Acceptance Criteria

- [ ] `mkdocs build --strict` passes with no warnings (AC6)
- [ ] Workflow has no editable install, deps file unchanged/minimums kept (AC7)
- [ ] Overlay works and URLs resolve under /ai-parrot/ (AC12)
- [ ] Mobile check of both tiers noted (AC13)
- [ ] `pytest tests/docs_site/test_site_build.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_site_build.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5203 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat mistral (nova devstral-2-123b), attempt 2
**Date**: 2026-11-05
**Notes**: Merged by the engine; merge-tier validation green (tests/docs_site/test_site_build.py: 3 passed). Per-task semantic review deferred to the feature-level code review.

**Deviations from spec**: none
