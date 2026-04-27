# TASK-877: SDD subagent definition files (`sdd-research`, `sdd-qa`)

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 13**. The dev-loop dispatcher binds one of three
subagents per dispatch: `sdd-research`, `sdd-worker`, `sdd-qa`. The
worker definition already exists at `.claude/agents/sdd-worker.md`. The
research and QA definitions do NOT, and this task creates them.

Subagent definitions are dual-sourced (spec §7 Patterns):

1. **Filesystem** — `.claude/agents/sdd-*.md` loaded by Claude Code via
   `setting_sources=["project"]`.
2. **Programmatic** — the same definitions are also passed inline as
   `ClaudeAgentOptions.agents={...}` in TASK-878 so dispatches do not
   depend on the worktree containing fresh `.claude/agents/` content.

This task owns the filesystem files. TASK-878 (dispatcher) imports the
prompt content into the programmatic `agents` dict.

---

## Scope

- Read `.claude/agents/sdd-worker.md` to learn the existing
  frontmatter + body shape.
- Create `.claude/agents/sdd-research.md` describing the research-phase
  subagent: log triage, Jira ticket creation, `/sdd-spec` + `/sdd-task`
  invocation, worktree creation. Output contract: a JSON object matching
  `ResearchOutput` (TASK-874).
- Create `.claude/agents/sdd-qa.md` describing the QA-phase subagent:
  run each `AcceptanceCriterion` deterministically (subprocess + exit
  code), run lint, return a `QAReport` JSON object. Constrained to
  `permission_mode="plan"` and `Read` + `Bash` tools only — NO edits.
- Both files MUST follow the existing frontmatter convention used by
  `sdd-worker.md`.
- Provide a small Python helper to load each file's body into a string,
  to be used by TASK-878:
  `parrot/flows/dev_loop/_subagent_defs.py` exposing
  `load_subagent_definition(name: str) -> str` which reads from a
  package-shipped copy (NOT from `.claude/agents/` at runtime, since
  the package may be installed outside the repo).

**NOT in scope**:
- Modifying `.claude/agents/sdd-worker.md`.
- The dispatcher's wiring of these into `ClaudeAgentOptions.agents=...`
  (that's TASK-878).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-research.md` | CREATE | Research-phase subagent definition (committed in repo). |
| `.claude/agents/sdd-qa.md` | CREATE | QA-phase subagent definition (committed in repo). |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | CREATE | Loader returning the prompt body for each subagent name. Bundles a copy at package install time. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | CREATE | Package-shipped copy of the research subagent body. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | CREATE | Package-shipped copy of the worker subagent body (mirror `.claude/agents/sdd-worker.md`). |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md` | CREATE | Package-shipped copy of the QA subagent body. |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py` | CREATE | Unit test for the loader. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In _subagent_defs.py
from importlib.resources import files     # stdlib >=3.9
```

### Existing Signatures to Use

```python
# .claude/agents/sdd-worker.md (existing) — read first to learn the
# frontmatter convention. The file ships with a YAML header followed by
# a markdown body that becomes the subagent's system prompt.
```

### Does NOT Exist

- ~~`claude_agent_sdk.AgentDefinition.from_markdown(...)`~~ — the SDK
  takes a plain `system_prompt` string. The conversion from `.md` to
  `AgentDefinition` happens in TASK-878.
- ~~`parrot.flows.dev_loop.subagents` (no underscore prefix)~~ — the
  helper module is `_subagent_defs.py` (underscore, private) because
  it is an internal loader, not a public API.
- ~~Reading `.claude/agents/*.md` at runtime~~ — when ai-parrot is
  installed via `pip` outside the repo, that path does not exist. Always
  read from the package-shipped copy via `importlib.resources`.

---

## Implementation Notes

### Subagent contracts

`sdd-research.md` body (high-level):

- Mission: given a `BugBrief` JSON and log excerpts, produce a Jira
  ticket, scaffold a `/sdd-spec` and run `/sdd-task` to generate the
  worktree at `.claude/worktrees/feat-<id>-<slug>/`.
- Tools: `Read`, `Grep`, `Glob`, `Bash(git:*, gh:*, /sdd-spec, /sdd-task)`.
  No `Edit`, no `Write` outside `sdd/`.
- Output: ONE JSON object on the final assistant turn matching
  `ResearchOutput`:
  ```json
  {"jira_issue_key": "OPS-...", "spec_path": "sdd/specs/...",
   "feat_id": "FEAT-...", "branch_name": "feat-...",
   "worktree_path": "/abs/.claude/worktrees/...", "log_excerpts": [...]}
  ```

`sdd-qa.md` body (high-level):

- Mission: given a list of `AcceptanceCriterion` and a worktree path,
  run each deterministically (subprocess + exit code), then run lint
  (`ruff check . && mypy --no-incremental`), and emit a `QAReport`.
- Tools: `Read`, `Bash(flowtask:*, pytest:*, ruff:*, mypy:*, pylint:*)`.
  Permission mode: `plan` (NO edits).
- Output: ONE JSON object on the final assistant turn matching
  `QAReport` (TASK-874):
  ```json
  {"passed": <bool>, "criterion_results": [...], "lint_passed": <bool>,
   "lint_output": "...", "notes": "..."}
  ```

### `_subagent_defs.py` API

```python
def load_subagent_definition(name: str) -> str:
    """Return the system-prompt body of an SDD subagent.

    Args:
        name: one of "sdd-research", "sdd-worker", "sdd-qa".

    Reads from the package-bundled `_subagent_data/<name>.md`. Strips the
    YAML frontmatter so the returned string is suitable as a plain
    `system_prompt`.
    """
```

### Package data — make sure files are shipped

Add `*.md` to the package data block in
`packages/ai-parrot/pyproject.toml` (`tool.setuptools.package-data` or
the equivalent for the build backend in use). Verify by running:

```bash
python -m build --wheel
unzip -l dist/ai_parrot-*.whl | grep _subagent_data
```

### Key Constraints

- Frontmatter on `.claude/agents/*.md` must match `sdd-worker.md` style.
- Body language is concise, imperative, JSON-output-explicit. Stay under
  ~150 lines per file.
- `_subagent_defs.load_subagent_definition` MUST raise `ValueError` for
  unknown names (do NOT default-fallback).

---

## Acceptance Criteria

- [ ] `.claude/agents/sdd-research.md` and `.claude/agents/sdd-qa.md`
  exist and follow the existing frontmatter convention.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/`
  contains shipped copies of all THREE subagent definitions
  (`sdd-research.md`, `sdd-worker.md`, `sdd-qa.md`).
- [ ] `parrot.flows.dev_loop._subagent_defs.load_subagent_definition(
  "sdd-research")` returns a non-empty string with the YAML frontmatter
  stripped.
- [ ] Unknown name raises `ValueError`.
- [ ] Package wheel includes the `.md` files.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py
import pytest

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition


@pytest.mark.parametrize("name", ["sdd-research", "sdd-worker", "sdd-qa"])
def test_load_returns_nonempty_string(name):
    body = load_subagent_definition(name)
    assert isinstance(body, str)
    assert len(body) > 100
    # frontmatter stripped
    assert not body.startswith("---")


def test_load_unknown_name_raises():
    with pytest.raises(ValueError):
        load_subagent_definition("sdd-whoknows")
```

---

## Agent Instructions

1. Read `.claude/agents/sdd-worker.md` to copy the frontmatter shape.
2. Create the two new agent definitions; copy `sdd-worker.md` body
   into the package data dir as well.
3. Implement `_subagent_defs.py`. Update `pyproject.toml` package-data.
4. Run tests, then move task to completed.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
