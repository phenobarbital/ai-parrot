---
type: Wiki Overview
title: 'TASK-005: `sdd-codereview` subagent definition + allowlist'
id: doc:sdd-tasks-completed-task-005-sdd-codereview-subagent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 5 (G4). Adds a read-only code-review subagent that the
  QA node
relates_to:
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop._subagent_defs
  rel: mentions
---

# TASK-005: `sdd-codereview` subagent definition + allowlist

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-003
**Assigned-to**: unassigned

---

## Context

Implements Module 5 (G4). Adds a read-only code-review subagent that the QA node
(TASK-008) dispatches. Its system prompt is adapted from
`.claude/agents/code-reviewer.md` and the AC-comparison logic of
`parrot/bots/github_reviewer.py`. It must emit a single JSON object so the
dispatcher can validate it (best-effort last-JSON-object parse).

---

## Scope

- Create `_subagent_data/sdd-codereview.md` (Markdown body, optional YAML
  frontmatter that `_strip_frontmatter` removes). The prompt instructs the agent
  to: read the diff/worktree, compare against the Jira acceptance criteria and
  the project's standards, and output exactly one JSON object
  `{"passed": bool, "findings": [str], "summary": str}`. Read-only — no edits.
- Add `"sdd-codereview"` to `_VALID_NAMES` in `_subagent_defs.py`.
- Unit test: `load_subagent_definition("sdd-codereview")` returns a non-empty
  body with the frontmatter stripped.

**NOT in scope**: the QA dispatch wiring (TASK-008); the `ClaudeCodeDispatchProfile`
Literal change (done in TASK-003).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` | CREATE | Subagent system prompt |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | `_VALID_NAMES += "sdd-codereview"` |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_codereview.py` | CREATE | Loader test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition  # _subagent_defs.py:60
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
_VALID_NAMES = {"sdd-research", "sdd-worker", "sdd-qa"}   # :30  ← add "sdd-codereview"
def load_subagent_definition(name: str) -> str:           # :60
    # reads files("parrot.flows.dev_loop") / "_subagent_data" / f"{name}.md"
    # then _strip_frontmatter(...)
```

### Does NOT Exist
- ~~a `sdd-codereview` entry~~ — only `sdd-research`/`sdd-worker`/`sdd-qa` exist today.
- ~~`.claude/commands/code-reviewer.md`~~ — the template lives at `.claude/agents/code-reviewer.md`.

### Template / Reference (read, do not import)
- `.claude/agents/code-reviewer.md` — review structure, severity levels, AI-Parrot checklist.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py` — PR-diff vs Jira AC comparison + structured verdict.
- Existing examples: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md` (style/format to mirror).

---

## Implementation Notes

### Key Constraints
- The packaged `.md` MUST ship with the wheel — `_subagent_data/` is already
  package-data (other `.md` files load fine), so the new file inherits it.
  Verify it is picked up by `load_subagent_definition`.
- The prompt must demand a SINGLE trailing JSON object (the dispatcher extracts
  the last balanced JSON object from assistant text).
- Read-only posture in the prompt (no Edit/Write) — enforced again by the QA
  profile in TASK-008.

### References in Codebase
- `_subagent_data/sdd-qa.md` — closest sibling (read-only verifier, JSON output).

---

## Acceptance Criteria

- [ ] `load_subagent_definition("sdd-codereview")` returns a non-empty, frontmatter-stripped body.
- [ ] `"sdd-codereview" in _VALID_NAMES`.
- [ ] The body instructs a single-JSON-object output `{passed, findings, summary}`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_codereview.py -v` passes.

---

## Test Specification
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition, _VALID_NAMES

def test_codereview_subagent_loads():
    assert "sdd-codereview" in _VALID_NAMES
    body = load_subagent_definition("sdd-codereview")
    assert body and "---" not in body.splitlines()[0]
```

---

## Agent Instructions
Standard SDD lifecycle.

## Completion Note

**Status**: done — 2026-06-20

**What changed**
- Created `_subagent_data/sdd-codereview.md` — read-only code-review system
  prompt with YAML frontmatter (`permissionMode: plan`, tools `Read, Bash,
  Grep, Glob`), an AC-first review posture, an AI-Parrot standards checklist
  (adapted from `.claude/agents/code-reviewer.md` + `github_reviewer.py`), and a
  single-JSON-object Output Contract `{passed, findings, summary}`.
- `_subagent_defs.py`: added `"sdd-codereview"` to `_VALID_NAMES`; updated the
  module + function docstrings to enumerate the new subagent.

**Scope note**: per file-fidelity, only the package-data `.md` and
`_subagent_defs.py` were touched (not a repo-level `.claude/agents/*` twin,
which is not in the task list).

**Verification**
- `pytest test_subagent_codereview.py` → 5 passed (in `_VALID_NAMES`, loads +
  frontmatter stripped, JSON contract keys present, read-only posture, unknown
  name still rejected). `load_subagent_definition` reads it via
  `importlib.resources`, confirming package-data pickup.
- `ruff check` clean on both files.
