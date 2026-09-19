# TASK-3495: Managed-page protection and the `adr` id namespace

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3479, TASK-3480
**Assigned-to**: unassigned

---

## Context

Spec §7 lists this as a known risk, with a sequencing requirement attached:

> Generic page bodies are mutable today: managed-page guards and CAS must land
> together **before review is enabled**.

An ADR record's authority lives in a JSON envelope inside its page body. Today
`wiki_note` (`tools.py:401`) and `LLMWikiToolkit.update_page` (`toolkit.py:825`)
will happily append prose to any page, which would corrupt that envelope and
make the record undecodable — silently destroying review history.

This task closes those holes on the **tool and toolkit** surfaces and teaches
the id grammar about `adr:`. The CLI's equivalent guards belong to TASK-3496,
which owns `cli.py`.

---

## Scope

- Add `adr` to `context._ID_KINDS` so `adr:doc:...` and `ns::adr:candidate:...`
  parse as page ids and render with their labels preserved.
- Add a shared `_reject_managed_page` guard next to `_reject_foreign_id` in
  `tools.py` and apply it in `WikiNoteTool._execute` and
  `WikiRememberTool._execute`.
- Apply the same guard in `LLMWikiToolkit.update_page` and `.remember`.
- Return `ADR_MANAGED_PAGE` as a structured error, never an exception.
- Test that a managed page is protected and ordinary pages are unaffected.

**NOT in scope**: the CLI `note` / `remember` guards (TASK-3496 owns `cli.py`),
the decision tools themselves (TASK-3494), CAS (TASK-3481).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/context.py` | MODIFY | Add `adr` to `_ID_KINDS` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `_reject_managed_page` + guards in note/remember |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | Guards in `update_page` and `remember` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_managed_page_protection.py` | CREATE | Protection + no-regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.models import ADR_CATEGORY, ADR_MANAGED_PAGE  # TASK-3479
```

`decisions/models.py` imports nothing from `parrot.knowledge.wiki` (TASK-3479),
so importing it from `tools.py` / `toolkit.py` creates no cycle. Import it at
**module scope** in `tools.py`; in `toolkit.py` follow whatever import style the
surrounding methods already use.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/context.py:40
_ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page|sym|issue|task|spec|insight"
#   Consumed by _ID_PREFIX_RE (line ~47) and _BARE_ID_PREFIX_RE (line ~52).

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:51 — THE PATTERN TO COPY
def _reject_foreign_id(store: BaseWikiStore, page_id: str) -> str | None:
    """Explain why a write cannot target ``page_id``, or ``None`` if it can."""

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiRememberTool(AbstractTool):                                  # line 302
    async def _execute(self, ...) -> ToolResult: ...                   # line 318
class WikiNoteTool(AbstractTool):                                      # line 401
    async def _execute(self, page_id: str, text: str) -> ToolResult: ...  # line 413
#   Its existing guard, the shape to mirror (tools.py:~428):
#       refusal = _reject_foreign_id(self._store, str(page["concept_id"]))
#       if refusal:
#           return ToolResult(success=False, status="error", result=None, error=refusal)

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:41
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix: str = "wiki"                                          # line 68
    async def update_page(self, wiki_name: str, page_id: str,
                          content: str, reason: Optional[str] = None) -> dict[str, Any]: ...  # line 825
    async def remember(self, ...) -> ...                               # line 882
```

### Does NOT Exist

- ~~a `category` check anywhere in the existing write path~~ — `WikiNoteTool`
  reads the page and appends to its body with no category inspection
  (`tools.py:413-433`). That is exactly the hole.
- ~~`ADR_MANAGED_PAGE` handling in `store.py`~~ — the store stays unaware of
  ADRs. The guard is at the authoring surfaces only.
- ~~a delete guard~~ — out of scope here. Spec §2 notes deletion is not a review
  action, but the delete surfaces are not part of this task.
- ~~`_ID_KINDS` being a list~~ — it is a single `|`-joined **string** consumed by
  two f-string regexes. Edit the string, not a collection.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/context.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_managed_page_protection.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiNoteTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiRememberTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py#LLMWikiToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#_reject_foreign_id"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Guard on the **page's stored `category`**, read from the store — not on the id
  prefix. An id can be spoofed; the stored category is what the codec wrote.
  Check the id prefix only as a cheap pre-filter when the page does not exist.
