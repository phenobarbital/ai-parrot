# TASK-5331: `_bound_text` marker names a cut first section

**Feature**: FEAT-844 — PageIndex Toolkit Fixes
**Spec**: `sdd/specs/pageindex-toolkit-fixes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5330
**Assigned-to**: unassigned
**Discovered-from**: `issue:d044442e1ecd`

---

## Context

Implements spec §3 **Module 4** (decision D4 in spec §7). When only the first section of a
`retrieve` result is cut, `_bound_text` appends
`[truncated: N more characters in 0 further sections — …]`: the numbers are consistent but the cut
remainder of the first section is not described (ledger `issue:d044442e1ecd`, FEAT-842 review).
FEAT-842 §2/§3 M3 fixed the marker text; FEAT-844 decides the new wording.

---

## Scope

- In `_bound_text`, keep the whole-sections marker unchanged and add the first-section-cut variant:
  - whole sections dropped (first part fits): `[truncated: {n} more characters in {k} further sections — lower top_k or narrow the query]`
  - first part cut, `k > 0`: `[truncated: {n} more characters in this section and {k} further sections — lower top_k or narrow the query]`
  - first part cut, `k == 0`: `[truncated: {n} more characters in this section — lower top_k or narrow the query]`
  The tail `lower top_k or narrow the query]` is byte-identical in every variant.
- Update the docstring of `_bound_text` and the two affected tests in `test_toolkit_no_llm.py`.

**NOT in scope**: the wiki page (TASK-5332); `llm_dependent_tools` prefix drift (spec Non-Goals);
any change to how much text is kept.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `_bound_text` marker variants + docstring |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` | MODIFY | marker assertions |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `origin/dev` @ `a3dec1c902` (2026-11-08), **before** TASK-5329/5330 (same file).
> Re-locate with `grep -nF`; a count of `0` means drift: stop and report.

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit   # toolkit.py:89
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    def _bound_text(self, parts: list[str]) -> str:                          # :365-397
        joined = "\n\n".join(parts); limit = self._max_result_chars           # :373-374
        if kept_parts:                                                       # :383
            kept = "\n\n".join(kept_parts); dropped_parts = len(parts) - len(kept_parts)   # :384-385
        else:                                                                # :386  (first part cut)
            ... kept = first[:cut] ...; dropped_parts = len(parts) - 1       # :387-392
        dropped_chars = len(joined) - len(kept)                              # :393
        return (                                                             # :394-397
            f"{kept}\n\n[truncated: {dropped_chars} more characters in {dropped_parts} further sections"
            " — lower top_k or narrow the query]"
        )

# packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py
_TAIL = "lower top_k or narrow the query]"                                   # :149
def test_bound_text_cuts_first_part_after_title(tmp_path: Path) -> None:    # :177 ; `assert "in 1 further sections" in out` :192
def test_bound_text_oversized_part_without_paragraph_break(tmp_path: Path) -> None:   # :224-229 (single part, cut)

# packages/ai-parrot/tests/mcp/test_pageindex_template.py
_MARKER_TAIL = "lower top_k or narrow the query]"                            # :73 — asserted by test_pageindex_serves_over_stdio; must stay
```

### Does NOT Exist
- ~~`_bound_text(parts, *, marker=...)`~~ — no new parameter; the signature is fixed.
- ~~`PageIndexToolkit.TRUNCATION_MARKER`~~ — no class constant; the f-strings live in the method.
- ~~a `## Decisions` entry in FEAT-842 pinning the marker~~ — its decisions are about LLM-less serving and the template; D4 needs no `supersedes:`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._bound_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Do not change which text is kept (the cut algorithm is FEAT-842 AC-6 and fully tested); only the
  marker sentence changes, and only in the `else:` (first-part-cut) branch.
- `k` keeps its meaning: parts not returned at all. `n` keeps its meaning: characters not returned.
- The tail stays byte-identical — `_TAIL` / `_MARKER_TAIL` assertions and the wiki quote depend on it.

