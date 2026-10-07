# TASK-4132: BasicAgent.handle_files — persist every upload, not only tabular ones

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4129
**Assigned-to**: unassigned

---

## Context

Spec §1 problem (1) and §3 Module 4. This is **the first of the two silent-drop
paths** the feature exists to close.

`BasicAgent.handle_files` (`bots/agent.py:365`) only understands `.xlsx`, `.xls` and
`.csv`. Everything else is read into a `BytesIO`, matches no DataFrame branch, and is
discarded without ever touching disk (`agent.py:404-418`). A `.docx` therefore never
becomes anything a Jira tool could reference.

> Note: the spec prose says "Agent.handle_files". The method is defined on
> **`BasicAgent`** (`bots/agent.py:38`); `Agent` (`:1520`) inherits it. Edit `BasicAgent`.

This is a **hard cut**: the return type changes from `List[str]` to a dict, and the
two existing tests that assert the list are updated in this task.

---

## Scope

- Change `BasicAgent.handle_files` to return
  `{"dataframes": [...], "files": [...], "errors": [...]}`.
- Keep the existing tabular branch intact: `.xlsx`/`.xls`/`.csv` still become DataFrames.
- Persist **every** upload — tabular ones too — via `SessionFileStore.put_bytes`, so a
  CSV can be both a DataFrame and an attachable file.
- Resolve the session id from `current_context()`; when unbound, record an entry in
  `errors` rather than raising — an upload must not fail because of binding.
- Update the two existing tests that assert the old `List[str]` contract.