- The refusal is a structured error (`ToolResult(success=False, ...)` for tools,
  a returned dict or raised `ValueError` for the toolkit — match each method's
  existing failure convention). Never let an exception escape a tool.
- Ordinary pages must be entirely unaffected — that is half of AC10.

---

## Implementation Blueprint

### Steps (in order)

1. Extend `_ID_KINDS` — *why*: without it, `adr:doc:<sha1>` is not recognized as
   a page id, so the context renderer would print the raw id instead of eliding
   it and the namespace grammar `ns::adr:...` would not split.
2. Add `_reject_managed_page` beside `_reject_foreign_id` — *why*: one guard,
   one message, applied at every authoring surface.
3. Apply it in the two tools, then the two toolkit methods — *why*: both
   surfaces reach the same store, so guarding one is guarding nothing.

### `packages/ai-parrot/src/parrot/knowledge/wiki/context.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '_ID_KINDS = ' packages/ai-parrot/src/parrot/knowledge/wiki/context.py)
# REPLACE the line at packages/ai-parrot/src/parrot/knowledge/wiki/context.py:40:
#   _ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page|sym|issue|task|spec|insight"
# with:
_ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page|sym|issue|task|spec|insight|adr"
```

Extend the comment block above it (lines 36-39) with a sentence naming `adr` as
the FEAT-578 decision-page kind, matching how `sym` and the ledger kinds are
already annotated.

**Why**: `_ID_PREFIX_RE` and `_BARE_ID_PREFIX_RE` are built from this string, so
one edit teaches both the plain and the `ns::`-qualified grammar. Appending
rather than inserting keeps the existing alternation order untouched — `adr`
shares no prefix with any existing kind, so ordering is not load-bearing, but
leaving the rest byte-identical keeps the diff reviewable.

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY — the guard)

```python
# occurrences: 1 (verified: grep -c 'def _reject_foreign_id(store: BaseWikiStore, page_id: str) -> str | None:' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# AFTER — insert directly below the END of `_reject_foreign_id`
# (verified: it starts at packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:51
# and the next def is `_unknown_namespace_error` at line 108), i.e. immediately
# before `def _unknown_namespace_error(`:

def _reject_managed_page(page: dict[str, Any] | None, page_id: str) -> str | None:
    """Explain why a generic write cannot target ``page_id``, or ``None``.

    ADR pages (FEAT-578) hold a canonical JSON envelope that IS the decision
    record, including its audit history. Appending prose to that body would
    make the record undecodable and silently destroy review history, so the
    generic authoring surfaces refuse them; edits go through the typed
    review surface (``wikitoolkit adr review``).

    Args:
        page: The stored row, or ``None`` when the page does not exist yet.
        page_id: The id the caller asked to write.

    Returns:
        An error message, or ``None`` when the write may proceed.
    """
    # FILL IN: refuse when (page is not None and page.get("category") ==
    # ADR_CATEGORY) OR (page is None and the local part of page_id starts with
    # "adr:" — use context.split_namespaced_id so a qualified id is handled).
    # The message must contain the literal ADR_MANAGED_PAGE code so callers and
    # tests can match on it. Bounded by spec §2 "Existing authoring tools must
    # reject arbitrary note/update_page modification of adr bodies with
    # ADR_MANAGED_PAGE".
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY — apply in `WikiNoteTool`)

```python
# occurrences: 1 (verified: grep -c '        refusal = _reject_foreign_id(self._store, str(page\["concept_id"\]))' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# AFTER — insert directly below the existing foreign-id guard block in
# `WikiNoteTool._execute` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:413,
# guard at ~:428-431), i.e. after its `return ToolResult(...)` line and before
# `        stamp = datetime.now(tz=UTC)...`:

        managed = _reject_managed_page(page, page_id)
        if managed:
            return ToolResult(success=False, status="error", result=None, error=managed)
```

Apply the same two-line guard in `WikiRememberTool._execute`
(`tools.py:318`) at the point where it has resolved the target page —
*why*: `remember` can write an arbitrary `concept_id`, so it can clobber an
ADR page just as easily as `note` can.