---

## Implementation Blueprint

### Steps (in order)
1. Introduce a `first_cut` flag set in the `else:` branch — *why*: the marker needs to know whether the first section was cut.
2. Build the "in …" clause from `first_cut` and `dropped_parts` — *why*: D4's three variants.
3. Update the docstring — *why*: it documents the marker (and TASK-5332 quotes it).
4. Update the two tests — *why*: they assert the old wording for the cut case.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        if kept_parts:' packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py — inside _bound_text :383)
# REPLACE the block from `        if kept_parts:` through the closing `        )` of the return (verified: toolkit.py:383-397) with:
        first_cut = not kept_parts
        if kept_parts:
            kept = "\n\n".join(kept_parts)
            dropped_parts = len(parts) - len(kept_parts)
        else:
            first = parts[0]
            title_end = first.find("\n")
            title_end = len(first) if title_end == -1 else title_end
            cut = first.rfind("\n\n", title_end, max(limit, title_end))
            kept = first[:cut] if cut != -1 else first[: max(limit, title_end)]
            dropped_parts = len(parts) - 1
        dropped_chars = len(joined) - len(kept)
        if not first_cut:
            where = f"in {dropped_parts} further sections"
        elif dropped_parts:
            where = f"in this section and {dropped_parts} further sections"
        else:
            where = "in this section"
        return f"{kept}\n\n[truncated: {dropped_chars} more characters {where} — lower top_k or narrow the query]"

# docstring (verified anchor: `        """Join ``parts`` and apply ``max_result_chars``.` toolkit.py:366, occurrences 1):
# REPLACE the "Appends ..." sentence (:369-370) with:
#   Appends ``"\n\n[truncated: {n} more characters in {k} further sections — lower top_k or narrow the query]"``
#   when whole sections were dropped, or ``"... in this section[ and {k} further sections] — ..."`` when the
#   first section itself was cut.
```
**Why**: the kept-text algorithm (lines inside `else:`) is copied verbatim — only `first_cut` and
`where` are new. The single return keeps the tail literal in one place.

### `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    assert "in 1 further sections" in out' packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py)
# REPLACE `    assert "in 1 further sections" in out` (verified: test_toolkit_no_llm.py:192) with:
    assert "in this section and 1 further sections" in out

# occurrences: 1 (verified: grep -cF '    assert kept == ("## T\n" + "x" * 200)[:30]' packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py — :228)
# AFTER — insert below `    assert kept == ("## T\n" + "x" * 200)[:30]` (verified: :228)
    assert "in this section —" in out and "0 further" not in out

# APPEND at end of file
def test_bound_text_whole_sections_marker_unchanged(tmp_path: Path) -> None:
    """D4: when the first part fits, the marker keeps the FEAT-842 wording."""
    # FILL IN: three parts, limit fits exactly one -> "in 2 further sections" in out and "this section" not in out
```

### FILL IN checklist
- [ ] `test_bound_text_whole_sections_marker_unchanged` body — bounded by AC-11

---

## Acceptance Criteria

- [ ] AC-11 marker variants per spec §2 item 4; every `_TAIL` / `_MARKER_TAIL` assertion still passes.
- [ ] `test_toolkit_no_llm.py` and `tests/mcp/test_pageindex_template.py::test_pageindex_serves_over_stdio` pass.
- [ ] AC-13 `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py::test_pageindex_serves_over_stdio -q`

---

## Test Specification

See the MODIFY block for `test_toolkit_no_llm.py` above.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5330 is `done` in `sdd/tasks/index/pageindex-toolkit-fixes.json`.
2. Re-locate every anchor with `grep -nF` (earlier tasks shifted `toolkit.py`); mark `in-progress`, commit only the index.
3. Implement from the blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the two files; `parrot sdd task close TASK-5331 pageindex-toolkit-fixes verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
