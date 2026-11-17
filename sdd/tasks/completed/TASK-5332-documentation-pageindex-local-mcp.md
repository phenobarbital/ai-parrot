# TASK-5332: Documentation — `wiki/knowledge/pageindex-local-mcp.md`

**Feature**: FEAT-844 — PageIndex Toolkit Fixes
**Spec**: `sdd/specs/pageindex-toolkit-fixes.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5328, TASK-5331
**Assigned-to**: unassigned

---

## Context

Spec §10 declares `docs.policy: required` with one page to **update**:
`wiki/knowledge/pageindex-local-mcp.md`. Two behaviours documented there change in FEAT-844:
the `retrieve` truncation marker gains a first-section-cut variant (TASK-5331, D4), and the stdio
server's stdout purity now holds even while the prompt-injection scorer loads (TASK-5328).
`vacuum_tree` also reports two new keys and floors its age (TASK-5329) — mention it where the page
lists write tools, if it does.

---

## Scope

- Update the "`retrieve` truncation" bullet (page lines 104-108) to quote both marker variants.
- Add one sentence under the stdout/JSON-RPC purity discussion stating that the injection-scorer
  banner is redirected to stderr at resolution time (first ingest), so stdout purity does not
  depend on a cached model.
- If the page lists `pageindex_vacuum_tree`, note that ages below the generation grace are raised
  to it and the result carries `revisions_removed` and `max_age_s`.
- Run `parrot sdd techwiki check --spec sdd/specs/pageindex-toolkit-fixes.spec.md --root .`.

**NOT in scope**: new wiki pages; `wiki/tools/mcp-local-toolkits.md` (nothing in it changes);
code or tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | marker variants, scorer banner note, vacuum note |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `origin/dev` @ `a3dec1c902` (2026-11-08).

### Verified Imports
```python
# none — documentation only
```

### Existing Signatures to Use
```markdown
# wiki/knowledge/pageindex-local-mcp.md
:104  - **`retrieve` truncation.** When the joined bodies exceed `max_result_chars`, whole sections are kept while they
:105    fit and the text ends with `[truncated: N more characters in K further sections — lower top_k or narrow the query]`.
:106-108 (bound applies to the kept text; title line kept whole; first section cut at a paragraph break; MCP `Metadata:` trailer)
```
Template for page structure: `sdd/templates/techwiki-page.md` (the page already follows it — keep
its frontmatter and section order).

### Does NOT Exist
- ~~`wiki/knowledge/pageindex-toolkit-fixes.md`~~ — FEAT-844 creates no page.
- ~~a `vacuum_tree` `force` flag~~ — do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-local-mcp.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Quote marker text exactly as `_bound_text` emits it after TASK-5331 (read the merged method, do
  not paraphrase from memory).
- Keep the page's `ref:` links intact (`parrot sdd techwiki check` resolves them).

---

## Implementation Blueprint

### Steps (in order)
1. Edit the truncation bullet — *why*: D4 changed the marker.
2. Add the scorer-banner sentence — *why*: TASK-5328 made stdout purity deterministic.
3. Add the vacuum note if the tool is listed — *why*: result shape changed.
4. Run the techwiki check — *why*: `/sdd-done` gates on it.

### `wiki/knowledge/pageindex-local-mcp.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF 'fit and the text ends with `[truncated: N more characters in K further sections' wiki/knowledge/pageindex-local-mcp.md)
# REPLACE line 105 (verified: pageindex-local-mcp.md:105) with:
  fit and the text ends with `[truncated: N more characters in K further sections — lower top_k or narrow the query]`.
  When the first section itself is cut, the marker reads `[truncated: N more characters in this section and K further
  sections — lower top_k or narrow the query]` (`in this section — …` when nothing else was dropped).

# FILL IN: locate the paragraph that discusses stdout as a pure JSON-RPC channel (grep -n "stdout" wiki/knowledge/pageindex-local-mcp.md)
#   and append one sentence: "The prompt-injection scorer resolves with stdout redirected to stderr, so its model-loading
#   banner on the first ingest never reaches the channel." — bounded by spec §10
# FILL IN: if `pageindex_vacuum_tree` is listed, add: "Ages below the generation grace are raised to it; the result
#   reports `removed`, `revisions_removed` and the effective `max_age_s`." — bounded by spec §10
```
**Why**: the page is the agent-facing reference for the stdio server; both changes alter what an
operator or agent observes.

### FILL IN checklist
- [ ] scorer-banner sentence placement — bounded by spec §10
- [ ] vacuum note (only if the tool is listed) — bounded by spec §10

---

## Acceptance Criteria

- [ ] AC-12 the page documents both marker variants and the banner redirect; `parrot sdd techwiki check --spec sdd/specs/pageindex-toolkit-fixes.spec.md --root .` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py -q`

---

## Test Specification

Documentation task — `test_local_mcp_docs.py` (FEAT-842) checks the page against the code; the
techwiki link check is run by hand (`parrot sdd techwiki check --spec sdd/specs/pageindex-toolkit-fixes.spec.md --root .`,
not a registered test runner) and `/sdd-done` gates on it.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5328 and TASK-5331 are `done` in `sdd/tasks/index/pageindex-toolkit-fixes.json`.
2. Mark `in-progress`, commit only the index.
3. Edit the page per the blueprint; run the Validation Command.
4. Commit the page; `parrot sdd task close TASK-5332 pageindex-toolkit-fixes verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

**Completed by**: Claude Opus 5.5 (/sdd-fix session agent:sdd-fix:507d6e6a)
**Date**: 2026-11-08
**Notes**: `wiki/knowledge/pageindex-local-mcp.md` — the `retrieve` truncation bullet quotes both marker variants (D4); a new `vacuum_tree` bullet documents the grace floor and the `revisions_removed` / `max_age_s` result keys; the "Known issue — stdout noise on first ingest" bullet became "stdout stays pure while the scorer loads" (redirect at resolution time + stream bound at start, formerly issue:70f18da2a8d5). Validation: `test_local_mcp_docs.py` 2 passed; `parrot sdd techwiki check --spec sdd/specs/pageindex-toolkit-fixes.spec.md --root .` → "Docs: required — ok" (exit 0). Docs commit: 047ab5883f.

**Deviations from spec**: none
