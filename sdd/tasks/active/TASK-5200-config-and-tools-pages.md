# TASK-5200: Minimal config section and curated tools page

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`docs/config.md` is a flat env-var dump; `docs/tools_quick.md` is a 522-line catalog. Make both newcomer-friendly (AC9, AC10). Implements spec §3 Module 5 (Page Improvements).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Insert a `## Minimal Configuration` section directly below `# AI-Parrot Configuration Guide` (config.md:1): the 3–5 env vars needed to run a first chatbot (one LLM API key + where `env/.env` lives), copied from facts already in the file.
- Curate `docs/tools_quick.md` to 3–4 showcase tools with short examples, and end with a link to the wiki's full tool catalog (manifest-verified target). Remove the rest of the catalog from Pages (it lives in the wiki — AC11).
- Write `tests/docs_site/test_page_improvements.py`.

**NOT in scope**: Other docs pages; mkdocs.yml.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/config.md` | MODIFY | add Minimal Configuration at top |
| `docs/tools_quick.md` | MODIFY | curate to 3–4 tools + wiki link |
| `tests/docs_site/test_page_improvements.py` | CREATE | checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Anchors
```markdown
# AI-Parrot Configuration Guide          # docs/config.md:1 — occurrences: 1
# AI-Parrot Tools Quick Reference Guide  # docs/tools_quick.md:1 — occurrences: 1
```
Choose showcase tools that actually exist in `packages/ai-parrot-tools/src/parrot_tools/` — verify each import path you show with `ls`/`grep` before writing it.

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
      "path": "docs/config.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/tools_quick.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/docs_site/test_page_improvements.py",
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
1. Insert the minimal config section after config.md:1 — *why*: AC9 requires it at the top.
2. Rewrite tools_quick.md keeping its H1 — *why*: AC10.
3. Write tests.

### `docs/config.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '# AI-Parrot Configuration Guide' docs/config.md)
# AFTER — insert below `# AI-Parrot Configuration Guide` (verified: docs/config.md:1)

## Minimal Configuration

<!-- FILL IN: the smallest env/.env that runs a first chatbot — bounded by facts already in this file -->
```
### `docs/tools_quick.md` (MODIFY)
```markdown
# AI-Parrot Tools Quick Reference Guide

<!-- FILL IN: 3–4 `## <Tool>` sections with a minimal verified example each -->

## Full Catalog

The complete tool catalog lives in the [Wiki](https://github.com/phenobarbital/ai-parrot/wiki/<Page-from-manifest>).
```
### `tests/docs_site/test_page_improvements.py` (CREATE)
```python
"""FEAT-803 AC9/AC10."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_minimal_configuration_is_first_section() -> None:
    text = (ROOT / "docs" / "config.md").read_text(encoding="utf-8")
    first_h2 = next(line for line in text.splitlines() if line.startswith("## "))
    assert first_h2.strip() == "## Minimal Configuration"


def test_tools_quick_is_curated() -> None:
    text = (ROOT / "docs" / "tools_quick.md").read_text(encoding="utf-8")
    sections = [line for line in text.splitlines() if line.startswith("## ") and line.strip() != "## Full Catalog"]
    assert 3 <= len(sections) <= 4
    assert "github.com/phenobarbital/ai-parrot/wiki" in text
```
### FILL IN checklist
- [ ] Minimal env vars
- [ ] Showcase tool picks with verified imports

---

## Acceptance Criteria

- [ ] config.md first H2 is Minimal Configuration (AC9)
- [ ] tools_quick.md has 3–4 tools + wiki catalog link (AC10)
- [ ] `pytest tests/docs_site/test_page_improvements.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_page_improvements.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5200 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
