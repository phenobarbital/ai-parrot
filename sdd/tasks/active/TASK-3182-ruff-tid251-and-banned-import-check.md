# TASK-3182: ruff TID251 banned-api config + `check_banned_imports()`

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (deterministic half). Prompts are advisory; the guarantee
that no `requests`/`starlette`/`langchain*` lands in the repo is a lint rule
every seat and every human runs: ruff `flake8-tidy-imports` banned-api
(TID251). Existing usages are grandfathered by file so the tree stays at zero
findings (the reviewer verified this exact configuration yields zero — spec
§10). `check_banned_imports()` wraps that rule for the FEAT-549 engine
(wired by TASK-3183).

---

## Scope

- `ruff.toml`: add `TID251` to `select`, the banned-api table (10 modules), the 17-file grandfather list.
- `sdd_coder/fidelity.py`: `async def check_banned_imports(cwd, changed) -> List[str]`.
- Tests in `test_fidelity.py`; tree-wide `ruff check --select TID251 packages/ scripts/` exits 0.

**NOT in scope**: engine wiring, docs, `sdd-worker.md` (TASK-3183); the
conventions prose (TASK-3177); removing any grandfathered usage.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ruff.toml` | MODIFY | `TID251` + banned-api + grandfather ignores |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` | MODIFY | `check_banned_imports()` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py` | MODIFY | new async tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, json                                                   # stdlib
from typing import List                                                # already imported in fidelity.py:5
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files   # verified: fidelity.py:49, :25
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py  (57 lines; imports: re, typing.List, pydantic)
class FidelityReport(BaseModel)                                        # line 15
def parse_task_files(task_md: str) -> List[str]                        # line 25
def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport   # line 49 (last def) — append the new function after it

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py — subprocess idiom to mirror (do NOT import engine from fidelity: circular)
async def _git(*args: str, cwd: str) -> Tuple[int, str, str]:         # lines 69-80: asyncio.create_subprocess_exec(..., stdout=PIPE, stderr=PIPE); returns (rc, out, err) decoded

# ruff.toml (verified 2026-09-12, ruff 0.16.3)
[lint]                                                                 # line 95
select = ["E4", "E7", "E9", "F"]                                       # line 101
[lint.per-file-ignores]                                                # line 103
"examples/**/*.py" = ["F401", "F841", "E402"]                          # line 117 — last entry of that table

# tests/flows/dev_loop/sdd_coder/test_fidelity.py — 2 sync tests; the sdd_coder test package runs `async def test_*` without markers (asyncio auto mode, see test_engine_plan_merge.py)

# Grandfather list (17 files, measured 2026-09-12: 7 `requests`, 10 `httpx`, 1 starlette+uvicorn):
#   packages/ai-parrot/src/parrot/flows/dev_loop/replication.py
#   packages/ai-parrot/src/parrot/interfaces/http.py
#   packages/ai-parrot/src/parrot/interfaces/jira/client.py
#   packages/ai-parrot/src/parrot/interfaces/onedrive.py
#   packages/ai-parrot/src/parrot/interfaces/sharepoint.py
#   packages/ai-parrot/src/parrot/interfaces/soap.py
#   packages/ai-parrot/src/parrot/tools/openapitoolkit.py
#   packages/ai-parrot-tools/src/parrot_tools/bingsearch.py
#   packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
#   packages/ai-parrot-tools/src/parrot_tools/massive/client.py
#   packages/ai-parrot-tools/src/parrot_tools/o365/delta.py
#   packages/ai-parrot-tools/src/parrot_tools/powerbi.py
#   packages/ai-parrot-tools/src/parrot_tools/research/academic.py
#   packages/ai-parrot-tools/src/parrot_tools/research/open_data.py
#   packages/ai-parrot-tools/src/parrot_tools/serpapi.py
#   packages/ai-parrot-tools/src/parrot_tools/zipcode.py
#   packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_tool_bridge.py
```

### Does NOT Exist
- ~~`[tool.ruff]` in any `pyproject.toml`~~ — ruff config lives ONLY in the repo-root `ruff.toml`.
- ~~a glob syntax for banned-api~~ — each module name is an explicit table key; `langchain` does NOT cover `langchain_core`.
- ~~`fidelity.check_banned_imports` (sync)~~ — it is `async` (spawns ruff); `check_fidelity` stays sync and pure.
- ~~importing `parrot.flows.dev_loop.sdd_coder.engine` from `fidelity.py`~~ — engine imports fidelity (engine.py:40); reverse import is circular.

