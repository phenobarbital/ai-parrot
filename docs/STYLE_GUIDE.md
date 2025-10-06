# AI Parrot Code Style Guide

[Back to README](../README.md)

This guide defines conventions for Python code in the `ai-parrot` project. It complements PEP 8 and focuses on clarity, correctness, and maintainability across bots, tools, clients, stores, handlers, and models.

## Python & Tooling
- **Version**: Target Python 3.10+ (project target `>=3.10.1`; CI uses 3.11). 
- **Formatting**: Follow PEP 8. Prefer Black-compatible formatting (120 cols max if long data structures demand it). Use the repo `pyproject.toml` settings.
- **Typing**: Use type hints for public APIs, function signatures, dataclasses/models, and complex local variables. Avoid `Any` unless necessary.
- **Imports**:
  - Standard lib, third-party, local imports (in that order).
  - Absolute imports within the package (e.g., `from parrot.tools.manager import ToolManager`).
  - Avoid circular imports; refactor shared code to dedicated modules.

## Naming
- **Files/Modules**: snake_case.
- **Classes**: PascalCase.
- **Functions/Methods**: snake_case, must be verbs/verb phrases.
- **Variables**: descriptive nouns; avoid 1–2 letter names (except for trivial indices).
- **Constants/Enums**: UPPER_SNAKE_CASE.

## Docstrings
- Use triple double quotes.
- For modules, classes, and all public functions/methods:
  - 1-line summary
  - Optional paragraphs with context
  - Args/Returns/Raises sections where applicable
- Keep user-facing wording clear and concise (this project’s APIs are used by other developers and by UI surfaces).

Example:
```python
def create_sql_agent(database_flavor: str, connection_string: str, **kwargs) -> SQLDbAgent:
    """Factory for SQL database agents.

    Args:
        database_flavor: Database type ('postgresql', 'mysql', 'sqlserver').
        connection_string: SQLAlchemy-style connection string.

    Returns:
        Configured `SQLDbAgent` instance.
    """
```

## Error Handling
- Fail fast with clear messages. Prefer `ValueError`, `TypeError`, `RuntimeError`, etc.
- Validate external inputs early (HTTP payloads, DB params, tool args).
- Use guard clauses and avoid deep nesting.
- When catching exceptions, narrow the scope and log with context. Prefer raising with context over silent failures.

## Logging
- Use the component logger pattern (e.g., `self.logger = logging.getLogger(f"{self.name}.Bot")`).
- Log at appropriate levels: `debug` (dev details), `info` (major events), `warning` (recoverable anomalies), `error` (failures), `exception` (with traceback).
- Avoid logging sensitive credentials or large payloads.

## Concurrency & Async IO
- Handlers and tools that perform IO (HTTP, DB, filesystem) should be async where supported.
- Prefer `async with`/`await` and use connection pools/clients designed for concurrency.
- Avoid blocking CPU work in async paths; offload to workers if needed.
- When enqueueing background work, use the provided `register_background_task` on handlers and keep task functions pure and idempotent. Use `done_callback` to persist results; handle exceptions and log context.
- Job tracking is Redis-backed; ensure `CACHE_URL` is configured. Do not rely on `KEYS` in production debugging; use `SCAN` and prefer `UNLINK` over `DEL`.

## Configuration & Defaults
- Use explicit, documented defaults. For LLMs and models, prefer centralized presets (`LLM_PRESETS`) or constructor kwargs.
- Read config from kwargs/`model_config`; keep runtime overrides explicit.
- For time values, prefer epoch ms where interoperating with BigQuery/Scylla, or timezone-aware `datetime` for PG.

## Models (`datamodel.Field`)
- Define constraints/choices and provide `ui_help` for all user-facing fields.
- Keep `to_bot_config()` mapping consistent with bot constructors.
- Validate enumerations at init (`operation_mode`, `memory_type`, etc.).

## Tools & ToolManager
- Tools must derive from `AbstractTool` and define:
  - `name`, `description`
  - Pydantic args schema (input validation)
  - Deterministic outputs; prefer `ToolResult`
- Register tools via `ToolManager` and keep legacy pathways backwards compatible.
- Never hardcode secrets; pass via config or environment.

## Clients (LLMs)
- Clients must extend `AbstractClient` and support:
  - Streaming and non-streaming
  - Tool calling and (where supported) structured output
  - Clear error surfaces for provider-specific limitations
- Keep provider quirks encapsulated (e.g., Groq tools + JSON mode limitations). Use `ToolSchemaAdapter` to normalize tool schemas per provider (`openai`, `anthropic`, `google`, `groq`, `vertex`).

## Stores & Loaders
- Stores implement `AbstractStore` with consistent CRUD/search semantics.
- Vector operations must document metric types and dimensions.
- Loaders should be pure and idempotent; avoid global state.

## Handlers & Interfaces
- Keep handlers thin; validate, dispatch to bots/tools, serialize results.
- Return structured responses (`AIMessage`, `AgentResponse`).
- Reuse decorators for auth/permissions (`auth_groups`, `auth_by_attribute`).
- Expose predictable HTTP surfaces: POST to enqueue (202 + `task_id`), GET to poll job (`results/{task_id}`), and GET to list jobs for current user. Avoid leaking internal errors; provide `error` and `stacktrace` fields when available. For chatbots, support `POST /api/v1/chat/{chatbot_name}/{method_name}` with dynamic param validation via `inspect.signature`.

## Testing
- Unit-test tools, clients, and model mappings.
- Prefer small, deterministic fixtures; avoid network in unit tests.
- Add regression tests when fixing bugs (e.g., ToolManager initialization).

## Performance
- Batch external calls where possible; use pagination/limits.
- Avoid unnecessary copies of large dataframes/blobs.
- Measure with timers in debug logs when optimizing.

## Style Do’s & Don’ts
- Prefer early returns over deep nesting.
- Use meaningful variable names; avoid magic numbers/strings (introduce constants).
- Keep functions short and focused; extract helpers.
- Do not add inline commentary comments; document intent via names and docstrings.


