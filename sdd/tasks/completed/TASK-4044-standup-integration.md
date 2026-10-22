# TASK-4044: Cross-source SQLite brief and roll-up integration coverage

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4026, TASK-4024, TASK-4041, TASK-4042
**Assigned-to**: unassigned

---

## Context

Implement the spec integration matrix as new package-local test files. Seed a temporary SQLite plane with vault frontmatter/Jira-rendered Markdown via real scanners, memories, ADR records, ledger events and task indexes. Freeze now and isolate PARROT_HOME; never touch a user plane/network/provider. Run day then next-day CLI and assert exact persisted items/delta/output, then three daily briefs plus week/month roll-ups. Exercise Spanish headings, personal/team filters, missing namespace and failing model. Compare code-only build bodies/edges with baseline and Jira-built attrs against the store query contract. Keep fixtures local to these test modules: no shared conftest changes/exclusive resource requirement.

---

## Scope

Implement the spec integration matrix as new package-local test files. Seed a temporary SQLite plane with vault frontmatter/Jira-rendered Markdown via real scanners, memories, ADR records, ledger events and task indexes. Freeze now and isolate PARROT_HOME; never touch a user plane/network/provider. Run day then next-day CLI and assert exact persisted items/delta/output, then three daily briefs plus week/month roll-ups. Exercise Spanish headings, personal/team filters, missing namespace and failing model. Compare code-only build bodies/edges with baseline and Jira-built attrs against the store query contract. Keep fixtures local to these test modules: no shared conftest changes/exclusive resource requirement.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_integration.py` | CREATE | Use local fixture helpers with complete behavior and independent expected results; no implementation-mirroring assertions. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.pipeline as subject  # planned in TASK-4040; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:572
def build_file_slice(
    root: Path,
    rel_path: str,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    symbol_depth: int = 2,
) -> FileSlice | None:

# packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py:497
def render_issue_document(
    issue: JiraIssue,
    *,
    fetched_at: datetime,
    existing: str | None = None,
    repo_pages: list[str] | None = None,
) -> str:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:878
class SQLiteWikiStore(BaseWikiStore):

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382
class WikiProjectConfig(BaseModel):
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/standup/test_integration.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#build_file_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py#render_issue_document",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig"
  ]
}
```

---

## Implementation Notes

TASK-4026: consumes actual source-boundary attrs; TASK-4024: consumes backend parity coverage; TASK-4041: consumes public CLI dispatch; TASK-4042: consumes read-only and local-write tool

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_integration.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.pipeline as subject


def test_standup_end_to_end_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify standup end to end sqlite."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_standup_rollup_week_month(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify standup rollup week month."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_build_parity_and_jira_attrs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify build parity and jira attrs."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use local fixture helpers with complete behavior and independent expected results; no implementation-mirroring assertions.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_integration.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] A real SQLite cross-source run covers every intended section and correct stored attrs/file output.
- [ ] Next-day delta and week/month daily source lists are deterministic under injected time.
- [ ] Code-only build parity and Jira ingest attrs are verified without network; MCP default leaves all storage unchanged.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_integration.py -q`

---

## Test Specification

- A real SQLite cross-source run covers every intended section and correct stored attrs/file output.
- Next-day delta and week/month daily source lists are deterministic under injected time.
- Code-only build parity and Jira ingest attrs are verified without network; MCP default leaves all storage unchanged.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4044`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