---

## Implementation Notes

### Key Constraints
- `ruff` is resolved from `PATH` (the engine process runs from the venv, where `ruff 0.16.3` is installed); expose `ruff_bin: str = "ruff"` as a keyword for tests.
- ruff exit codes: 0 clean, 1 findings, ≥2 error. Missing binary (`FileNotFoundError`) or rc ≥ 2 → `["ruff: <stderr or exception>"]` — fail closed, never raise.
- Only `.py` paths are passed; empty selection returns `[]` without spawning.
- `--output-format json` gives a list of `{filename, location: {row}, message, code}`; render `f"{filename}:{row}: {message}"` with `filename` made relative to `cwd`.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `ruff.toml` (three blocks) — *why*: the rule must exist before the wrapper can find anything.
2. Run `ruff check --select TID251 packages/ scripts/` from the repo root — must exit 0 — *why*: the backlog policy in `ruff.toml`'s header: the rule may not add findings on `dev`.
3. Append `check_banned_imports` to `fidelity.py` — *why*: engine wiring (TASK-3183) imports it from here.
4. Add tests; run `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py -v`.

### `ruff.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^select = \["E4", "E7", "E9", "F"\]' ruff.toml)
# REPLACE line 101 with:
select = ["E4", "E7", "E9", "F", "TID251"]

# occurrences: 1 (verified: grep -c '^\[lint.per-file-ignores\]' ruff.toml)
# BEFORE — insert directly above `[lint.per-file-ignores]` (verified: ruff.toml:103):
# FEAT-553: forbidden modules (TID251). Substitutes are named in .agent/rules/codebase-conventions.md.
# One entry per top-level name — banned-api has no globs, so `langchain` does NOT cover `langchain_core`.
[lint.flake8-tidy-imports.banned-api]
"requests".msg            = "Use aiohttp (parrot.interfaces.http) — requests is synchronous and banned."
"httpx".msg               = "Use aiohttp — httpx is banned in this repository."
"starlette".msg           = "The HTTP stack is aiohttp + navigator-api behind gunicorn — starlette is banned."
"fastapi".msg             = "The HTTP stack is aiohttp + navigator-api behind gunicorn — fastapi is banned."
"uvicorn".msg             = "Serve with gunicorn (aiohttp worker) — uvicorn is banned."
"langchain".msg           = "LangChain was removed; use parrot primitives (AbstractClient, AbstractTool, …)."
"langchain_core".msg      = "LangChain was removed; use parrot primitives."
"langchain_community".msg = "LangChain was removed; use parrot primitives."
"langgraph".msg           = "LangGraph is banned; use AgentsFlow / AgentCrew (parrot.bots.flows)."
"langsmith".msg           = "LangSmith is banned; use parrot observability."

