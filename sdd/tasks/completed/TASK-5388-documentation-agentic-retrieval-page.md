# TASK-5388: Documentation — PageIndex agentic retrieval page

**Feature**: FEAT-849 — PageIndex Toolkit Tech Debt
**Spec**: `sdd/specs/pageindex-toolkit-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5385, TASK-5386, TASK-5387
**Assigned-to**: unassigned

**Discovered-from**: `issue:2e4dfac0d686`

---

## Context

Implements spec §4 FR-5.3 and §5 AC-10 — the `docs.policy: required` task for FEAT-849.
Completes the closure of `issue:2e4dfac0d686` (its documentation-only items 4 and 5) and
documents the behaviour change TASK-5385 made for `issue:d34c567792ef`.

`wiki/knowledge/pageindex-agentic-retrieval.md` is the integrator-facing page for stage-2
retrieval. Three things in it are now wrong or missing once TASK-5385…5387 land:

- its `### stopped values and precedence` list does not mention `provider_error`, and its
  closing sentence ("Exceptions still propagate") is no longer true for a provider failure;
- nothing on the page states the cap-fill / tie semantics (issue item 4) or the per-instance
  serialisation limit (issue item 5);
- nothing documents that a byte-identical re-import is now an idempotent skip.

This task is last in the graph because it documents symbols and behaviour the other three
tasks create.

---

## Scope

- Add `provider_error` to the page's `stopped` precedence list and correct the
  "Exceptions still propagate" sentence.
- Add the cap-fill / provider-done tie semantics and the per-toolkit serialisation limit to
  the page's Gotchas.
- Add a short "same-source re-import" note covering the `reused: True` behaviour.
- Extend `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py` so the page's
  new content is checked the way the existing names are.

**NOT in scope**:
- Any source change. **Do not touch `toolkit.py` or `agentic.py`** — their docstrings are
  written by TASK-5386 and TASK-5387.
- Other wiki pages' content. Only add a link if the docs gate demands one.
- Rewriting sections unrelated to FEAT-849.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-agentic-retrieval.md` | MODIFY | `provider_error`, cap-fill/tie, serialisation limit, re-import note |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py` | MODIFY | Assert the new page content |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase at `dev`.
> Do NOT invent any import, attribute, or method not listed here.

### Verified Imports

`test_agentic_docs.py` imports exactly one thing today (verified
`test_agentic_docs.py:3`); keep it:

```python
from pathlib import Path
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py:5-6 (verified)
REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-agentic-retrieval.md"

# test_agentic_docs.py:9 — the test whose name tuple this task extends
def test_page_has_frontmatter_api_and_reasons() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "ReadLedger", "validate_citations", "EvidenceBundle", "agentic_retrieve",
        "clone_for_tools", "bad_address", "revision_unread", "revision_unavailable",
        "segment_unread", "empty_excerpt", "excerpt_not_found", "outside_covered_ranges",
        "no_tool_calls", "max_tool_calls", "parse_error",
    ):
        assert name in text

# test_agentic_docs.py:30 and :36 — the other two tests; leave them untouched
def test_related_pages_link_new_page() -> None: ...
def test_local_mcp_exclude_slot_names_the_agentic_tool() -> None: ...
```

Page structure, verified by line number in
`wiki/knowledge/pageindex-agentic-retrieval.md`:

```
1    --- / title: / summary:   (frontmatter)
8    ## Purpose
25   ## Public API
51   ## Configuration & Parameters
61   | `agentic_max_tool_calls` | `20` | ... |   (table row)
72   ### Snapshot pinning
121  ### Read budget and clipping
130  ## Usage Examples
165  ## Gotchas
213  ### `stopped` values and precedence     <-- numbered list 1..6 ends at line 227
229  "Exceptions still propagate: ..."       <-- the sentence to correct
232  ### Other behaviour to know             <-- bullet list
244  ## Related
```

