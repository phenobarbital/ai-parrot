<!-- parrot:wiki:google:begin -->
## Codebase Knowledge Graph (LLM Wiki)

This repository has an ai-parrot LLM-wiki. Before scanning source files, run `wikitoolkit query "<focused question>"` or use the `wiki_*` MCP tools, then inspect a result with `wikitoolkit page <id>` or `wikitoolkit related <id>`. When you learn a durable fact or decision, save it: `wikitoolkit remember "<fact>" --category decision`.

<!-- parrot:wiki:google:end -->

<!-- parrot:conventions:google:begin -->
## Project conventions

## Project rule: codebase-conventions

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

---

## Project rule: python-development

You are an expert in Python, AI, and Machine Learning development.

**CRITICAL ENVIRONMENT RULES:**
1. **Package Manager**: You MUST use **`uv`** for all package management (e.g., `uv pip install`, `uv pip list`, `uv add`).
2. **Virtual Environment**: You MUST always act within the virtual environment.
   - **Interactive shell**: NEVER run `uv`, `python`, or `pip` without first activating it — run `source .venv/bin/activate` before any python-related command.
   - **Tool-driven coder with no shell** (the dev-loop in-process seats): you cannot `source`; run the allowlisted `pytest` / `ruff` / `python` / `uv` binaries directly — the host resolves them on its `PATH` — and never provision a `.venv` in your worktree.
3. **Dependencies**: All dependencies must be managed via `pyproject.toml`.

Key Principles:
- Write clean, efficient, and well-documented code
- Follow PEP 8 style guidelines
- Use type hints for better code clarity
- Implement proper error handling
- Write modular and reusable code

Python Best Practices:
- Follow naming conventions (snake_case for functions/variables)
- Use list comprehensions and generator expressions
- Use context managers (with statement)
- Implement proper logging

Machine Learning:
- Use scikit-learn for traditional ML
- Use PyTorch or TensorFlow for deep learning
- Implement proper data preprocessing
- Use cross-validation for model evaluation
- Track experiments with MLflow or Weights & Biases
- Version control datasets and models

Data Processing:
- Use pandas for data manipulation
- Use numpy for numerical computations
- Return data for visualization via structured-chart/A2UI; use altair for complex viz only
- Implement data validation
- Handle missing data appropriately
- Use efficient data structures

Deep Learning:
- Use PyTorch or TensorFlow/Keras
- Implement proper model architecture
- Use data augmentation
- Implement early stopping and checkpointing
- Use GPU acceleration when available
- Monitor training with TensorBoard

Model Deployment:
- Use aiohttp for serving models
- Implement model versioning
- Use Docker for containerization
- Implement proper API documentation
- Add input validation and error handling
- Monitor model performance in production

Testing:
- Write unit tests with pytest and pytest-asyncio
- Test data pipelines
- Test model predictions
- Use fixtures for test data
- Implement integration tests

Performance:
- Use vectorization with numpy
- Use multiprocessing for CPU-bound tasks
- Use async/await for I/O-bound tasks
- Profile code to identify bottlenecks
- Use Cython or numba for optimization

<!-- parrot:conventions:google:end -->