# occurrences: 1 (verified: grep -c '^"examples/\*\*/\*.py" = ' ruff.toml)
# AFTER — insert below `"examples/**/*.py" = ["F401", "F841", "E402"]` (verified: ruff.toml:117):
# FEAT-553: files that imported a banned module BEFORE the ban (17, measured 2026-09-12).
# Grandfathered so the rule bites only new code. NEVER add a file to this list.
"packages/ai-parrot/src/parrot/flows/dev_loop/replication.py" = ["TID251"]
"packages/ai-parrot/src/parrot/interfaces/http.py" = ["TID251"]
"packages/ai-parrot/src/parrot/interfaces/jira/client.py" = ["TID251"]
"packages/ai-parrot/src/parrot/interfaces/onedrive.py" = ["TID251"]
"packages/ai-parrot/src/parrot/interfaces/sharepoint.py" = ["TID251"]
"packages/ai-parrot/src/parrot/interfaces/soap.py" = ["TID251"]
"packages/ai-parrot/src/parrot/tools/openapitoolkit.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/bingsearch.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/massive/client.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/o365/delta.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/powerbi.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/research/academic.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/research/open_data.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/serpapi.py" = ["TID251"]
"packages/ai-parrot-tools/src/parrot_tools/zipcode.py" = ["TID251"]
"packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_tool_bridge.py" = ["TID251"]
```
**Why this shape**: exact table from spec §3 M4 (plus the four `langchain*`/`langgraph`/`langsmith` rows from §8 Q4); TOML tables must come before the next `[table]` header, hence the insertion order.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def check_fidelity(' …/fidelity.py)
# AFTER — append at end of file, below `check_fidelity` (verified: fidelity.py:49-57); add `import asyncio`, `import json`, `import os` to the imports at :4-8
async def check_banned_imports(cwd: str, changed: List[str], *, ruff_bin: str = "ruff") -> List[str]:
    """Banned-import findings (ruff TID251, `ruff.toml` banned-api) for the changed `.py` files in `cwd`.

    Returns one ``"<path>:<row>: <message>"`` line per finding; ``[]`` when clean or when
    ``changed`` holds no ``.py`` file (ruff is not spawned then). Fails closed: a missing ruff
    or an exit code >= 2 yields a single ``"ruff: <reason>"`` line. Never raises.
    """
    py_files = [p for p in changed if p.endswith(".py")]
    if not py_files:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            ruff_bin, "check", "--select", "TID251", "--no-fix", "--output-format", "json", *py_files,
            cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except (FileNotFoundError, OSError) as exc:
        return [f"ruff: {exc}"]
    if proc.returncode not in (0, 1):
        return [f"ruff: exit {proc.returncode}: {err.decode('utf-8', 'replace').strip()}"]
    # FILL IN: parse json.loads(out or b"[]"); for each item render
    #   f"{os.path.relpath(item['filename'], cwd)}:{item['location']['row']}: {item['message']}"
    #   — bounded by spec §3 M4 skeleton; tolerate a malformed JSON body by returning ["ruff: unparseable output"]
```
**Why this shape**: mirrors `engine._git`'s exec idiom (no shell), keeps the contract "never raises", and leaves the engine free to decide what a finding means (TASK-3183).

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py` (MODIFY)
```python
# AFTER — append at end of file (verified: last test `test_fidelity_rejects_unexpected_and_sdd` at :23)
from pathlib import Path

from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports

_BANNED_CFG = '[lint]\nselect = ["TID251"]\n[lint.flake8-tidy-imports.banned-api]\n"requests".msg = "use aiohttp"\n"httpx".msg = "use aiohttp"\n'


def _sandbox(tmp_path: Path) -> Path:
    (tmp_path / "ruff.toml").write_text(_BANNED_CFG)   # ruff discovers the nearest ruff.toml above cwd
    (tmp_path / "pkg").mkdir()
    return tmp_path


async def test_check_banned_imports_flags_requests(tmp_path):
    root = _sandbox(tmp_path)
    (root / "pkg" / "a.py").write_text("import requests\n")
    lines = await check_banned_imports(str(root), ["pkg/a.py"])
    assert len(lines) == 1 and lines[0].startswith("pkg/a.py:1:")


async def test_check_banned_imports_clean_and_empty(tmp_path):
    # FILL IN: clean file → []; changed=[] → [] (assert ruff not spawned: pass ruff_bin="/nonexistent" and still expect []) — bounded by AC-8


async def test_check_banned_imports_skips_non_python(tmp_path):
    # FILL IN: changed=["README.md", "cfg.toml"] → [] with ruff_bin="/nonexistent" — bounded by AC-8


async def test_check_banned_imports_fails_closed_without_ruff(tmp_path):
    root = _sandbox(tmp_path)
    (root / "pkg" / "a.py").write_text("x = 1\n")
    lines = await check_banned_imports(str(root), ["pkg/a.py"], ruff_bin="/nonexistent/ruff")
    assert lines and lines[0].startswith("ruff:")
```

### FILL IN checklist
- [ ] `fidelity.py::check_banned_imports` — JSON rendering loop; bounded by the `"<path>:<row>: <message>"` contract
- [ ] two test bodies; bounded by AC-8

---

## Acceptance Criteria

- [ ] `ruff check --select TID251 packages/ scripts/` exits 0 from the repo root (spec AC-7)
- [ ] `ruff check --select TID251 -` with `import requests` on stdin reports TID251 with the aiohttp message
- [ ] `check_banned_imports()` contract: one line per finding, `[]` when clean/empty/non-py, `["ruff: …"]` when ruff is missing (spec AC-8)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` clean; existing `test_fidelity` tests still pass

---

## Test Specification

See the MODIFY test block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M4, §7 "TID251 backlog", §8 Q4)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — `ruff.toml:101/103/117` anchors and `ruff --version` = 0.16.x
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; never extend the grandfather list beyond the 17 files
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3182-ruff-tid251-and-banned-import-check.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none
