# Module-level Functions Catalog

[Back to README](../README.md)

This document lists notable module-level functions in the `parrot` package. Methods inside classes are covered in `CLASSES.md`.

> Note: Summaries are derived from code/docstrings. See source for signatures and edge cases.

## Core and Utilities
- `parrot/__init__.py` — `get_project_root() -> Path`: Resolve project root.
- `parrot/conf.py` — `resolve_cert(crt)`: Resolve certificate paths.
- `parrot/utils/uv.py` — `install_uvloop()`: Install `uvloop` if available.

## Handlers and Models
- `parrot/handlers/models.py` — `default_embed_model() -> dict`: Default embedding model config.
- `parrot/handlers/models.py` — `created_at(*args, **kwargs) -> int`: Epoch milliseconds.
- `parrot/handlers/models.py` — `create_bot(bot_model: BotModel, bot_class=None)`: Build a bot from `BotModel`.
- `parrot/handlers/agents/abstract.py` — `register_background_task(task, request=None, done_callback=None, *args, **kwargs) -> JobRecord`: Enqueue an async task through `BackgroundService`; returns a job record with `task_id`.
- `parrot/handlers/agents/abstract.py` — `get_task_status(task_id, request=None) -> JSONResponse`: Read job status from the background tracker (Redis-backed).
- `parrot/handlers/agents/abstract.py` — `find_jobs(request) -> web.Response`: Find jobs for the current user using tracker attributes.

## Stores
- `parrot/stores/postgres.py` — `vector_distance(embedding_column, vector, op)`: SQL expr for vector distance.

## Tools and Tooling
- `parrot/tools/toolkit.py` — `tool_schema(schema: Type[BaseModel]) -> dict`: Build tool schema from Pydantic model.
- `parrot/tools/pythonrepl.py` — `brace_escape(text: str) -> str`: Escape braces for format strings.
- `parrot/tools/pythonrepl.py` — `sanitize_input(query: str) -> str`: Sanitize input for REPL.
- `parrot/tools/pdfprint.py` — `count_tokens(text: str, model: str = "gpt-4") -> int`: Token estimator.
- `parrot/tools/gvoice.py` — `strip_markdown(text: str) -> str`: Remove markdown.
- `parrot/tools/gvoice.py` — `markdown_to_plain(md: str) -> str`: Markdown → plain text.
- `parrot/tools/querytoolkit.py` — `is_collection_model(structured_obj: type) -> bool`
- `parrot/tools/querytoolkit.py` — `get_model_from_collection(collection_model: type) -> type`
- `parrot/tools/nextstop/base.py` — `is_collection_model(structured_obj: type) -> bool`
- `parrot/tools/nextstop/base.py` — `get_model_from_collection(collection_model: type) -> type`

## Handlers (HTTP)
- `parrot/handlers/chat.py` — within `ChatHandler.post`: validates required method parameters dynamically via `inspect.signature`; reports `required_params` when missing. Accepts `query`, `search_type`, `return_sources`, optional `llm` and `model`.

## Agents & Background Jobs
- `parrot/handlers/agents/abstract.py` — `register_background_task(...) -> JobRecord`: Enqueue async tasks via `BackgroundService`.
- `parrot/handlers/agents/abstract.py` — `get_task_status(task_id, request=None) -> JSONResponse`: Read job status from Redis tracker.
- `parrot/handlers/agents/abstract.py` — `find_jobs(request) -> web.Response`: Find jobs by tracker attributes.

## DB Agents Factories
## NextStop Helpers
- `resources/nextstop/handler.py` — `open_prompt(prompt_file) -> str`: Read a prompt file for the agent.
- `resources/nextstop/handler.py` — `ask_agent(query=None, prompt_file=None, *args, **kwargs) -> Tuple[AgentResponse, AIMessage]`: Execute the agent conversation and return structured response.
- `resources/nextstop/handler.py` — `_generate_report(response) -> NextStopResponse`: Produce transcript, PDF, and podcast; fill response metadata.

- `parrot/bots/db/sqlagent.py` — `create_sql_agent(...) -> SQLDbAgent`: SQL agent factory.
- `parrot/bots/db/elastic.py` — `create_elasticsearch_agent(...) -> ElasticDbAgent`: Elasticsearch agent factory.
- `parrot/bots/db/influx.py` — `create_influxdb_agent(...) -> InfluxDBAgent`: InfluxDB agent factory.
- `parrot/bots/db/multi.py` — `integrate_with_parrot_bot(bot, database_configs) -> None`: Compose DB capabilities into a bot.

## Loaders and Media Helpers
- `parrot/loaders/youtube.py` — `extract_video_id(url: str) -> Optional[str]`
- `parrot/loaders/basevideo.py` — `extract_video_id(url)`
- `parrot/loaders/videolocal.py` — `split_text(text, max_length)`

## Interfaces and Plugins
- `parrot/interfaces/http.py` — `bad_gateway_exception(exc)`: Build standardized 502 response.
- `parrot/interfaces/images/plugins/exif.py` — `_json_safe(obj)`, `_make_serialisable(val)`, `get_xmp_modify_date(...)`

## Models helpers
- `parrot/models/agents.py` — `created_at(*args, **kwargs) -> int`: Epoch ms helper.

## Data prompts
- `parrot/bots/data.py` — `brace_escape(text: str) -> str`: Escape braces in data prompts.

---
If a function is missing, it is likely private or a method; see source modules for details.


