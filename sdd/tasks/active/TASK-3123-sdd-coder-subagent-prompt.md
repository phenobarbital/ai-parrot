# TASK-3123: `sdd-coder` sub-agent prompt (repo + packaged twin) and `"sdd-coder"` registrations

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Every seat runs the same task-scoped, code-only prompt: MCP
dispatchers load it with `load_subagent_definition("sdd-coder")` from the packaged
`_subagent_data/` copy; Claude Code loads the repo twin natively for the Haiku seat
(`model: haiku`). The prompt is `sdd-worker.md`'s Cardinal Rules + Task-Scoped Mode +
steps a–f, minus everything about SDD state (spec G7: coders never touch `sdd/`), plus
the `DevelopmentOutput` JSON contract (brainstorm Q2). Byte-parity between the two copies
is enforced by `test_subagent_parity.py` (auto-discovers `_subagent_data/*.md`). The
name must also be accepted by `_VALID_NAMES` and by every dispatch profile's `subagent`
Literal.

---

## Scope

- Write `.claude/agents/sdd-coder.md` (frontmatter `model: haiku`, tools without `Agent`) and copy it byte-for-byte to `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md`.
- Add `"sdd-coder"` to `_VALID_NAMES` and to the `subagent` Literals in `models/llm.py`, `models/gemini.py`, `models/codex.py` (line 18 only), `models/claude.py` (lines 18-27 block), `models/google_coding.py`.
- Tests: `load_subagent_definition("sdd-coder")` body contract; each profile accepts `subagent="sdd-coder"`; parity passes.

**NOT in scope**: `sdd-worker.md` (TASK-3124); the `codex.py:48` / `claude.py:106` Literals (other profiles — leave untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-coder.md` | CREATE | repo twin (Claude Code loads it; `model: haiku`) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | CREATE | packaged twin — `cp` of the repo file |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | `_VALID_NAMES += "sdd-coder"` + docstring line |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py` | MODIFY | Literal (:18) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/gemini.py` | MODIFY | Literal (:22) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py` | MODIFY | Literal (:18) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py` | MODIFY | Literal block (:18-27) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py` | MODIFY | Literal (:21) |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py` | MODIFY | add `sdd-coder` contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition     # verified: _subagent_defs.py:86 — reads ONLY _subagent_data/<name>.md, strips frontmatter
from parrot.flows.dev_loop.models import (LLMCodeDispatchProfile, GeminiCodeDispatchProfile, CodexCodeDispatchProfile,
                                          ClaudeCodeDispatchProfile, GoogleCodingDispatchProfile)   # verified: models/__init__.py exports
```

### Existing Signatures / anchors (each occurs exactly once in its file — verified by grep -c)
```python
# _subagent_defs.py:49-57
_VALID_NAMES: frozenset[str] = frozenset({ "sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview", "sdd-secondopinion", "sdd-planner", "sdd-feedback", })
#   anchor line :56  `        "sdd-feedback",`   (8 spaces)
# models/llm.py:18        `    subagent: Literal["sdd-worker"] = "sdd-worker"`
# models/gemini.py:22     `    subagent: Literal["sdd-worker"] = "sdd-worker"`
# models/codex.py:18      `    subagent: Literal["sdd-worker", "sdd-secondopinion"] = "sdd-worker"`   (NOT :48 `Literal["sdd-worker"]` of another profile, NOT :64)
# models/claude.py:18-27  `    subagent: Optional[Literal[ "sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview", "sdd-planner", "sdd-feedback", ]] = "sdd-worker"` — anchor :25 `            "sdd-feedback",` (12 spaces)   (NOT :106, a different profile)
# models/google_coding.py:21  `    subagent: Literal["sdd-worker", "sdd-secondopinion", "sdd-research", "sdd-qa", "sdd-planner", "sdd-feedback"] = "sdd-worker"`
# .claude/agents/sdd-worker.md — source text to copy: "## ⛔ CARDINAL RULES" (:37-67), "## Task-Scoped Mode (FEAT-323)" (:77-106), steps a)–f) (:211-282), "## Structured Output Contract (dispatched runs)" (:373-402), "## STOP Conditions" (:404-414)
# .claude/agents/sdd-ideation.md:44 — precedent for a `tools:` line; every agent today uses `model: sonnet` (product-analyst: opus); sdd-coder is the first `model: haiku`
# tests/flows/dev_loop/test_subagent_parity.py:38-44 — parametrised over _subagent_data/*.md; requires .claude/agents/<name>.md unless in _NO_REPO_TWIN
# tests/flows/dev_loop/test_subagent_defs.py:11-31 — existing shape (`test_load_returns_nonempty_string(name)`, `test_load_*_mentions_*`)
```

### Does NOT Exist
- ~~`.claude/agents/sdd-coder.md`~~, ~~`_subagent_data/sdd-coder.md`~~ — created here.
- ~~`"sdd-coder"` in any Literal or `_VALID_NAMES`~~ — added here.
- ~~a Delegation Contract / `writer_generate` step in the coder prompt~~ — FEAT-549 replaces that route (spec C3); do not copy `sdd-worker.md` step b2.
- ~~any `sdd/` write in the coder prompt~~ — forbidden by spec G7 / AC-7; the fidelity gate rejects it anyway.
- ~~`Agent` in the coder's `tools:`~~ — a coder never spawns sub-agents.

---

## Implementation Notes

### Key Constraints
- Frontmatter: `name: sdd-coder`, `description:` (one paragraph + two `Context/user/assistant` examples like other agents), `model: haiku`, `color: green`, `permissionMode: bypassPermissions`, `tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep`.
- Body sections in this order: Cardinal Rules (verbatim from sdd-worker) · Input (`task_file`, `cwd` = your sub-worktree, feature branch; the brief may be a `TaskScopedBrief` JSON when dispatched) · Steps a) read task b) verify Codebase Contract c) implement (start from the Implementation Blueprint, complete every FILL IN) d) verification checklist e) run THIS task's acceptance tests f) commit `feat(<feature-slug>): TASK-<NNN> — <title>` with ONLY the listed files · Forbidden (editing anything under `sdd/`, marking tasks, touching other tasks, `git push`, creating branches/worktrees) · Output: final message = single `DevelopmentOutput` JSON, `files_changed` derived from git · STOP conditions.
- After writing: `cp .claude/agents/sdd-coder.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` and `cmp` them.
- `.claude/` is git-ignored as a directory but its files are tracked: stage with `git add -f .claude/agents/sdd-coder.md`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the repo prompt — *why*: it is the behaviour contract every seat executes; the fidelity gate (TASK-3119) enforces what the prompt forbids.
2. `cp` to `_subagent_data/` — *why*: dispatchers read only the packaged copy (`_subagent_defs.py:86`), parity test guards drift (FEAT-547).
3. Literal + `_VALID_NAMES` edits — *why*: `load_subagent_definition` raises on unknown names (:105) and profiles validate `subagent`.
4. Tests; `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py test_subagent_defs.py -v`.

