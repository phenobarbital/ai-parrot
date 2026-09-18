---
trigger: always_on
---
# AI-Parrot codebase conventions

Binding for every file you touch in this repository — Python, Cython, Rust and the
TypeScript/Svelte admin UI alike. If a task file and this document disagree, STOP and
report — never pick one silently.

## Stack
- HTTP: **aiohttp** + **navigator-api**, served by **gunicorn** (aiohttp worker). There is no ASGI stack.
- Async-first: I/O paths are `async def`; never block the event loop (no `time.sleep`, no sync HTTP or DB drivers in async code).
- LLM calls go through `AbstractClient` (`parrot/clients/base.py`); never call a provider SDK directly. Do not modify `clients/base.py` unless a task says so.
- Data structures are **Pydantic v2** models. Logging is `self.logger` (`logging.getLogger(__name__)`), never `print`.
- Tools: `@tool` for functions, `AbstractToolkit` for collections; every tool has a docstring (it is the LLM-facing description).
- Charts: return data for structured-chart/A2UI; `altair` only for complex viz — never matplotlib/seaborn.

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
- Admin UI (Svelte 5 + Vite): `packages/ai-parrot-server/ui/`.

## Tooling — pick the mode that matches how you run
- **Interactive shell** (humans, Claude Code, codex, agy): `source .venv/bin/activate` first; then `uv add` / `uv pip`, `pytest`, `ruff check`, `black`. Never run `python`/`uv`/`pip` outside the venv.
- **Tool-driven coder without a shell** (dev-loop in-process seats): there is no shell — never try `source`, `cd`, pipes or `>`. Call the allowlisted binaries directly (`pytest`, `ruff`, `python`, `uv`); the host resolves them on its `PATH`. Do not create or look for a `.venv` inside your worktree — it is a bare git worktree.
- Common: `black` (line-length 120) formats; `ruff check` is the lint gate; tests use `pytest` + `pytest-asyncio`; run your task's tests before committing.

## Python
- Google-style docstrings and strict type hints on every function and class.
- `snake_case` functions/variables, `PascalCase` classes, 120-column lines; PEP 8 otherwise.
- Context managers for resources; `async with` / `await` for I/O; multiprocessing (not threads) for CPU-bound work.
- Secrets come only from environment variables — never in code or committed files.
- Complete, working files: no `TODO`, no stubs, no "existing code here" placeholders.
- Minimal, focused diffs: touch only the files your task lists; never refactor outside scope.

## Cython (`*.pyx`, `*.pxd`, `*.pxi`)
- Prefer `cimport` over `import` for anything exposed via a `.pxd` (`from libc.math cimport sqrt`).
- Use Cython syntax (`cdef`, `cpdef`, `struct`) rather than pure-Python-mode decorators; statically type variables, functions and class attributes with `cdef`; call C functions directly.
- Ship a `.pxd` for every reusable module so others can `cimport` it; build through the package's `setup.py`; PEP 8 naming still applies.

## Rust (PyO3 + Maturin — `*.rs`, `Cargo.toml`)
- `crate-type = ["cdylib"]`, `maturin` as build backend; `maturin develop` for local testing, `maturin build --release` for wheels.
- `#[pymodule]` entry point; `#[pyfunction]` / `#[pyclass]` + `#[pymethods]` (`#[new]`, `#[getter]`/`#[setter]`, `#[pyo3(get, set)]`, `#[pyo3(signature = (...))]` for defaults).
- Modern `Bound<'py, T>` API (PyO3 ≥ 0.21); return `PyResult<T>`; map errors with `.map_err(|e| PyRuntimeError::new_err(e.to_string()))` or `create_exception!`.
- Keep the boundary thin: heavy lifting in pure Rust, `py.allow_threads` around long CPU work, `Python::with_gil` only when touching Python objects, no needless clones across the boundary.
- `cargo test` for internal logic, `pytest` for the exposed API.

## TypeScript + Svelte (admin UI)
- **Svelte 5 runes only** (`$state`, `$derived`, `$props`, `$effect`); never `export let` or other Svelte 4 patterns. Shared reactive state lives in `.svelte.ts` files.
- TypeScript `strict`; explicit types on component props and exported functions; import through the `$lib` alias, `$app/*` through the shims in `src/lib/shims/`.
- `src/lib/types/generated/` is produced by `pnpm generate` from `schemas/` — never hand-edit it.
- Styling: Tailwind 4 utilities + `app.css`; icons via `@iconify/svelte`.
- Package manager is `pnpm`; tests are `vitest` + `@testing-library/svelte` next to the code (`*.test.ts`); build with `pnpm build`. No prettier/eslint step exists — match the surrounding formatting.
