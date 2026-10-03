# TASK-4026: Extract attrs at Markdown and vault ingest boundaries

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4022, TASK-4023
**Assigned-to**: unassigned

---

## Context

Implement M2/AC4. Parse raw Markdown/rst before body wrapping/truncation; set record.attrs after its construction (the spec comment at the summary anchor precedes record creation, so do not reference an unbound record). For vault notes use note.frontmatter. Keep imports execution-local where needed to preserve hook startup. Leave jira_render and _ingest_files unchanged. A Jira-rendered issue enters through the Markdown path and retains x_assignee_id.

---

## Scope

Implement M2/AC4. Parse raw Markdown/rst before body wrapping/truncation; set record.attrs after its construction (the spec comment at the summary anchor precedes record creation, so do not reference an unbound record). For vault notes use note.frontmatter. Keep imports execution-local where needed to preserve hook startup. Leave jira_render and _ingest_files unchanged. A Jira-rendered issue enters through the Markdown path and retains x_assignee_id.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | Frontmatter may be lost by body transformations; extracting it here preserves AC4. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py` | MODIFY | The vault parser already holds the original YAML metadata. |
| `packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py` | CREATE | Compare bodies/edges as well as attrs and check absence of email fields. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from parrot.knowledge.wiki.entities import normalize_frontmatter, parse_leading_yaml  # planned in TASK-4022; not present before that task
from parrot.knowledge.wiki.entities import normalize_frontmatter  # planned in TASK-4022; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.repo_scan as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
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

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:524
def _markdown_summary(content: str) -> str:

# packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:118
def scan_vault(
    root: Path,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> tuple[RepoScan, VaultScanStats]:

# packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py:497
def render_issue_document(
    issue: JiraIssue,
    *,
    fetched_at: datetime,
    existing: str | None = None,
    repo_pages: list[str] | None = None,
) -> str:
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#build_file_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#_markdown_summary",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py#scan_vault",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py#render_issue_document"
  ]
}
```

---

## Implementation Notes

TASK-4022: consumes normalize_frontmatter and parse_leading_yaml; TASK-4023: consumes WikiPageRecord.attrs

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` (MODIFY)

Anchor `        summary = _markdown_summary(content) or rel_path` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:643`.

```python
def _document_attrs(content: str) -> dict[str, str]:
    """Normalize leading document frontmatter without altering the source body."""
    from parrot.knowledge.wiki.entities import normalize_frontmatter, parse_leading_yaml
    fm = parse_leading_yaml(content)
    return normalize_frontmatter(fm, source="markdown").to_rows() if fm is not None else {}
# FILL IN: set record.attrs after WikiPageRecord construction, only for DOC_SUFFIXES.
# Keep summary computation/body wrapping unchanged and parse full original content.
```

**Why**: Frontmatter may be lost by body transformations; extracting it here preserves AC4.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py` (MODIFY)

Anchor `        scan.files.append(FileSlice(rel_path=rel, record=record))` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:171`.

```python
# Immediately before scan.files.append, while note and record are available:
from parrot.knowledge.wiki.entities import normalize_frontmatter
record.attrs = normalize_frontmatter(note.frontmatter, source="vault").to_rows()
# Keep the import in scan_vault execution if module-level import affects hook startup.
```

**Why**: The vault parser already holds the original YAML metadata.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.repo_scan as subject


def test_markdown_and_jira_attrs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify markdown and jira attrs."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_vault_aliases_and_body_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify vault aliases and body parity."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_no_frontmatter_build_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify no frontmatter build parity."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Compare bodies/edges as well as attrs and check absence of email fields.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Markdown, Jira-rendered documents and FEAT-481 vault notes receive normalized attrs.
- [ ] Bodies, summaries, source IDs, symbols and edges stay identical to pre-feature values.
- [ ] Non-document/no-frontmatter/malformed inputs retain empty attrs and do not fail build.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py -q`
- `pytest tests/knowledge/wiki/test_repo_scan.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_vault_scan.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_jira_render.py -q`

---

## Test Specification

- Markdown, Jira-rendered documents and FEAT-481 vault notes receive normalized attrs.
- Bodies, summaries, source IDs, symbols and edges stay identical to pre-feature values.
- Non-document/no-frontmatter/malformed inputs retain empty attrs and do not fail build.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4026`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
