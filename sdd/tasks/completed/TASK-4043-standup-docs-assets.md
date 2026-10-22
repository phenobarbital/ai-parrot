# TASK-4043: Managed command assets and standup operator documentation

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4041, TASK-4042
**Assigned-to**: unassigned

---

## Context

Implement M7 docs/AC17 and managed asset parity. Update Claude SLASH_COMMAND_MD argument-hint and bullets plus checked-in parrotwiki.md in the same task. Add one sentence about standup/entity in Codex/Gemini wiki skill assets. Add cheatsheet and guide sections at verified anchors and a runbook. Document cron at 07:00 after the 06:17 Jira sweep, personal identity/aliases without email, --team, language, output flags, read-only MCP defaults, backend fallback limitations and entity reindex --store for issues. Explain that discarded vault metadata requires a fresh source ingest, whereas preserved Markdown bodies can be back-filled. Do not create a cron entry or execute external writes; document only.

---

## Scope

Implement M7 docs/AC17 and managed asset parity. Update Claude SLASH_COMMAND_MD argument-hint and bullets plus checked-in parrotwiki.md in the same task. Add one sentence about standup/entity in Codex/Gemini wiki skill assets. Add cheatsheet and guide sections at verified anchors and a runbook. Document cron at 07:00 after the 06:17 Jira sweep, personal identity/aliases without email, --team, language, output flags, read-only MCP defaults, backend fallback limitations and entity reindex --store for issues. Explain that discarded vault metadata requires a fresh source ingest, whereas preserved Markdown bodies can be back-filled. Do not create a cron entry or execute external writes; document only.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | Installers must distribute the same instructions users read in the repository. |
| `.claude/commands/parrotwiki.md` | MODIFY | The command and managed asset are updated atomically in this task. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | Codex-generated skill text must expose the same CLI surface. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` | MODIFY | Gemini-generated skill text must expose the same CLI surface. |
| `docs/wiki/cheatsheet.md` | MODIFY | Keep the existing cheatsheet navigation and quick-command style. |
| `docs/guides/llm-wiki-guide.md` | MODIFY | The guide explains operational behavior, not internal implementation details. |
| `docs/runbooks/wiki-standup.md` | CREATE | The runbook is an operator artifact; fill decisions are bounded by existing public controls. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py` | CREATE | Assert public commands and write defaults across assets/docs without overfitting wording. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
```

### Existing Signatures to Use

No existing implementation symbol is required beyond the explicitly listed dependency contracts and installed libraries.

### Does NOT Exist

- `docs/runbooks/wiki-standup.md` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/parrotwiki.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/wiki/cheatsheet.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/guides/llm-wiki-guide.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/runbooks/wiki-standup.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

TASK-4041: consumes final CLI flags/help; TASK-4042: consumes wiki_standup write semantics

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)

Anchor `argument-hint:` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:309`.

Anchor `- `audit` — run `wikitoolkit audit` and summarise recent writes.` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:340`.

```python
# Extend SLASH_COMMAND_MD argument-hint with standup and entity.
# Insert after the audit bullet in that same string:
# - `standup` — run `wikitoolkit standup`; use --period day|week|month and --language en|es.
# - `entity` — run `wikitoolkit entity add|list|reindex`; reindex foreign planes with --store.
# FILL IN: explain MCP writes are opt-in and mirror checked-in command text; AC14/17.
```

**Why**: Installers must distribute the same instructions users read in the repository.

---

### `.claude/commands/parrotwiki.md` (MODIFY)

Anchor `- `audit` — run `wikitoolkit audit` and summarise recent writes.` — occurrences: 1 (verified: `grep -F -c`), `.claude/commands/parrotwiki.md:34`.

```markdown
Add standup and entity to the argument hint and insert the exact same bullets
as the managed SLASH_COMMAND_MD asset. Document optional periods/language and
local-only explicit MCP writes. Preserve the rest of the command.
```

**Why**: The command and managed asset are updated atomically in this task.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)

Anchor `SKILL = """---` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py:34`.

```python
# In the SKILL string add:
# Use `wikitoolkit standup` for day/week/month briefs and `wikitoolkit entity`
# for typed authoring, listing and local-plane back-fill.
```

**Why**: Codex-generated skill text must expose the same CLI surface.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` (MODIFY)

Anchor `SKILL = """---` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:40`.

```python
# In the SKILL string add:
# Use `wikitoolkit standup` for day/week/month briefs and `wikitoolkit entity`
# for typed authoring, listing and local-plane back-fill.
```

**Why**: Gemini-generated skill text must expose the same CLI surface.

---

### `docs/wiki/cheatsheet.md` (MODIFY)

Anchor `## 12. Exportar el wiki como markdown` — occurrences: 1 (verified: `grep -F -c`), `docs/wiki/cheatsheet.md:489`.

```markdown
Insert a concise standup/entity section immediately before section 12.
Include day/week/month, --language es, --no-llm, --out, and entity reindex
against an explicit --store. Link the operator runbook and retain numbering.
```

**Why**: Keep the existing cheatsheet navigation and quick-command style.

---

### `docs/guides/llm-wiki-guide.md` (MODIFY)

Anchor `## Obsidian Vaults as Wiki Sources` — occurrences: 1 (verified: `grep -F -c`), `docs/guides/llm-wiki-guide.md:921`.

```markdown
Insert a Standup briefs and typed entities section before Obsidian sources.
Explain attrs ingest/back-fill, personal/team filtering, model fallback,
period roll-ups, delta meaning and read-only MCP defaults. Link the runbook.
```

**Why**: The guide explains operational behavior, not internal implementation details.

---

### `docs/runbooks/wiki-standup.md` (CREATE)

```markdown
# Wiki standup briefs

## Generate a brief
`wikitoolkit standup --no-llm`
`wikitoolkit standup --period week --language es`
`wikitoolkit standup --period month --team --no-store --no-file --json`

## Back-fill an existing issues plane
`wikitoolkit entity reindex --store "${PARROT_HOME}/wikis/issues/.parrot/wiki" --dry-run`
`wikitoolkit entity reindex --store "${PARROT_HOME}/wikis/issues/.parrot/wiki"`

## Schedule
Run at 07:00 after the 06:17 Jira sweep, with explicit working directory,
virtualenv executable and PARROT_HOME. This document does not install cron.

## Identity, storage and recovery
FILL IN: document config/cache identity without email, aliases, --team,
output flags, vault markers, attrs fallback limitations, delta interpretation,
optional model failure and MCP opt-in persistence; bounded by AC7-17.
FILL IN: give a concrete cron template whose deployment-specific paths are
clearly marked, and explain logs/failure recovery without exposing credentials.
```

**Why**: The runbook is an operator artifact; fill decisions are bounded by existing public controls.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest


def test_managed_command_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify managed command parity."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_docs_show_actual_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify docs show actual controls."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Assert public commands and write defaults across assets/docs without overfitting wording.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `.claude/commands/parrotwiki.md` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `docs/wiki/cheatsheet.md` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `docs/guides/llm-wiki-guide.md` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `docs/runbooks/wiki-standup.md` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Managed and checked-in Claude commands list identical standup/entity syntax.
- [ ] Docs cover period/identity/language/output/MCP controls, cron and back-fill recipe.
- [ ] All usage examples match actual CLI options; asset regression checks pass.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_assets.py -q`

---

## Test Specification

- Managed and checked-in Claude commands list identical standup/entity syntax.
- Docs cover period/identity/language/output/MCP controls, cron and back-fill recipe.
- All usage examples match actual CLI options; asset regression checks pass.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4043`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
