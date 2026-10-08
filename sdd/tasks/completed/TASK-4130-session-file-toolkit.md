# TASK-4130: SessionFileToolkit — request-scoped session binding, listing and generated files

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4128
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 Overview decision (3). This is the agent's **only** view of
the store: it is how a model discovers that handles exist at all.

The binding rule is the important part. Toolkits are long-lived, reusable instances,
so the session must be read per call from the task-local `RequestContext`
(`current_context()`, `utils/helpers.py:58`, bound by `AbstractBot.session()`), and
never stored on the toolkit. A call with no bound session is **refused**, not
defaulted — spec AC13.

`import_remote_file` is TASK-4131, so this task does not touch `FileManagerToolkit`.

---

## Scope

- Implement `SessionFileToolkit(AbstractToolkit)` with `tool_prefix = "sf"`.
- Implement `_require_session()` reading `current_context()`; raise
  `SessionFileError` with code `no_session` when unbound.
- Implement the `list_session_files` and `store_generated_file` tools.
- Write tests for binding refusal, per-session isolation of listings, and
  tool-name generation through the prefix.

**NOT in scope**: `import_remote_file` (TASK-4131) · store internals (TASK-4128/4129)
· wiring the toolkit into any agent's default tool set (not in this feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/session_files.py` | CREATE | The toolkit, session binding, two tools |
| `packages/ai-parrot/tests/tools/test_session_files_toolkit.py` | CREATE | Binding and isolation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit        # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:262
from parrot.utils.helpers import current_context        # verified: packages/ai-parrot/src/parrot/utils/helpers.py:58
from parrot.interfaces.file.session import SessionFileStore, SessionFileError  # TASK-4128
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:                                   # line 7
    def __init__(self, request=None, app=None, llm=None,
                 user_id=None, session_id=None, **kwargs)   # line 17
_current_ctx: ContextVar[Optional[RequestContext]]      # line 53
def current_context() -> Optional[RequestContext]:      # line 58
    """Returns the RequestContext bound to the current asyncio task, or None."""

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()                 # line 262
    tool_prefix: str | None = None                      # line 276
    def get_tools(...)                                  # line 522
    def _generate_tools(self) -> None                   # line 575
# Tool names are generated as f"{tool_prefix}{prefix_separator}{method_name}"
# (toolkit.py:267-270) — so `list_session_files` becomes `sf_list_session_files`.
```

### Does NOT Exist
- ~~`async def sf_list_session_files(...)`~~ — never write a prefixed method name.
  The prefix is applied by `_generate_tools` (`toolkit.py:575`); define
  `list_session_files` and let the toolkit rename it
- ~~`RequestContext.get_session_id()`~~ — it is a plain attribute, `ctx.session_id`
- ~~a default/fallback session id~~ — an unbound call must raise (spec AC13)
- ~~`SessionFileToolkit` in any registry or agent default tool list~~ — wiring is not
  in this feature

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/session_files.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/tools/test_session_files_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#current_context",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every tool method carries a Google-style docstring — it is the LLM-facing
  description, and it is how the model learns handles can be passed to Jira.
- `self.logger` comes from `AbstractToolkit`; do not create a module logger here.
- Never cache `session_id`, the root, or a handle map on `self`.

---

## Implementation Blueprint

### Steps (in order)
1. Define the toolkit with `tool_prefix = "sf"` and an injectable store — *why*:
   tests must pass a `tmp_path`-rooted store, never the real `OUTPUT_DIR`.
2. Implement `_require_session()` first — *why*: both tools call it, and AC13 is the
   criterion most likely to be silently skipped.
3. Implement the two tools with LLM-facing docstrings — *why*: the docstring is the
   only place the model is told what a `file_id` is for.

### `packages/ai-parrot/src/parrot/tools/session_files.py` (CREATE)
```python
"""Agent-facing view of the per-session file store."""
from __future__ import annotations

from typing import Any, Dict, Optional

from parrot.interfaces.file.session import SessionFileError, SessionFileStore
from parrot.tools.toolkit import AbstractToolkit      # verified: parrot/tools/toolkit.py:262
from parrot.utils.helpers import current_context      # verified: parrot/utils/helpers.py:58


