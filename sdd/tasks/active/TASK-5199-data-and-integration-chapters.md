# TASK-5199: Data, tools and integration chapter overviews

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Chapter overviews become newcomer concept introductions that cross-link to the GitHub Wiki for technical depth (spec G3, AC3, AC11). Implements spec §3 Module 4 (Content Hub & Chapter Rewrites).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Rewrite `docs/chapters/memory-knowledge.md`.
- Rewrite `docs/chapters/knowledge-graph.md`.
- Rewrite `docs/chapters/tools-rag.md`.
- Rewrite `docs/chapters/integrations.md`.
- Write `tests/docs_site/test_chapters_data.py`.

**NOT in scope**: Other chapters (split across TASK-5198/5199); wiki authoring (FEAT-801); mkdocs.yml.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/chapters/memory-knowledge.md` | MODIFY | full rewrite as concept intro |
| `docs/chapters/knowledge-graph.md` | MODIFY | full rewrite as concept intro |
| `docs/chapters/tools-rag.md` | MODIFY | full rewrite as concept intro |
| `docs/chapters/integrations.md` | MODIFY | full rewrite as concept intro |
| `tests/docs_site/test_chapters_data.py` | CREATE | structure checks |

---

## Codebase Contract (Anti-Hallucination)

### Chapter → Wiki mapping (spec §3 M4)
| Page | Wiki sections |
|---|---|
| `docs/chapters/memory-knowledge.md` | Memory; Knowledge; Stores & Loaders |
| `docs/chapters/knowledge-graph.md` | Knowledge; LLM Wiki |
| `docs/chapters/tools-rag.md` | Tools & Toolkits; Stores & Loaders |
| `docs/chapters/integrations.md` | Integrations; MCP & A2A; Server & APIs |

Wiki base URL: `https://github.com/phenobarbital/ai-parrot/wiki/<Page-Name>` (spec §7). Page names come from the manifest.
Read the current chapter file first — reuse its accurate facts, drop its API detail.

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
      "path": "docs/chapters/memory-knowledge.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/chapters/knowledge-graph.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/chapters/tools-rag.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/chapters/integrations.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/docs_site/test_chapters_data.py",
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
- Each overview follows the spec §3 M4 **Chapter overview pattern** (300–500 words: intro, Key Concepts, What You Can Build, Deep Dive). Wiki targets come ONLY from `wiki/_index.yaml` / released `techwiki-manifest.json` — list every chosen URL in the Completion Note with proof it exists (AC3). If FEAT-801 has not published the page yet, use the section's index page from the manifest and flag it in the Completion Note; never synthesize a slug. Pages = what/why; never paste class signatures or argument tables (AC11).

---

## Implementation Blueprint

### Steps (in order)
1. For each chapter, read the existing file and the mapped wiki sections in `wiki/_index.yaml` — *why*: facts must stay accurate and targets real.
3. Write each chapter per the pattern below — *why*: uniform newcomer reading experience.
4. Write the test module.

### `docs/chapters/<chapter>.md` (MODIFY — full rewrite, one per chapter)
```markdown
# <Chapter Name>

<!-- FILL IN: 2–3 paragraphs what/why for a newcomer — bounded by 300–500 words total -->

## Key Concepts

- **<Concept>**: <one sentence>

## What You Can Build

<!-- FILL IN: 2–3 concrete use cases -->

## Deep Dive

For API reference, class signatures, and implementation details, see the
[<Section> section in the Wiki](https://github.com/phenobarbital/ai-parrot/wiki/<Page-Name-from-manifest>).
```
### `tests/docs_site/test_chapters_data.py` (CREATE)
```python
"""FEAT-803 AC3/AC11: chapter overviews are concept intros with wiki links."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHAPTERS = ["memory-knowledge", "knowledge-graph", "tools-rag", "integrations"]
WIKI = re.compile(r"https://github\.com/phenobarbital/ai-parrot/wiki/[A-Za-z0-9._-]+")


@pytest.mark.parametrize("name", CHAPTERS)
def test_chapter_follows_pattern(name: str) -> None:
    text = (ROOT / "docs" / "chapters" / f"{name}.md").read_text(encoding="utf-8")
    for heading in ("## Key Concepts", "## What You Can Build", "## Deep Dive"):
        assert heading in text
    assert WIKI.search(text)
    words = len(text.split())
    assert 250 <= words <= 650, words
    # FILL IN: assert no ```python fenced blocks longer than 15 lines (AC11 — no reference duplication)
```
### FILL IN checklist
- [ ] Prose per chapter
- [ ] Manifest-verified wiki targets listed in the Completion Note

---

## Acceptance Criteria

- [ ] Each listed chapter follows the overview pattern with a verified wiki link (AC3)
- [ ] No API reference duplicated from the wiki (AC11)
- [ ] `pytest tests/docs_site/test_chapters_data.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_chapters_data.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5199 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