The `stopped` list is numbered **1 `timeout` → 2 `max_tool_calls` → 3 `parse_error` →
4 `budget` → 5 `no_tool_calls` → 6 `answered`**, introduced by "When several conditions
hold, the first one in this list wins" (verified `:215`).

### Does NOT Exist

- ~~A `provider_error` mention anywhere in the page today~~ — verify with
  `grep -c provider_error wiki/knowledge/pageindex-agentic-retrieval.md` (expect 0 before
  this task).
- ~~`wiki/knowledge/pageindex-toolkit-tech-debt.md`~~ — FEAT-849 declares no new page; the
  spec's `docs.pages` lists only `wiki/knowledge/pageindex-agentic-retrieval.md`. Do not
  create one.
- ~~`parrot sdd techwiki check --feature FEAT-849`~~ — the flag is `--spec <path>`; see
  Validation Commands.
- ~~`test_agentic_docs.py` having a `toolkit` fixture~~ — it is a pure file-content test
  module with no fixtures and no `pytest` import.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/pageindex-agentic-retrieval.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Precedence order is a claim about the code.** `provider_error` is set in the
  `asyncio.wait` branch *before* answer parsing and skips both the parse and validation
  guards (TASK-5386, FR-4.4), so it ranks with `timeout`/`max_tool_calls` — above
  `parse_error`. Read the merged `agentic.py` and place it where the code actually puts it;
  do not guess from this note.
- **Do not renumber the existing list wrongly.** Inserting `provider_error` shifts the
  numbers of the items below it — update all of them.
- **The page is generated-adjacent but hand-written.** Match its existing voice: short
  declarative sentences, backticked identifiers, a bold lead-in for each Gotchas bullet.
- **Frontmatter stays** (`---\ntitle: ` / `summary: `) — the docs test asserts it.
- The docs gate (`parrot sdd techwiki check`) must pass for the spec's declared
  `api_modules`: `parrot.knowledge.pageindex.agentic` and `parrot.knowledge.pageindex.toolkit`.

### References in Codebase

- `wiki/knowledge/pageindex-agentic-retrieval.md:232-242` — the "Other behaviour to know"
  bullet style to follow.
- `sdd/templates/techwiki-page.md` — the page template, for frontmatter conventions.

---

## Implementation Blueprint

### Steps (in order)

1. Read the merged `agentic.py` and `toolkit.py` docstrings first — *why*: this page must
   agree with what TASK-5386/5387 actually wrote, not with this task's summary of it.
2. Insert `provider_error` into the `stopped` precedence list and renumber — *why*: FR-5.3.
3. Correct the "Exceptions still propagate" sentence — *why*: it is now false for a
   provider failure, and a wrong sentence is worse than a missing one.
4. Add three Gotchas bullets (cap-fill, tie, serialisation) — *why*: FR-5.1/FR-5.2.
5. Add the same-source re-import note — *why*: FR-5.3, second half.
6. Extend `test_agentic_docs.py` — *why*: AC-10 needs the page checked, not just written.

### `wiki/knowledge/pageindex-agentic-retrieval.md` (MODIFY — `stopped` list)

```markdown
<!-- occurrences: 1 (verified: grep -c '2. `max_tool_calls` — the call cap was reached.' wiki/knowledge/pageindex-agentic-retrieval.md) -->
<!-- AFTER — insert a new numbered item below item 2 (verified: :220-221), then renumber
     the items that follow (parse_error 3→4, budget 4→5, no_tool_calls 5→6, answered 6→7) -->

3. `provider_error` — the provider call raised. The exception is logged and not re-raised: there is no answer, no
   repair call and no citation validation, while the reads already charged to the budget remain in `reads` and
   `chars_read`. `asyncio.CancelledError` is never converted — an external cancellation still propagates.
```

**Why**: FR-5.3 and spec D-2. It is placed at rank 3 because `provider_error` short-circuits
the parse and validation branches exactly as `timeout` and `max_tool_calls` do, so it can
never be overwritten by `parse_error`, `budget` or `no_tool_calls`. The bullet states both
halves of the contract — what is lost (answer, citations) and what survives (reads,
chars_read) — because that is what a caller has to handle.