### `.claude/agents/sdd-coder.md` (CREATE — structure; prose is FILL IN from sdd-worker.md)
```markdown
---
name: sdd-coder
description: |
  Task-scoped SDD coder (FEAT-549). Implements exactly ONE task in the sub-worktree it is given, commits code only,
  never touches sdd/ or other tasks, and ends with a DevelopmentOutput JSON. Dispatched by the sdd-worker
  orchestrator (native haiku seat) or by the parrot-sdd-coder MCP server (nova / google-compat / codex seats).

  Examples:
  Context: sdd-worker prepared .claude/worktrees/feat-FEAT-549-x--pool/TASK-3115-a1 for TASK-3115.
  user: "Implement sdd/tasks/active/TASK-3115-sdd-coder-models.md in this worktree."
  assistant: "I read the task, verify its Codebase Contract, write the blueprint files, run its tests, commit only the listed files, and emit the DevelopmentOutput JSON."
model: haiku
color: green
permissionMode: bypassPermissions
tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep
---

# SDD Coder — One Task, One Worktree, Code Only

## ⛔ CARDINAL RULES — NEVER VIOLATE THESE
<!-- FILL IN: copy rules 1–5 verbatim from .claude/agents/sdd-worker.md:37-63; replace rule 6 with:
     6. YOU NEVER TOUCH `sdd/`. The per-spec index, task files and Completion Notes belong to the orchestrator. A branch that edits sdd/ is rejected before merge. -->

## Input
<!-- FILL IN: task_file path; cwd is your sub-worktree (branch <feature>--TASK-NNN-a<n>); the feature branch name; when dispatched by the MCP server
     the brief is a TaskScopedBrief JSON {research, task_id, task_file} — read task_file, never reconstruct it from task_id (sdd-worker.md:96-104 wording) -->

## Steps
### a) Read and Understand Task   <!-- FILL IN: sdd-worker.md:211-217 -->
### b) Verify Codebase Contract   <!-- FILL IN: sdd-worker.md:219-227 -->
### c) Implement — from the Implementation Blueprint   <!-- FILL IN: sdd-worker.md:253-257 + "start from the blueprint blocks, complete every FILL IN, never change a fixed signature" -->
### d) Verification Checklist     <!-- FILL IN: sdd-worker.md:259-269 minus the writer_apply line -->
### e) Validate                    <!-- FILL IN: run THIS task's acceptance tests + ruff; 3 attempts then report — sdd-worker.md:271-274 -->
### f) Commit                      <!-- FILL IN: git add <listed files only>; git commit -m "feat(<feature-slug>): TASK-<NNN> — <title>" — sdd-worker.md:276-281 -->

## Forbidden
- Editing, moving or creating anything under `sdd/` · marking task status · touching files of other tasks · `git push` · creating branches or worktrees · calling other agents.

## Output — DevelopmentOutput JSON (mandatory)
<!-- FILL IN: sdd-worker.md:373-402 (files_changed from `git diff --name-only <feature-branch>...HEAD` + `git status --porcelain`, commit_shas, summary) -->

## STOP Conditions
<!-- FILL IN: sdd-worker.md:404-414 -->
```
**Why this shape**: the prompt is `sdd-worker.md` with the feature-level loop and SDD state removed (spec §3 M6) so parity of wording keeps behaviour predictable across seats; `model: haiku` makes the same file the native Claude Code seat.

