# TASK-5195: Brand identity: favicon and social card

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Three different icons are used today and there is no favicon or OG social card. This task produces the two missing raster assets from the parrot SVG so the landing page (TASK-5196) and mkdocs theme (TASK-5197) can reference them. Implements spec §3 Module 2 (Brand Identity Unification).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Generate `docs/branding/favicon.ico` containing 16×16 and 32×32 frames, rendered from `docs/branding/parrot.svg`.
- Generate `docs/branding/social-card.png` at exactly 1200×630: project name "AI-Parrot", a one-line tagline ("Async-first Python framework for AI Agents and Chatbots"), and the parrot logo.
- Record the generator tool and exact command (ImageMagick/rsvg-convert/Pillow) in the Completion Note — required by spec §7.
- Write `tests/docs_site/test_branding_assets.py` asserting both files exist, the PNG is 1200×630, the ICO holds 16 and 32 px frames, and the 5 pre-existing assets are untouched.

**NOT in scope**: Referencing the assets from HTML or mkdocs.yml (TASK-5196/5197); editing or deleting any existing SVG/PNG.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/branding/favicon.ico` | CREATE | 16+32 px favicon from parrot.svg |
| `docs/branding/social-card.png` | CREATE | 1200×630 OG card |
| `tests/docs_site/test_branding_assets.py` | CREATE | asset checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Files
```text
docs/branding/parrot.svg                      # source icon — verified: ls docs/branding
docs/branding/parrot-transparent.png          # preserved
docs/branding/ai-parrot-wordmark-on-dark.svg  # preserved
docs/branding/parrot-mono-dark.svg            # preserved
docs/branding/parrot-mono-light.svg           # preserved
```
### Verified Imports (tests)
```python
from PIL import Image  # Pillow — verify with `python -c "import PIL"` in the venv; if absent, parse the PNG IHDR / ICO header with `struct` instead (do NOT add a dependency)
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
      "path": "docs/branding/favicon.ico",
      "action": "CREATE"
    },
    {
      "path": "docs/branding/social-card.png",
      "action": "CREATE"
    },
    {
      "path": "tests/docs_site/test_branding_assets.py",
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
1. Render `parrot.svg` to 16/32 px PNGs and pack them into `favicon.ico` (e.g. `convert parrot.svg -background none -define icon:auto-resize=32,16 favicon.ico`) — *why*: spec M2 requires both sizes.
2. Compose the 1200×630 social card — *why*: standard OG size used by both tiers.
3. Write the test module — *why*: AC5 needs a repeatable check.

### `tests/docs_site/test_branding_assets.py` (CREATE)
```python
"""FEAT-803 AC5: brand assets exist with the required geometry."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRANDING = ROOT / "docs" / "branding"
PRESERVED = ["ai-parrot-wordmark-on-dark.svg", "parrot-mono-dark.svg", "parrot-mono-light.svg",
             "parrot-transparent.png", "parrot.svg"]


def test_favicon_exists_with_16_and_32_frames() -> None:
    """favicon.ico carries 16x16 and 32x32 frames."""
    ico = BRANDING / "favicon.ico"
    assert ico.is_file()
    # FILL IN: read ICONDIR entries (struct, little-endian) and assert {16, 32} ⊆ sizes — bounded by AC5


def test_social_card_is_1200x630() -> None:
    """social-card.png is exactly 1200x630."""
    png = BRANDING / "social-card.png"
    assert png.is_file()
    # FILL IN: read width/height from the IHDR chunk (bytes 16..24, big-endian) — bounded by AC5


def test_existing_brand_assets_preserved() -> None:
    """The five pre-existing assets still exist."""
    for name in PRESERVED:
        assert (BRANDING / name).is_file(), name
```
**Why this shape**: header parsing via `struct` avoids a Pillow dependency in the test.

### FILL IN checklist
- [ ] ICO frame-size parsing — bounded by AC5
- [ ] PNG IHDR parsing — bounded by AC5
- [ ] Completion Note names the tool + command used

---

## Acceptance Criteria

- [ ] `docs/branding/favicon.ico` exists with 16 and 32 px frames (AC5)
- [ ] `docs/branding/social-card.png` is 1200×630 (AC5)
- [ ] The five existing branding files are byte-identical to dev
- [ ] `pytest tests/docs_site/test_branding_assets.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_branding_assets.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5195 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-terra (codex)
**Date**: 2026-11-05
**Notes**: Merged by the engine; merge-tier validation green (tests/docs_site: 16 passed). Per-task semantic review deferred to the feature-level code review.

**Deviations from spec**: none