### `wiki/knowledge/pageindex-agentic-retrieval.md` (MODIFY — exceptions sentence)

```markdown
<!-- occurrences: 1 (verified: grep -c 'Exceptions still propagate' wiki/knowledge/pageindex-agentic-retrieval.md) -->
<!-- REPLACE the paragraph at :229 -->

Some exceptions still propagate: an external cancellation of the caller is re-raised after cleanup rather than
returned as a bundle, and `ValueError` is raised for invalid arguments or a missing LLM. A failure of the provider
call itself does **not** propagate — it is returned as `stopped="provider_error"` (see above).
```

**Why**: the original sentence was an unqualified "exceptions propagate", which TASK-5386
makes false for the most common failure. Correcting it in place keeps the two statements
adjacent so they cannot drift.

### `wiki/knowledge/pageindex-agentic-retrieval.md` (MODIFY — Gotchas bullets)

```markdown
<!-- occurrences: 1 (verified: grep -c '\- \*\*No persistence.\*\*' wiki/knowledge/pageindex-agentic-retrieval.md) -->
<!-- AFTER — append below the `- **No persistence.**` bullet, the last of the
     "Other behaviour to know" list (verified: :242) -->

- **Cap-fill ends the loop immediately.** The controller stops the request as soon as the last admitted tool call
  completes, so a model that uses *exactly* `max_tool_calls` reads returns `stopped="max_tool_calls"` with no answer.
  Size `agentic_max_tool_calls` one above the read count you expect.
- **A provider-done / stop tie resolves to `max_tool_calls`.** When the provider finishes in the same tick the cap is
  reached, both are reported and the stop branch wins — a completed answer is discarded. This is the same remedy:
  leave one call of headroom.
- **One agentic request at a time per toolkit.** A single lock guards the whole request, so a second concurrent caller
  waits for it and, if its own `timeout_s` expires first, gets a `stopped="timeout"` bundle with no candidates. Scale
  out with separate `PageIndexToolkit` instances, not with concurrent calls on one.
- **A byte-identical re-import is a no-op.** Importing the same source twice into one tree splices nothing and mints no
  generation: the call returns the existing `doc_id` and `revision` with `reused: true` and an empty `new_node_ids`.
  Changed bytes under the same name still get their own suffixed `doc_id`, and an explicit `doc_id=` always splices.
```

**Why**: FR-5.1, FR-5.2 and FR-5.3. Each bullet gives the behaviour, the observable symptom
and the remedy, matching the list's existing bold-lead-in style. The re-import bullet lives
here rather than in a new section because it is a property a stage-2 caller hits through the
same toolkit, and the page already carries ingest-adjacent gotchas.

### `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        "parse_error",' test_agentic_docs.py)
# MODIFY — add the new identifier to the name tuple of
# `test_page_has_frontmatter_api_and_reasons` (verified: test_agentic_docs.py:28)
        "parse_error",
        "provider_error",
```

```python
# occurrences: 1 (verified: grep -c 'def test_local_mcp_exclude_slot_names_the_agentic_tool' test_agentic_docs.py)
# AFTER — append below that test, the module's last (verified: test_agentic_docs.py:36-39)


def test_page_documents_cap_fill_lock_and_reuse() -> None:
    """AC-10: the page states the termination, concurrency and re-import semantics."""
    text = PAGE.read_text(encoding="utf-8")
    # FILL IN: assert one distinctive phrase per documented semantic — cap-fill, the
    # provider-done/stop tie, the one-request-per-toolkit lock, and `reused` — choosing
    # substrings that are specific enough to fail if a section is deleted but not so long
    # that reflowing a sentence breaks the test. Bounded by AC-10 and FR-5.1/5.2/5.3.
    raise NotImplementedError
