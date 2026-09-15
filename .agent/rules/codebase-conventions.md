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