**NOT in scope**: the HTTP handler (TASK-4133) · the store itself (TASK-4128/4129) ·
`jiratoolkit.py` (deferred module M3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `handle_files` hard cut + persistence |
| `packages/ai-parrot/tests/test_agent_module.py` | MODIFY | `test_handle_files_csv` asserts the new dict |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | `test_handle_files` asserts the new dict |
| `packages/ai-parrot/tests/test_session_upload.py` | CREATE | docx persistence + csv dual-path tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.file.session import SessionFileStore   # TASK-4128
from parrot.utils.helpers import current_context              # verified: packages/ai-parrot/src/parrot/utils/helpers.py:58
# already imported at the top of bots/agent.py (verified :1-27):
#   asyncio, pandas as pd, Path, Dict/List/Any/Optional, logging
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                      # line 38
    async def handle_files(self, attachments: Dict[str, Any]) -> List[str]:   # line 365
        # lines 387-402: per-file loop; FileField via `.file.read()`, else `.read()`,
        #                else the raw value; wrapped in io.BytesIO
        # lines 404-410: ONLY .xlsx/.xls/.csv produce a DataFrame
        # lines 411-418: df is None -> nothing stored, bytes dropped  <-- THE BUG
        # it calls self.add_dataframe(df, name=slug) and self.logger.info/error
class Agent(BasicAgent):                                           # line 1520

# packages/ai-parrot/tests/test_agent_module.py:143  — asserts `"data" in added`
# packages/ai-parrot/tests/test_basic_agent_new.py:133 — asserts `"data" in added`
```

### Does NOT Exist
- ~~`Agent.handle_files` as its own definition~~ — it is inherited from `BasicAgent`;
  editing `Agent` (`:1520`) would do nothing
- ~~a docx/pdf branch in `handle_files`~~ — only `.xlsx`, `.xls`, `.csv` (`:404-410`)
- ~~a `session_id` attribute on `BasicAgent`~~ — the session comes from
  `current_context()`, which `AbstractBot.session()` binds
- ~~a compatibility shim for the old `List[str]` return~~ — this is a hard cut by
  decision (spec §1, AC17); do not add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_agent_module.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_basic_agent_new.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_session_upload.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.handle_files",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileStore",
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#current_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the existing byte-extraction logic (`.file.read()` / `.read()` / raw) — it already
  handles aiohttp `FileField` and is covered by the tests you are updating.
- One failing file must not abort the others: collect per-file errors, never raise.
- `self.logger` is available on `BasicAgent`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the store import and a lazily-built `self._session_store` — *why*: constructing
   it per call would re-read config on every upload.
2. Rewrite the loop body so bytes are persisted first, then optionally parsed as a
   DataFrame — *why*: persistence must not depend on the parse succeeding.
3. Return the three-key dict — *why*: the handler (TASK-4133) distinguishes "stored
   nothing and registered nothing" from success, which is spec AC3.
4. Update the two existing tests last — *why*: they are the regression proof that the
   tabular behaviour survived the cut.

### `packages/ai-parrot/src/parrot/bots/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def handle_files(self, attachments: Dict\[str, Any\]) -> List\[str\]:' packages/ai-parrot/src/parrot/bots/agent.py)
# REPLACE — the signature and docstring at `async def handle_files(...)` (verified: bots/agent.py:365)
    async def handle_files(self, attachments: Dict[str, Any]) -> Dict[str, Any]:
        """Persist every uploaded file and register the tabular ones as DataFrames.

        HARD CUT (FEAT-639): previously returned List[str] of DataFrame names.

        Args:
            attachments: Mapping of filename to aiohttp FileField, file-like object,
                or raw bytes.

        Returns:
            {"dataframes": [str, ...],          # slugs registered via add_dataframe
              "files": [dict, ...],             # SessionFileRecord dicts, attachable by file_id
              "errors": [{"filename": str, "error": str}, ...]}
        """
        # FILL IN: keep the existing byte-extraction (FileField .file.read() / .read() /
        # raw value, bots/agent.py:387-402). For EVERY file: persist first via
        # self._session_store().put_bytes(session_id, filename, content, origin="upload"),
        # appending the record dict to "files"; then, ONLY for .xlsx/.xls/.csv, parse
        # with pd.read_excel/pd.read_csv and self.add_dataframe(df, name=slug) as today.
        # Per-file exceptions go into "errors" and never abort the loop.
        # Session id: ctx = current_context(); when ctx/ctx.session_id is missing, append
        # one {"filename": ..., "error": "no bound session"} entry per file and skip
        # persistence — the upload must not raise.
        # bounded by AC1 (docx persisted), AC3 (honest result), spec §3 M4
        raise NotImplementedError
```
**Why**: persistence comes *before* parsing so a malformed CSV still leaves an
attachable file — the old code lost the bytes whenever the parse branch did not match.
The three-key dict is what TASK-4133 turns into an honest HTTP response; do not change
the key names. Keep `add_dataframe` and the slug logic exactly as they are: the two
existing tests assert that behaviour and must keep passing.

```python
# occurrences: 1 (verified: grep -c '        added = await basic_agent.handle_files(attachments)' packages/ai-parrot/tests/test_agent_module.py)
# REPLACE — in `test_handle_files_csv` (verified: packages/ai-parrot/tests/test_agent_module.py:151)
        result = await basic_agent.handle_files(attachments)

        assert "data" in result["dataframes"]
        assert result["files"], "a CSV must ALSO be persisted as a session file"
```
**Why**: this is the dual-path assertion from spec §4 — a tabular file is both a
DataFrame and an attachable file. The remaining assertions in that test
(`basic_agent.dataframes["data"]`, the row count) stay unchanged.

```python
# occurrences: 1 (verified: grep -c '        added = await agent.handle_files(attachments)' packages/ai-parrot/tests/test_basic_agent_new.py)
# REPLACE — in `test_handle_files` (verified: packages/ai-parrot/tests/test_basic_agent_new.py:136)
        result = await agent.handle_files(attachments)

        assert "data" in result["dataframes"]
```
**Why**: the surrounding debug block in that test reads `added`; rename it to `result`
there too, or drop the debug block — it was a troubleshooting aid, not an assertion.

### FILL IN checklist
- [ ] `handle_files` body — persist-then-parse, per-file error collection, session
      lookup; bounded by AC1, AC3 and "never raise for one bad file"
- [ ] `_session_store()` accessor — lazy construction; bounded by "no per-call config read"
- [ ] new test bodies in `test_session_upload.py`; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] A `.docx` upload produces a resolvable handle in `result["files"]` (spec AC1)
- [ ] A `.csv` upload appears in BOTH `result["dataframes"]` and `result["files"]`
- [ ] `test_handle_files_csv` and `test_handle_files` pass against the new contract
- [ ] One unreadable file yields an `errors` entry and does not abort the others
- [ ] With no bound session the call returns errors instead of raising
- [ ] No compatibility shim for the old `List[str]` return exists in the diff (AC17)
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/agent.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_session_upload.py -q`
- `pytest packages/ai-parrot/tests/test_agent_module.py::TestBasicAgent::test_handle_files_csv -q`
- `pytest packages/ai-parrot/tests/test_basic_agent_new.py::test_handle_files -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_session_upload.py
import pytest


class TestHandleFilesPersistence:
    async def test_persists_docx(self, basic_agent, bound_session):
        """Spec AC1 — a .docx upload becomes a resolvable handle."""
        # FILL IN: attachments = {"report.docx": b"PK\x03\x04"}; assert files[0]["file_id"]

    async def test_csv_is_dataframe_and_file(self, basic_agent, bound_session):
        """A tabular upload takes both paths."""
        # FILL IN

    async def test_unreadable_file_does_not_abort_others(self, basic_agent, bound_session):
        """One bad file -> one errors entry, the rest still stored."""
        # FILL IN

    async def test_no_bound_session_reports_error(self, basic_agent):
        """Unbound -> errors, never an exception."""
        # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read the spec sections named in Context before writing code.
3. **Verify the Codebase Contract** — confirm every import and signature still exists;
   if anything moved, fix the contract in this file FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4132 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