```

**Why**: the module's whole contract is "the page says these things", so the new semantics
belong in the same shape — a name added to the existing tuple plus one focused test. The
`FILL IN` deliberately leaves phrase choice open: it must be made against the final wording
written above, and over-long substrings make the test brittle to reflowing.

### FILL IN checklist

- [ ] `test_agentic_docs.py::test_page_documents_cap_fill_lock_and_reuse` — pick one
      distinctive substring per semantic; bounded by AC-10 and brittleness (no full
      sentences).
- [ ] `wiki/knowledge/pageindex-agentic-retrieval.md` — confirm `provider_error`'s rank
      against the merged `agentic.py` before renumbering; bounded by Key Constraints.

---

## Acceptance Criteria

- [ ] AC-10 — the page documents `provider_error`, the cap-fill / tie semantics, the
      per-instance serialisation limit and same-source re-import.
- [ ] The `stopped` precedence list is correctly renumbered and matches the merged code.
- [ ] The "Exceptions still propagate" paragraph no longer contradicts `provider_error`.
- [ ] `test_agentic_docs.py` passes, including the new test and the extended name tuple.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-toolkit-tech-debt.spec.md --root .` passes.
- [ ] Frontmatter (`title:` / `summary:`) is intact.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py -q`

> Also run, outside the pytest set:
> `parrot sdd techwiki check --spec sdd/specs/pageindex-toolkit-tech-debt.spec.md --root .`

---

## Test Specification

`packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py`:
`"provider_error"` added to the name tuple of
`test_page_has_frontmatter_api_and_reasons`, plus a new
`test_page_documents_cap_fill_lock_and_reuse` asserting one distinctive phrase per
documented semantic.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-toolkit-tech-debt --feature-id FEAT-849`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5385, TASK-5386 and TASK-5387 must all be `"done"` in
   `sdd/tasks/index/pageindex-toolkit-tech-debt.json`; this page documents what they wrote
4. **Verify the Codebase Contract** — re-grep every anchor and re-read the merged
   `agentic.py` / `toolkit.py` docstrings before writing a word of the page
5. **Update status** in `sdd/tasks/index/pageindex-toolkit-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:` marker
7. **Verify** by running the Validation Commands with
   `PYTHONPATH=<wt>/packages/ai-parrot/src`, plus the techwiki check
8. **Commit** — stage only the two files this task lists; **no source files**
9. **Close the task**: `parrot sdd task close TASK-5388 pageindex-toolkit-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code session ai-parrot-b5 (/sdd-fix d34c567792ef)
**Date**: 2026-11-09
**Notes**: `provider_error` was placed at rank 3 of the `stopped` precedence list, verified
against the merged `agentic.py`: it is set in the `asyncio.wait` else-branch before answer
parsing and is in both guard sets, so `parse_error`, `budget` and `no_tool_calls` can never
overwrite it, while `timeout` and `max_tool_calls` are decided earlier. Items 3-6 were
renumbered to 4-7.

The blanket "Exceptions still propagate:" paragraph was corrected — it was false for the most
common failure once TASK-5386 landed.

Four Gotchas bullets added (cap-fill, the provider-done/stop tie, the per-instance lock, the
re-import no-op), each with behaviour + symptom + remedy in the list's existing style.

`test_agentic_docs.py` gained `"provider_error"` in the name tuple plus two tests:
`test_page_documents_cap_fill_lock_and_reuse` (one distinctive phrase per semantic) and
`test_page_does_not_claim_every_exception_propagates`, which fails if the corrected paragraph is
ever reverted. 5/5 pass; 40/40 across the three agentic modules.
`parrot sdd techwiki check --spec ... --root .` → "Docs: required — ok".

**Deviations from spec**: none, with one addition — the second docs test
(`test_page_does_not_claim_every_exception_propagates`) was not in the task's Test Specification.
It was added because correcting a false sentence is worthless if nothing guards the correction,
and the task's own Steps list the correction as step 3.
