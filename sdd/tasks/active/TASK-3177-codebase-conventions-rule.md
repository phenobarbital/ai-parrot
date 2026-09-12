# TASK-3177: Write `codebase-conventions.md` and the two-mode Python rule

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (content half). External `sdd-coder` seats today receive one
convention line; this task writes the canonical, tool-neutral rule file under
`.agent/rules/` plus its `.claude/rules/` twin, and fixes the one existing rule
that is unexecutable for a shell-free seat (spec §10 R2: `source
.venv/bin/activate` cannot run in the in-process loop and task worktrees have
no `.venv`). Pure Markdown — no Python is touched here; TASK-3178 packages
these files.

---

## Scope

- Create `.agent/rules/codebase-conventions.md` with the five sections fixed
  by spec §3 M1 (Stack, Forbidden table, Repository layout, Tooling in two
  modes, Code standards).
- Create the byte-identical twin `.claude/rules/codebase-conventions.md`.
- Edit CRITICAL RULE 2 of `.agent/rules/python-development.md` AND
  `.claude/rules/python-development.md` (identical edit) to add the
  tool-driven-coder clause.
- Keep the two coder rule files (`codebase-conventions` + `python-development`)
  under 8 000 bytes combined (AC-3).

**NOT in scope**: `parrot/flows/conventions.py`, `_rules_data/`, package-data,
parity tests (TASK-3178); `cython-development.md` / `rust-development.md`
(untouched by FEAT-553, spec §8 Q5); banning `black` (it is the active
formatter — spec §10 R3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agent/rules/codebase-conventions.md` | CREATE | canonical conventions rule |
| `.claude/rules/codebase-conventions.md` | CREATE | byte-identical twin (Claude Code auto-loads `.claude/rules/*.md`) |
| `.agent/rules/python-development.md` | MODIFY | CRITICAL RULE 2 gains the no-shell clause |
| `.claude/rules/python-development.md` | MODIFY | same edit, byte-identical to `.agent/` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```text
# .agent/rules/python-development.md  (2 402 bytes; byte-identical to .claude/rules/python-development.md, verified 2026-09-12)
line 1-3   frontmatter: ---\ntrigger: always_on\n---
line 9     2. **Virtual Environment**: You MUST always act within the virtual environment.
line 10       - **CRITICAL**: NEVER run `uv`, `python`, or `pip` commands without first activating the environment.
line 11       - **ALWAYS** run `source .venv/bin/activate` before any python-related command.
line 52    - Use aiohttp for serving models

# Facts the rule text must state (all verified 2026-09-12):
#   Makefile:399 `uv run black …` (format), :404 `uv run black --check …` (lint) → black IS the formatter
#   ruff.toml:101 select = ["E4","E7","E9","F"]; line-length 120 → ruff IS the linter
#   pyproject.toml has [tool.black] (:237) and NO [tool.isort]; no isort/prettier step anywhere
#   dispatchers/llm.py:1713 `_tool_run_command` execs a bare argv (no shell) against `allowed_commands`
#   models/llm.py:53 allowed_commands includes git, uv, pytest, python, python3, rg, grep, ls, pwd, cat, sed, find, head, tail, wc, awk, jq, mkdir, mv, ruff, mypy
#   worktree_manager.py:146 `create()` makes a bare git worktree — no .venv
#   CLAUDE.md "Repository layout": uv workspace, no root parrot/, core root packages/ai-parrot/src/parrot/
```

### Does NOT Exist
- ~~`.agent/rules/codebase-conventions.md`~~ — created by this task.
- ~~an ASGI stack (starlette/fastapi/uvicorn) anywhere in production code~~ — only `codex_tool_bridge.py` imports starlette/uvicorn (grandfathered); the server is aiohttp + gunicorn.
- ~~`[tool.isort]`, an isort or prettier step~~ — none exists; do not describe one.
- ~~a `.venv` inside a task worktree~~ — never; the rule must say so.

---

## Implementation Notes

### Key Constraints
- The file is injected into a 40-turn LLM prompt: terse, imperative, no prose paragraphs longer than two lines.
- `black` is NEVER listed as forbidden. The stale tools are `isort` and `prettier` only.
- Both copies of both files must be byte-identical (`diff -q` must print nothing) — TASK-3178's parity test will enforce it.
- Size: `wc -c .agent/rules/codebase-conventions.md .agent/rules/python-development.md` total < 8000.

### References in Codebase
- `.agent/rules/python-development.md` — the frontmatter shape (`trigger: always_on`) to reuse.
- `CLAUDE.md` §"Repository layout" and `.agent/CONTEXT.md` §"What NOT to Do" — source of the facts; condense, do not copy.

---

## Implementation Blueprint

### Steps (in order)
1. Write `.agent/rules/codebase-conventions.md` from the CREATE block — *why*: it is the single source; the twin is a copy of it.
2. `cp .agent/rules/codebase-conventions.md .claude/rules/codebase-conventions.md` — *why*: Claude Code reads only `.claude/rules/`, and byte parity is a test.
3. Apply the MODIFY block to `.agent/rules/python-development.md`, then `cp` it over `.claude/rules/python-development.md` — *why*: same parity rule.
4. Run `wc -c` on the two `.agent/rules/` coder files and `diff -q` on each pair — *why*: AC-3 and AC-2 are checked mechanically.

### `.agent/rules/codebase-conventions.md` (CREATE)
```markdown
---
trigger: always_on
---

# AI-Parrot codebase conventions

Binding for every file you touch in this repository. If a task file and this
document disagree, STOP and report — never pick one silently.

## Stack
- HTTP: **aiohttp** + **navigator-api**, served by **gunicorn** (aiohttp worker). There is no ASGI stack.
- Async-first: I/O paths are `async def`; never block the event loop (no `time.sleep`, no sync HTTP or DB drivers in async code).
- LLM calls go through `AbstractClient` (`parrot/clients/base.py`); never call a provider SDK directly. Do not modify `clients/base.py` unless a task says so.
- Data structures are **Pydantic v2** models. Logging is `self.logger` (`logging.getLogger(__name__)`), never `print`.
- Tools: `@tool` for functions, `AbstractToolkit` for collections; every tool has a docstring (it is the LLM-facing description).

## Forbidden — and what to use instead
| Never import / use | Use instead |
|---|---|
| `requests`, `httpx` | `aiohttp` (see `parrot/interfaces/http.py`) |
| `starlette`, `fastapi`, `uvicorn` | aiohttp handlers under `parrot/handlers/`, served by gunicorn |
| `langchain`, `langchain_core`, `langchain_community`, `langgraph`, `langsmith` | parrot primitives: `AbstractClient`, `AbstractTool`, `AgentsFlow`, `AgentCrew` |
| `print(...)` | `self.logger.<level>(...)` |
| `pip`, `poetry`, `requirements.txt` | `uv add` / `uv pip`, dependencies in `pyproject.toml` |
| `isort`, `prettier` | nothing — no import-sorting step exists; `black` formats, `ruff` lints |

`ruff check` enforces the import bans (rule TID251); a banned import fails the task at the merge gate.

## Repository layout
- uv **workspace**: every distribution lives under `packages/<dist>/src/`. There is **no** `parrot/` directory at the repo root.
- Core source root: `packages/ai-parrot/src/parrot/`. Satellite packages merge into the same `parrot.*` namespace (PEP 420).
- Concrete tools live in `packages/ai-parrot-tools/src/parrot_tools/` (`import parrot_tools.<x>`); only base machinery stays in `parrot/tools/`.
- Tests live next to their distribution: `packages/<dist>/tests/`.

## Tooling — pick the mode that matches how you run
- **Interactive shell** (humans, Claude Code, codex, agy): `source .venv/bin/activate` first; then `uv add` / `uv pip`, `pytest`, `ruff check`, `black`.
- **Tool-driven coder without a shell** (dev-loop in-process seats): there is no shell — never try `source`, `cd`, pipes or `>`. Call the allowlisted binaries directly (`pytest`, `ruff`, `python`, `uv`); the host resolves them on its `PATH`. Do not create or look for a `.venv` inside your worktree — it is a bare git worktree.
- Common: `black` (line-length 120) formats; `ruff check` is the lint gate; tests use `pytest` + `pytest-asyncio`; run your task's tests before committing.

## Code standards
- Google-style docstrings and strict type hints on every function and class.
- `snake_case` functions/variables, `PascalCase` classes, 120-column lines.
- Secrets come only from environment variables — never in code or committed files.
- Complete, working files: no `TODO`, no stubs, no "existing code here" placeholders.
- Minimal, focused diffs: touch only the files your task lists; never refactor outside scope.
```
**Why this shape**: each section is one of the five the spec fixes (§3 M1 items 1-5); the Forbidden table is the human-readable twin of the ruff TID251 table TASK-3182 adds, so the two must name the same modules; the Tooling section carries both modes because spec §10 R2 showed the old single-mode instruction was unexecutable for in-process seats. Do not add sections, and do not add `black` to the Forbidden table.

### `.agent/rules/python-development.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'ALWAYS\*\* run `source .venv/bin/activate`' .agent/rules/python-development.md)
# REPLACE lines 10-11 — the two bullets under "2. **Virtual Environment**" (verified: .agent/rules/python-development.md:9-11) — with:
   - **Interactive shell**: NEVER run `uv`, `python`, or `pip` without first activating it — run `source .venv/bin/activate` before any python-related command.
   - **Tool-driven coder with no shell** (the dev-loop in-process seats): you cannot `source`; run the allowlisted `pytest` / `ruff` / `python` / `uv` binaries directly — the host resolves them on its `PATH` — and never provision a `.venv` in your worktree.
```
**Why**: keeps the interactive rule verbatim in spirit and adds the only sentence spec §3 M1 asks for, so the rule and `codebase-conventions.md` agree.

### FILL IN checklist
- [ ] none — the content above is the deliverable; verify sizes and parity mechanically (Steps 4).

---

## Acceptance Criteria

- [ ] `.agent/rules/codebase-conventions.md` exists with exactly the five `##` sections above and names `requests`, `httpx`, `starlette`, `fastapi`, `uvicorn`, `langchain*`, `langgraph`, `langsmith`, `print`, `pip`, `isort` as forbidden with substitutes (spec AC-1)
- [ ] The file names `black` as the formatter and `ruff` as the linter; `black` is not in the Forbidden table
- [ ] `diff -q .agent/rules/codebase-conventions.md .claude/rules/codebase-conventions.md` prints nothing; same for `python-development.md` (spec AC-2)
- [ ] `python-development.md` CRITICAL RULE 2 has both bullets (interactive / no-shell) and no longer says activation is unconditional (spec AC-1b)
- [ ] `cat .agent/rules/codebase-conventions.md .agent/rules/python-development.md | wc -c` < 8000 (spec AC-3)
- [ ] `cython-development.md` and `rust-development.md` are untouched (`git status` shows no change to them)

---

## Test Specification

```bash
# Mechanical checks — no pytest in this task (TASK-3178 adds the parity tests)
diff -q .agent/rules/codebase-conventions.md .claude/rules/codebase-conventions.md
diff -q .agent/rules/python-development.md .claude/rules/python-development.md
cat .agent/rules/codebase-conventions.md .agent/rules/python-development.md | wc -c   # < 8000
grep -c '^## ' .agent/rules/codebase-conventions.md                                    # 5
grep -n 'black' .agent/rules/codebase-conventions.md                                  # only as formatter, never in the "Never import / use" column
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§3 M1, §10 R2/R3)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `python-development.md:9-11` still reads as quoted; if not, adapt the MODIFY anchor and say so in the Completion Note
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the Implementation Blueprint; never add sections or ban `black`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3177-codebase-conventions-rule.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none