### `_subagent_defs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^        "sdd-feedback",$' packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py)
# AFTER — insert below `        "sdd-feedback",` (verified: _subagent_defs.py:56)
        "sdd-coder",
# Also add one docstring bullet (module docstring, after the `sdd-feedback` bullet ~:19-21):
#  * ``sdd-coder`` — task-scoped, code-only coder used by every FEAT-549 seat; dual-sourced (repo twin at .claude/agents/sdd-coder.md).
```

### Literal edits (MODIFY — each anchor occurs once per file)
```python
# models/llm.py:18 and models/gemini.py:22 — REPLACE `    subagent: Literal["sdd-worker"] = "sdd-worker"`
    subagent: Literal["sdd-worker", "sdd-coder"] = "sdd-worker"
# models/codex.py:18 — REPLACE `    subagent: Literal["sdd-worker", "sdd-secondopinion"] = "sdd-worker"`
    subagent: Literal["sdd-worker", "sdd-secondopinion", "sdd-coder"] = "sdd-worker"
# models/claude.py — AFTER `            "sdd-feedback",` (verified :25, 12 spaces) insert
            "sdd-coder",
# models/google_coding.py:21 — REPLACE the Literal adding ", "sdd-coder"" before the closing bracket
```
**Why**: `build_dispatcher` profiles are `model_copy`-updated to `sdd-coder` by the engine (TASK-3121); widening the Literals makes the value constructible and validated everywhere else (dev-loop included).

### FILL IN checklist
- [ ] `sdd-coder.md` prose sections — copied/adapted from `sdd-worker.md` anchors above; bounded by spec §3 M6 section list and G7
- [ ] `test_subagent_defs.py` additions (below)

---

## Acceptance Criteria

- [ ] `cmp .claude/agents/sdd-coder.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` succeeds; `pytest .../test_subagent_parity.py -v` passes for `sdd-coder` and every other prompt (AC-11).
- [ ] `load_subagent_definition("sdd-coder")` returns a body containing `DevelopmentOutput`, `CARDINAL RULES`, and the string `sdd/` inside the Forbidden section; it contains neither `writer_generate` nor `Completion Note`.
- [ ] Repo frontmatter has `model: haiku` and a `tools:` line without `Agent`.
- [ ] `LLMCodeDispatchProfile(subagent="sdd-coder")`, `GeminiCodeDispatchProfile(subagent="sdd-coder")`, `CodexCodeDispatchProfile(subagent="sdd-coder")`, `ClaudeCodeDispatchProfile(subagent="sdd-coder")`, `GoogleCodingDispatchProfile(subagent="sdd-coder")` all validate; defaults stay `"sdd-worker"`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes (AC-16); `ruff`/`mypy` clean.

---

## Test Specification

```python
# additions to packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py
import pytest
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.models import (ClaudeCodeDispatchProfile, CodexCodeDispatchProfile, GeminiCodeDispatchProfile,
                                          GoogleCodingDispatchProfile, LLMCodeDispatchProfile)

def test_valid_names_include_sdd_coder():
    body = load_subagent_definition("sdd-coder")
    assert "DevelopmentOutput" in body and "CARDINAL RULES" in body
    assert "writer_generate" not in body and "Completion Note" not in body

def test_sdd_coder_prompt_forbids_sdd_dir():
    body = load_subagent_definition("sdd-coder")
    forbidden = body.split("## Forbidden", 1)[1].split("## ", 1)[0]
    assert "sdd/" in forbidden

@pytest.mark.parametrize("cls", [LLMCodeDispatchProfile, GeminiCodeDispatchProfile, CodexCodeDispatchProfile, ClaudeCodeDispatchProfile, GoogleCodingDispatchProfile])
def test_subagent_literals_accept_sdd_coder(cls):
    assert cls(subagent="sdd-coder").subagent == "sdd-coder"
    assert cls().subagent == "sdd-worker"

def test_sdd_coder_repo_twin_frontmatter():
    from pathlib import Path
    text = Path(__file__).resolve().parents[4].joinpath(".claude/agents/sdd-coder.md").read_text(encoding="utf-8")  # FILL IN: reuse _repo_agents_dir() from test_subagent_parity.py
    head = text.split("---", 2)[1]
    assert "model: haiku" in head and "Agent" not in head.split("tools:", 1)[1].splitlines()[0]
```

---

## Agent Instructions

1. **Read the spec** §3 Module 6, G7, brainstorm Q2 (DevelopmentOutput contract).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-run each `grep -c` anchor; read `sdd-worker.md:37-106, 207-282, 373-414`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**; remember `git add -f` for the `.claude/agents/` file.
6. **Verify** all acceptance criteria including the full `tests/flows/dev_loop` run.
7. **Move this file** to `sdd/tasks/completed/TASK-3123-sdd-coder-subagent-prompt.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
