# TASK-2667: Project page reconciler (§19, diff-guarded) + new-project creation (§16)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2661, TASK-2662, TASK-2666
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 9 — the **highest-risk** node. Reconcile the canonical project page to
current state after each meeting (§19), and create new projects only when warranted (§16).

## Scope

- `nodes/project_reconcile.py` + `render/project.py`: **typed section-merge** with the **strong-tier client** (edit typed §19 sections, NOT free-form whole-page regen).
- **Q2 diff-guard**: no claim removed while a live source still supports it; supersede only with a newer source (chronological, §19 rule 10 — never let an older late-arriving meeting overwrite newer state).
- Preserve `## Human Notes` verbatim; if `locked: true`, queue a `locked-page-update` review item instead of editing.
- **§16 new-project creation**: create a project ONLY for an ongoing body of work; **never** for a passing topic, single question, company-mention-without-work, a concept (→ Concepts), or a product (→ Products). When justified, create the full `Projects/<Name>/` + `Meeting Summaries/{index,Archive/index}.md` in the same ingest and link it from `Wiki/index.md`.

**NOT in scope**: entities/concepts (TASK-2668), contradictions (TASK-2669).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/project_reconcile.py` | CREATE | reconciler + new-project |
| `.../wiki_ingest/render/project.py` | CREATE | deterministic §19 renderer |
| `packages/ai-parrot/tests/unit/test_wiki_kb_project_reconcile.py` | CREATE | diff-guard + chronological + §16 tests |

## Codebase Contract (Anti-Hallucination)
### Existing Signatures to Use
```python
async def invoke(self, prompt, *, output_type=None, ...) -> InvokeResult      # clients/base.py:1747
async def update_note(self, path, content, preserve_frontmatter=True)         # tools/obsidian.py:471
async def read_note(self, path, include_content=True)                         # tools/obsidian.py:212
```
### Does NOT Exist
- ~~free-form whole-page regeneration~~ — forbidden; typed section-merge only.

## Implementation Notes
- The diff-guard is the single most important safety mechanism — enforce it and assert it in §34 validation (TASK-2661).
- Link every material claim to a source page (rule #10); no fabrication (rule #12).

## Acceptance Criteria
- [ ] A claim with a live source is never dropped on reconcile.
- [ ] An older late-arriving meeting does not overwrite newer current-state.
- [ ] `## Human Notes` preserved; `locked: true` → queued, not edited.
- [ ] No project created for a passing topic / lone company mention (§16).
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_diff_guard_keeps_live_sourced_claim(): ...
async def test_chronological_no_regression(): ...
async def test_new_project_negative_criteria(): ...
```
