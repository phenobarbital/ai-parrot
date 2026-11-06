# TASK-5275: Documentation — green cache depth-1 limit, namespace and file name

**Feature**: FEAT-830 — test-scope report fixes
**Spec**: `sdd/specs/test-scope-report-fixes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5272, TASK-5273
**Assigned-to**: unassigned
**Discovered-from**: `issue:bfb29d4ffe49`

---

## Context

Spec §1 item 5 / Module 5 and §10. The issue named `docs/sdd/test-selection-validation-contract.md`, which no
longer exists; the page is `wiki/sdd-tooling/sdd/test-selection-validation-contract.md`. Its "Green cache and
baseline verdict" section does not state the depth-1 cache-key limit, names the wrong cache file
(`.sdd_test_cache.json`; the real one is `green_cache.CACHE_FILENAME == "parrot-test-scope-green.json"`), and
predates the single namespace (TASK-5273) and the `.py`-only contract rule (TASK-5272).

---

## Scope

- In "Green cache and baseline verdict": correct the cache file name; add the depth-1 limit; add one bullet on
  the namespace (`green_cache.namespace_for`: feature id + base ref + contract digest, `""` without a contract,
  shared by `select_tests` and the MCP supervisor).
- In "Authoring" → "Format": add one line — contract operands must be `.py` files or node ids; a directory is
  rejected (`test-contract-malformed` in `check_task_graph`).

**NOT in scope**: any code; other wiki pages; restructuring the page.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/sdd-tooling/sdd/test-selection-validation-contract.md` | MODIFY | green-cache facts + `.py` rule |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None (documentation only).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py
CACHE_FILENAME: str = "parrot-test-scope-green.json"  # line 31
def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:  # line 38
def namespace_for(*, feature_id: str, base_ref: str, contract: TestContract | None) -> str:  # created by TASK-5273
# The cache key digests a test file's DIRECT imports only (depth 1) — issue:bfb29d4ffe49 item 5.

# wiki/sdd-tooling/sdd/test-selection-validation-contract.md
#   "## Green cache and baseline verdict"  (line 43)
#   "- **Cached targets**: Test execution results for passing test suites are recorded in `.sdd_test_cache.json`."  (line 45)
#   "### Format"  (line 11)
```

### Does NOT Exist
- ~~`docs/sdd/test-selection-validation-contract.md`~~ — gone.
- ~~`.sdd_test_cache.json`~~ — not the cache file.
- ~~`--fresh` flag on `select_tests`~~ — unverified; do not add new claims about flags (leave the existing bullet alone).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/sdd-tooling/sdd/test-selection-validation-contract.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#cache_namespace"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the page's existing tone and bullet style; add bullets, do not rewrite sections.
- State only facts verified in code (the depth-1 limit is stated by the issue and the cache design; confirm in
  `green_cache._manifest` before writing it).

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the depth-1 behaviour in `green_cache._manifest` / `_imported_sources` — *why*: docs state only verified facts.
2. Replace the "Cached targets" bullet and add the two new bullets — *why*: AC-8.
3. Add the `.py` rule line under "### Format".
4. Run the Validation Command and `parrot sdd techwiki check --spec sdd/specs/test-scope-report-fixes.spec.md --root .`.

### `wiki/sdd-tooling/sdd/test-selection-validation-contract.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c -F -- '- **Cached targets**:' test-selection-validation-contract.md) -->
<!-- REPLACE line 45 with: -->
- **Cached targets**: green results are recorded per worktree in `parrot-test-scope-green.json`
  (`green_cache.CACHE_FILENAME`), only for `.py` files and node ids.
- **Namespace**: one store namespace per feature id + base ref + contract digest (`green_cache.namespace_for`;
  a feature without a contract digests as `""`). `select_tests` and the MCP supervisor compute the same value,
  so neither clears the other's entries; any change to the three inputs invalidates the whole store.
- **Depth-1 key**: a cache key digests the test file and the sources it imports **directly**. A change two
  imports away does not invalidate the entry — the feature tier runs fresh and the nightly sweep is the backstop.
```
FILL IN: wording of the depth-1 bullet once step 1 confirms it — bounded by AC-8.

```markdown
<!-- AFTER — insert below `### Format` and its first sentence (verified: line 11-12) -->
Contract operands are `.py` files or `file.py::node` ids; a directory or suite is rejected when the contract is
parsed or loaded, and `check_task_graph` reports it as `test-contract-malformed`.
```

### FILL IN checklist
- [ ] depth-1 bullet wording — AC-8

---

## Acceptance Criteria

- [ ] AC-8 The page states the depth-1 cache-key limit and names `parrot-test-scope-green.json`.
- [ ] `parrot sdd techwiki check` passes for the spec.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`  (docs task: the real check is `parrot sdd techwiki check --spec sdd/specs/test-scope-report-fixes.spec.md --root .` — see AC)

---

## Test Specification

Documentation only — no tests.

---

## Agent Instructions

1. Work in `feat-FEAT-830-test-scope-report-fixes`.
2. Implement from the Blueprint; run the Validation Command.
3. Commit only the listed file; close with `parrot sdd task close TASK-5275 test-scope-report-fixes verified`.

---

## Completion Note

*(Agent fills this in when done)*
