# TASK-5197: MkDocs nav collapse and theme refresh

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5195
**Assigned-to**: unassigned

---

## Context

The nav has 14 sections / 175 entries (`mkdocs.yml:114-340`). Collapse to 6 newcomer sections, swap the robot icon for the parrot, and add a `custom_dir` for CSS overrides. Implements spec §3 Module 3 (MkDocs Theme & Nav Restructuring).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Replace the whole `nav:` block (`mkdocs.yml:114` to EOF) with the 6-section structure from spec M3 verbatim (Home, Getting Started, Concepts, Tutorials, Guides, About). `getting-started.md` MUST appear (AC8).
- Guides: list only guides that survive FEAT-801 M7 classification; on dev today `docs/guides/` holds `cli-agent-daemon.md`, `jira-ticket-extractor.md`, `jira-wiki-agent-integration.md`, `llm-wiki-guide.md`, `llm-wiki-remote.md`, `wiki-adr-decisions.md` — FILL IN against FEAT-801's classification.
- About → Branding: `branding/` is a directory, not a page — FILL IN: either drop the entry or point at an existing page; `mkdocs build --strict` must not warn.
- Theme: replace `    logo: material/robot-happy-outline` (mkdocs.yml:48) with `logo: branding/parrot.svg` + `favicon: branding/favicon.ico` under `theme:`; add `custom_dir: docs/overrides`.
- Create `docs/overrides/main.css` (reference via `extra_css`) and `docs/overrides/main.html` extending `base.html` to emit OG meta pointing at `social-card.png`.
- Write `tests/docs_site/test_mkdocs_nav.py`.

**NOT in scope**: Removing the mkdocstrings plugin (M9 owns it — leave `mkdocs.yml:54` alone); creating tutorial files (TASK-5201/5202); editing docs content.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `mkdocs.yml` | MODIFY | nav rewrite, logo/favicon, custom_dir, extra_css |
| `docs/overrides/main.css` | CREATE | theme CSS overrides |
| `docs/overrides/main.html` | CREATE | OG meta partial |
| `tests/docs_site/test_mkdocs_nav.py` | CREATE | nav/theme checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Anchors (dev @ 0b8c3a1fa2)
```yaml
# mkdocs.yml — 340 lines
    logo: material/robot-happy-outline   # line 48 — occurrences: 1 (grep -c)
  - mkdocstrings:                        # line 54 — DO NOT TOUCH (M9)
nav:                                     # line 114 — occurrences: 1; block runs to EOF
```
Palette `primary: green` at lines 36 and 42 — keep.
`mkdocs.yml` is NOT plain YAML-safe if it uses `!!python/name:` tags — in the test load it with a `yaml.SafeLoader` subclass that ignores unknown tags (FILL IN) or parse only the `nav:` section.

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
      "path": "mkdocs.yml",
      "action": "MODIFY"
    },
    {
      "path": "docs/overrides/main.css",
      "action": "CREATE"
    },
    {
      "path": "docs/overrides/main.html",
      "action": "CREATE"
    },
    {
      "path": "tests/docs_site/test_mkdocs_nav.py",
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
1. Edit theme block: logo/favicon/custom_dir — *why*: G5 brand unification.
2. Replace `nav:` through EOF with the spec M3 block — *why*: AC2/AC8.
3. Create overrides — *why*: Material `custom_dir` pattern; never edit installed Material files.
4. Write tests.

### `mkdocs.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '    logo: material/robot-happy-outline' mkdocs.yml)
# REPLACE line 48 `    logo: material/robot-happy-outline` — the `icon:` mapping it sits in must not be left empty:
# FILL IN: remove the now-empty `icon:` key if logo was its only child; add under `theme:`
  custom_dir: docs/overrides
  logo: branding/parrot.svg
  favicon: branding/favicon.ico
# occurrences: 1 (verified: grep -c '^nav:' mkdocs.yml)
# REPLACE from `nav:` (mkdocs.yml:114) to EOF with the spec §3 M3 nav block
```
### `docs/overrides/main.html` (CREATE)
```html
{% extends "base.html" %}
{% block extrahead %}
  <meta property="og:image" content="https://phenobarbital.github.io/ai-parrot/docs/branding/social-card.png">
  <meta property="og:title" content="{{ page.title ~ ' — ' if page.title }}{{ config.site_name }}">
  <meta name="twitter:card" content="summary_large_image">
{% endblock %}
```
### `tests/docs_site/test_mkdocs_nav.py` (CREATE)
```python
"""FEAT-803 AC2/AC8: collapsed nav and parrot branding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def _nav_top_level() -> list[str]:
    """Return top-level nav titles (lines `  - Title:` directly under `nav:`)."""
    # FILL IN: slice CONFIG after the `nav:` line and collect `  - X` entries at indent 2
    raise AssertionError("unimplemented")


def test_nav_has_at_most_six_sections() -> None:
    assert len(_nav_top_level()) <= 6


def test_getting_started_in_nav() -> None:
    assert "getting-started.md" in CONFIG.split("\nnav:", 1)[1]


def test_parrot_branding_and_custom_dir() -> None:
    assert "robot-happy-outline" not in CONFIG
    assert "custom_dir: docs/overrides" in CONFIG
    assert "branding/favicon.ico" in CONFIG
```
### FILL IN checklist
- [ ] Surviving Guides list
- [ ] Branding nav entry resolution (no strict warning)
- [ ] `_nav_top_level` parsing

---

## Acceptance Criteria

- [ ] ≤6 top-level nav sections (AC2)
- [ ] `getting-started.md` in nav (AC8)
- [ ] Parrot logo + favicon; no robot icon; `custom_dir: docs/overrides`
- [ ] mkdocstrings plugin line untouched (M9 owns it)
- [ ] `pytest tests/docs_site/test_mkdocs_nav.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_mkdocs_nav.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5197 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-sol (codex)
**Date**: 2026-11-05
**Notes**: Merged by the engine; merge-tier validation green (tests/docs_site: 7 passed). Per-task semantic review deferred to the feature-level code review.

**Deviations from spec**: none
