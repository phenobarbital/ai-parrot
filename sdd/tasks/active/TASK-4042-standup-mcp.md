# TASK-4042: Read-only-by-default wiki_standup MCP tool

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4040
**Assigned-to**: unassigned

---

## Context

Implement M7 MCP surface. Add WikiStandupInput with exact spec fields and defaults, WikiStandupTool and factory registration when root+config are supplied (matching its required constructor context). Preserve context-free create_wiki_tools callers that cannot construct a standup tool; document/test this explicit guard. Map store/write_file/use_llm independently to pipeline flags. Passed federated stores are for reading only; writes must resolve the true local plane via root/config, never a namespace-scoped facade. Return Markdown and brief_id/written_page/written_file/diagnostics from the document receipt. Validate date/horizon before execution. Update every count-sensitive server expectation affected by contextful registration, not unrelated lists.

---

## Scope

Implement M7 MCP surface. Add WikiStandupInput with exact spec fields and defaults, WikiStandupTool and factory registration when root+config are supplied (matching its required constructor context). Preserve context-free create_wiki_tools callers that cannot construct a standup tool; document/test this explicit guard. Map store/write_file/use_llm independently to pipeline flags. Passed federated stores are for reading only; writes must resolve the true local plane via root/config, never a namespace-scoped facade. Return Markdown and brief_id/written_page/written_file/diagnostics from the document receipt. Validate date/horizon before execution. Update every count-sensitive server expectation affected by contextful registration, not unrelated lists.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | Explicit construction context prevents accidental default-directory writes. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_mcp.py` | CREATE | Inject a foreign read facade and assert only the real local plane changes. |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` | MODIFY | These existing tests assert exact tool sets and must change alongside registration. |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` | MODIFY | These existing tests assert exact tool sets and must change alongside registration. |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` | MODIFY | These existing tests assert exact tool sets and must change alongside registration. |
| `tests/knowledge/wiki/test_mcp_server_structural.py` | MODIFY | These existing tests assert exact tool sets and must change alongside registration. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
from typing import Any, Literal  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel  # stdlib or existing pyproject dependency/test environment
from parrot.tools.abstract import AbstractTool, ToolResult  # verified source packages/ai-parrot/src/parrot/tools/abstract.py
from parrot.knowledge.wiki.store import BaseWikiStore  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
from parrot.knowledge.wiki.project import WikiProjectConfig  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.tools as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:514
class WikiStatusTool(AbstractTool):

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:530
class VaultIngestTool(AbstractTool):

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:807
def create_wiki_tools(
    store: BaseWikiStore,
    root: Path | None = None,
    config: WikiProjectConfig | None = None,
    ledger_service: Union["LedgerService", None] = None,
) -> list[AbstractTool]:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382
class WikiProjectConfig(BaseModel):
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/standup/test_mcp.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_mcp.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/knowledge/wiki/test_mcp_server_structural.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiStatusTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#VaultIngestTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#create_wiki_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig"
  ]
}
```

---

## Implementation Notes

TASK-4040: consumes run, StandupOptions and write receipts

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)

Anchor `    if ledger_service is not None:` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:840`.

```python
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.project import WikiProjectConfig
# Add input model and tool beside existing wiki tool classes; retain current imports.
class WikiStandupInput(BaseModel):
    """Explicit brief options; persistence and model calls are opt-in over MCP."""
    period: Literal["day", "week", "month"] = "day"
    date: str | None = None
    team: bool = False
    horizon_days: int | None = None
    language: Literal["en", "es"] | None = None
    store: bool = False
    write_file: bool = False
    use_llm: bool = False
class WikiStandupTool(AbstractTool):
    """Render a wiki brief; write only when explicitly requested, to local storage."""
    name = "wiki_standup"
    description = "Render a daily, weekly or monthly wiki brief. Read-only unless writes are explicitly enabled."
    args_schema = WikiStandupInput
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None:
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._root = root
        self._config = config
    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Run the shared pipeline and return Markdown with write receipts."""
        # FILL IN: validate/map args, preserve true local writer and format receipt; AC14.
        raise NotImplementedError
# Before the ledger conditional inside create_wiki_tools:
# if root is not None and config is not None:
#     tools.append(WikiStandupTool(store, root, config))
```

**Why**: Explicit construction context prevents accidental default-directory writes.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_mcp.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.tools as subject


def test_readonly_default_and_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify readonly default and schema."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_local_only_optin_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify local only optin writes."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_factory_context_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify factory context guard."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Inject a foreign read facade and assert only the real local plane changes.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` (MODIFY)

Anchor `class TestWikiMCPServerIntegration:` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py:57`.

```python
# FILL IN: update contextful expected tool sets/counts for wiki_standup.
# Keep context-free create_wiki_tools(store) expectations unchanged.
# Assert existing tools still register and the new schema defaults to no writes.
# Preserve the existing structural/vault/ledger/namespace assertions; AC14.
```

**Why**: These existing tests assert exact tool sets and must change alongside registration.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` (MODIFY)

Anchor `BASE_TOOLS = {` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py:16`.

```python
# FILL IN: update contextful expected tool sets/counts for wiki_standup.
# Keep context-free create_wiki_tools(store) expectations unchanged.
# Assert existing tools still register and the new schema defaults to no writes.
# Preserve the existing structural/vault/ledger/namespace assertions; AC14.
```

**Why**: These existing tests assert exact tool sets and must change alongside registration.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` (MODIFY)

Anchor `BASE_TOOLS = {` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py:20`.

```python
# FILL IN: update contextful expected tool sets/counts for wiki_standup.
# Keep context-free create_wiki_tools(store) expectations unchanged.
# Assert existing tools still register and the new schema defaults to no writes.
# Preserve the existing structural/vault/ledger/namespace assertions; AC14.
```

**Why**: These existing tests assert exact tool sets and must change alongside registration.

---

### `tests/knowledge/wiki/test_mcp_server_structural.py` (MODIFY)

Anchor `"wiki_status",` — occurrences: 1 (verified: `grep -F -c`), `tests/knowledge/wiki/test_mcp_server_structural.py:35`.

```python
# FILL IN: update contextful expected tool sets/counts for wiki_standup.
# Keep context-free create_wiki_tools(store) expectations unchanged.
# Assert existing tools still register and the new schema defaults to no writes.
# Preserve the existing structural/vault/ledger/namespace assertions; AC14.
```

**Why**: These existing tests assert exact tool sets and must change alongside registration.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_mcp.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `tests/knowledge/wiki/test_mcp_server_structural.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Default MCP call performs zero page/file/cache/audit writes and no model call.
- [ ] Explicit store=true writes only local plane; write_file is independent and receipts reflect actual success.
- [ ] Factory/server expose wiki_standup with root+config, preserve no-context callers and existing tools.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_mcp.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`
- `pytest tests/knowledge/wiki/test_mcp_server_ledger.py -q`

---

## Test Specification

- Default MCP call performs zero page/file/cache/audit writes and no model call.
- Explicit store=true writes only local plane; write_file is independent and receipts reflect actual success.
- Factory/server expose wiki_standup with root+config, preserve no-context callers and existing tools.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4042`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
