# TASK-2668: Entity + concept resolvers (§20 / §21, match-before-create)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2661, TASK-2662, TASK-2666
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 10. Create/update entity (§20) and concept (§21) pages, matching
existing knowledge first to avoid near-duplicates (rule #6).

## Scope

- `nodes/entities.py` + `nodes/concepts.py` + `render/{entity,concept}.py`.
- Match-before-create: search filenames, frontmatter `title`/`id`/`aliases`, spelling/abbreviation/former-name variants (use GraphIndex retrieval from TASK-2671 when available; fall back to `search_notes`); prefer updating the canonical page.
- Render exact §20/§21 templates; entity pages only for material people/companies/products; concept pages only for material, reused ideas (not "every noun").
- Do not infer unsupported personal details/titles/ownership (§20); no fabrication (rule #12).

**NOT in scope**: project reconcile, contradictions.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/entities.py` | CREATE | entity resolver |
| `.../wiki_ingest/nodes/concepts.py` | CREATE | concept resolver |
| `.../wiki_ingest/render/entity.py`, `render/concept.py` | CREATE | §20/§21 renderers |
| `packages/ai-parrot/tests/unit/test_wiki_kb_entities_concepts.py` | CREATE | match + render tests |

## Codebase Contract (Anti-Hallucination)
### Existing Signatures to Use
```python
async def search_notes(self, query, limit=20)   # tools/obsidian.py:300
async def list_notes(self, folder=…, recursive=…) # tools/obsidian.py:257
async def create_note(...); async def update_note(...)  # :439 / :471
```
### Does NOT Exist
- ~~an existing entity/concept resolver~~ — new here.

## Implementation Notes
- Canonical human-readable filenames (§8.2); alternates in `aliases`.
- Prefer update over near-duplicate create.

## Acceptance Criteria
- [ ] Existing entity/concept is updated, not duplicated, on alias/spelling variants.
- [ ] Rendered pages match §20/§21 templates.
- [ ] No unsupported inference; `ruff`/`mypy` clean.

## Test Specification
```python
async def test_match_before_create_alias(): ...
async def test_no_concept_for_every_noun(): ...
```