### `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    async def update_page(' packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py)
# INSIDE `LLMWikiToolkit.update_page` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:825),
# immediately after it has loaded the existing page and before it writes:

        from parrot.knowledge.wiki.tools import _reject_managed_page

        managed = _reject_managed_page(existing_page, page_id)
        if managed:
            # FILL IN: return/raise using THIS method's existing failure
            # convention — read toolkit.py:825-880 and match what it already
            # does for a missing page, rather than inventing a third shape.
            raise NotImplementedError
```

Apply the same guard in `LLMWikiToolkit.remember` (`toolkit.py:882`).

**Why**: the toolkit is a separate agent-facing surface over the same store, so
guarding only `tools.py` would leave the hole open for any bot using
`LLMWikiToolkit`. The import is function-local to avoid a module-level cycle
between `toolkit.py` and `tools.py`.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_managed_page_protection.py` (CREATE)

```python
"""Generic writes cannot corrupt a managed ADR page (FEAT-578 M6, AC10)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page
from parrot.knowledge.wiki.decisions.models import DecisionRecord, ReviewEvent
from parrot.knowledge.wiki.store import WikiPageRecord
from parrot.knowledge.wiki.tools import WikiNoteTool, WikiRememberTool


@pytest.fixture
async def seeded(adr_store):
    """A stored ADR record carrying one review event."""
    record = DecisionRecord(
        decision_id="adr:doc:a", decision="use pgvector", origin="documented", source_status="accepted",
        review_history=[ReviewEvent(revision=1, action="accept", actor="human:m",
                                    timestamp="2026-01-01T00:00:00+00:00", reason="ok",
                                    before_sha1="b", after_sha1="a")],
    )
    await adr_store.upsert_pages([decision_to_page(record)])
    return adr_store, record


class TestManagedPageProtection:
    async def test_note_refuses_an_adr_page(self, seeded):
        store, _ = seeded
        result = await WikiNoteTool(store)._execute(page_id="adr:doc:a", text="a stray note")
        assert result.success is False
        assert "ADR_MANAGED_PAGE" in (result.error or "")

    async def test_refused_note_leaves_the_record_decodable(self, seeded):
        """The point of the guard: history must survive (AC6)."""
        store, record = seeded
        await WikiNoteTool(store)._execute(page_id="adr:doc:a", text="a stray note")
        decoded = decision_from_page(await store.get_page("adr:doc:a"))
        assert decoded == record
        assert len(decoded.review_history) == 1

    async def test_remember_cannot_overwrite_an_adr_page(self, seeded):
        # FILL IN: call WikiRememberTool with concept_id="adr:doc:a"; assert it
        # is refused with ADR_MANAGED_PAGE and the record still decodes
        raise NotImplementedError

    async def test_toolkit_update_page_refuses(self, seeded, tmp_path):
        # FILL IN: build LLMWikiToolkit over the seeded store and assert
        # update_page on "adr:doc:a" is refused using that method's own failure
        # convention, and the record still decodes
        raise NotImplementedError

    async def test_a_nonexistent_adr_id_is_also_refused(self, adr_store):
        """An id-prefix pre-filter closes the create-then-corrupt path."""
        result = await WikiNoteTool(adr_store)._execute(page_id="adr:doc:nope", text="x")
        assert result.success is False and "ADR_MANAGED_PAGE" in (result.error or "")

    async def test_namespaced_adr_id_is_refused(self, adr_store):
        # FILL IN: assert "other::adr:doc:a" is refused too (the foreign-id
        # guard may fire first — either refusal is acceptable, a SUCCESS is not)
        raise NotImplementedError


class TestOrdinaryPagesUnaffected:
    async def test_note_still_works_on_a_concept_page(self, adr_store):
        """AC10: existing behaviour is untouched."""
        await adr_store.upsert_pages([WikiPageRecord(concept_id="concept:x", title="X",
                                                     category="concept", body="body")])
        result = await WikiNoteTool(adr_store)._execute(page_id="concept:x", text="a note")
        assert result.success is True
        assert "a note" in (await adr_store.get_page("concept:x"))["body"]

    async def test_remember_still_works(self, adr_store):
        # FILL IN: assert an ordinary remember write succeeds unchanged
        raise NotImplementedError


class TestIdGrammar:
    @pytest.mark.parametrize("page_id", ["adr:doc:abc123", "adr:candidate:def456", "other::adr:doc:abc123"])
    def test_adr_ids_parse_as_page_ids(self, page_id):
        from parrot.knowledge.wiki.context import split_namespaced_id

        namespace, local = split_namespaced_id(page_id)
        assert local.startswith("adr:")

    def test_adr_stub_lines_keep_their_labels(self):
        """AC9: the generic renderer must not strip the [INFERRED / ...] prefix."""
        # FILL IN: build a stub row from decision_to_page of an inferred record
        # and assert context.stub_line's output still contains "INFERRED"
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `tools.py::_reject_managed_page` — category check + id pre-filter + `ADR_MANAGED_PAGE` message; bounded by spec §2
- [ ] `toolkit.py::update_page` / `::remember` — refusal matching each method's existing convention
- [ ] `test_managed_page_protection.py` — six test bodies

---

## Acceptance Criteria

- [ ] `adr` is in `_ID_KINDS`; `adr:doc:...` and `ns::adr:candidate:...` parse as page ids
- [ ] `wiki_note` and `wiki_remember` refuse an ADR page with a message containing `ADR_MANAGED_PAGE`
- [ ] `LLMWikiToolkit.update_page` and `.remember` refuse it too
- [ ] After a refused write the record still decodes and its `review_history` is intact (AC6)
- [ ] An `adr:` id with no stored page is refused as well
- [ ] Refusals are structured results, never escaping exceptions
- [ ] Ordinary pages behave exactly as before (AC10)
- [ ] Generic stub rendering preserves the origin/status label prefix (AC9)
- [ ] `store.py` gains no ADR awareness
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q` still passes (AC10)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_managed_page_protection.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Identity, storage, and concurrency" (final paragraphs) and §7 first risk.
2. **Verify the Codebase Contract** — confirm `context.py:40`, `tools.py:51`, `:318`, `:413`, `toolkit.py:825`, `:882`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** all three Validation Commands pass — the last two are the AC10 regression guard.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (native sonnet coder)
**Date**: 2026-09-19
**Notes**: Added `adr` to `_ID_KINDS` in `context.py` so `adr:doc:...` /
`adr:candidate:...` parse as page ids. Added a shared `_reject_managed_page`
guard (checks `page.get("category") == ADR_CATEGORY` first, falls back to an
id-prefix pre-filter for not-yet-existing pages) applied in `WikiNoteTool`,
`WikiRememberTool`, `LLMWikiToolkit.update_page`, and `LLMWikiToolkit.remember`,
returning a structured `ADR_MANAGED_PAGE` refusal instead of letting a generic
write corrupt a managed ADR record's JSON envelope/review history. 12 new
tests in `test_managed_page_protection.py`; `test_wiki_tools.py` (31/31,
AC10 regression guard) unaffected. Two pre-existing failures in
`test_mcp_server_namespaces.py` (`BASE_TOOLS` drift from FEAT-498's newer
wiki tools) verified unrelated via `git stash`/pop against unmodified HEAD —
left untouched, out of scope.

**Deviations from spec**: two, both required to satisfy the task's own stated
Acceptance Criteria (not scope creep): (1) `_reject_managed_page` in
`WikiNoteTool._execute` is placed immediately after `get_page()`, before the
"page not found" branch, rather than after the blueprint's literal insertion
point (which is only reached when `page is not None`) — otherwise an
`adr:` id with no stored page would not be refused, per the task's own AC.
(2) `WikiRememberTool`/`LLMWikiToolkit.remember` have no `concept_id`
parameter (they derive their own id deterministically); the blueprint's
literal "call with concept_id=..." instruction was infeasible, so the test
pre-computes the exact derived id and seeds an ADR page at it instead.

**Note for future task authoring**: this delivery was originally left
un-finalized in the per-spec index (still `in-progress`, file pointing at
`active/`) despite the code being merged — a bookkeeping slip by the
orchestrator, corrected here retroactively with no code changes.