class NoBoundSession(SessionFileError):
    """No RequestContext is bound to this asyncio task."""

    code = "no_session"


class SessionFileToolkit(AbstractToolkit):
    """Lists and stages the files of the CURRENT session, addressed by handle."""

    tool_prefix: str = "sf"      # -> sf_list_session_files, sf_store_generated_file

    def __init__(self, store: Optional[SessionFileStore] = None) -> None:
        super().__init__()
        self.store = store or SessionFileStore()

    def _require_session(self) -> str:
        """Return the bound session id, or raise NoBoundSession.

        Reads current_context(); never falls back to a default session, so two
        concurrent sessions cannot collide on one reusable toolkit instance.
        """
        # FILL IN: ctx = current_context(); raise NoBoundSession when ctx is None or
        # ctx.session_id is falsy; return str(ctx.session_id)
        # bounded by AC13 (refuse, never default)
        raise NotImplementedError

    async def list_session_files(self) -> Dict[str, Any]:
        """List the files available in this session.

        Returns {"files": [{"file_id", "filename", "mime_type", "size", "origin"}]}.
        Pass a file_id to jira_add_attachment or jira_add_comment to attach it.
        """
        session_id = self._require_session()
        # FILL IN: await self.store.list_files(session_id) and project each record to
        # the five documented keys — bounded by: never expose a filesystem path
        raise NotImplementedError

    async def store_generated_file(self, filename: str, content: str) -> Dict[str, Any]:
        """Store text this agent produced as a session file, returning its handle.

        Returns {"file_id", "filename", "size"}.
        """
        session_id = self._require_session()
        # FILL IN: encode content as UTF-8 and call store.put_bytes(..., origin="generated")
        raise NotImplementedError
```
**Why this shape**: `_require_session` is the single choke point for binding — if any
tool reads `current_context()` directly, the refusal guarantee is gone. The projection
in `list_session_files` deliberately drops the path: the model must never see one
(spec AC5). Do not rename the methods; the `sf_` names are generated, not written.

### FILL IN checklist
- [ ] `_require_session` — refusal conditions; bounded by AC13
- [ ] `list_session_files` projection — five keys, no path; bounded by spec AC5
- [ ] `store_generated_file` — encoding + origin; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `SessionFileToolkit().get_tools()` yields tools named `sf_list_session_files`
      and `sf_store_generated_file`
- [ ] A call with no bound `RequestContext` raises with code `no_session` (spec AC13)
- [ ] Two bound sessions see disjoint listings (spec AC7)
- [ ] No tool output contains a filesystem path (spec AC5)
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/session_files.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_session_files_toolkit.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_session_files_toolkit.py
import pytest
from parrot.interfaces.file.session import SessionFileStore
from parrot.tools.session_files import NoBoundSession, SessionFileToolkit
from parrot.utils.helpers import RequestContext, _current_ctx


@pytest.fixture
def toolkit(tmp_path):
    return SessionFileToolkit(store=SessionFileStore(root=tmp_path))


@pytest.fixture
def bind():
    """Bind a RequestContext for the duration of a test, then reset the ContextVar."""
    # FILL IN: set _current_ctx with RequestContext(session_id=...), yield, reset token


class TestSessionBinding:
    async def test_refuses_without_session(self, toolkit):
        with pytest.raises(NoBoundSession):
            await toolkit.list_session_files()

    async def test_lists_only_current_session(self, toolkit, bind):
        """Files stored under s1 are invisible while s2 is bound."""
        # FILL IN

    def test_tool_names_carry_the_prefix(self, toolkit):
        names = {t.name for t in toolkit.get_tools()}
        assert "sf_list_session_files" in names

    async def test_output_has_no_path(self, toolkit, bind):
        """Spec AC5 — the model never sees a filesystem path."""
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
8. `scripts/sdd/close_task.sh TASK-4130 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any

## Completion Note

Merged by sdd-coder engine; targeted session-file store/toolkit tests pass.
