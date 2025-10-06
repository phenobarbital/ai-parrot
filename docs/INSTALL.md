# Installation Guide

[Back to README](../README.md)

This guide explains how to install and run ai-parrot from source and using uv.

## Prerequisites
- Python 3.10–3.12
- Git
- System libs for science stack (Debian/Ubuntu):
  - `build-essential libffi-dev libssl-dev libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev`
- Optional: Redis, PostgreSQL, BigQuery credentials depending on features

## Clone the repository
```bash
git clone git@github.com:phenobarbital/ai-parrot.git
cd ai-parrot
```

## Install with uv (recommended)
uv is a fast Python package manager.

- Install uv (see docs): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Create and activate environment, then install project:
```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .[all]
```
- Optional extras by area:
  - `.[agents]`, `.[loaders]`, `.[images]`, `.[vector]`, `.[anthropic]`, `.[openai]`, `.[google]`, `.[groq]`, `.[milvus]`, `.[chroma]`, `.[eda]`

## Install from source with pip
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e .[all]
```

## Environment configuration
The app relies on `navconfig` for settings (env vars, .ini files). Common variables:

- Database (PostgreSQL): `DBHOST`, `DBUSER`, `DBPWD`, `DBNAME`, `DBPORT`
- Redis:
  - Preferred single URL: `CACHE_URL` (e.g., `redis://localhost:6379/0`)
  - Legacy separate vars: `CACHE_HOST`, `CACHE_PORT`
  - Conversation/store cache: `REDIS_HISTORY_URL` (optional; defaults used if unset)
- BigQuery: `BIGQUERY_CREDENTIALS`, `BIGQUERY_PROJECT_ID`, `BIGQUERY_DATASET`
- LLM providers:
  - OpenAI: `OPENAI_API_KEY`
  - Anthropic: `ANTHROPIC_API_KEY`
  - Google: `GOOGLE_API_KEY`, `GOOGLE_CREDENTIALS_FILE`
  - Groq: `GROQ_API_KEY`
- Vector stores (Milvus/Qdrant/Chroma): see `parrot/conf.py`

Create an `.env` or navigator `.ini` as needed. Example minimal environment:
```bash
export DBHOST=localhost
export DBUSER=postgres
export DBPWD=postgres
export DBNAME=navigator
export CACHE_URL=redis://localhost:6379/0
export OPENAI_API_KEY=sk-...
```

## Running the application
ai-parrot integrates with navigator-api. The entry `Main` AppHandler is defined in `app.py`.

### Run with navigator-api
If you have `navigator-api` installed, you can run the ASGI server:
```bash
python -m navigator run --app app:Main --host 0.0.0.0 --port 5000
```
Alternatively, using uvicorn directly if supported by your navigator version:
```bash
uvicorn app:Main --factory --host 0.0.0.0 --port 5000
```

### Verify routes
Once running, key endpoints (authenticated) include:
- `GET /api/v1/chats`
- `GET /api/v1/chat/{chatbot_name}`
- `POST /api/v1/chat/{chatbot_name}` (converse)
- `POST /api/v1/chat/{chatbot_name}/{method_name}` (invoke a bot method)
- `PUT /api/v1/chatbots` (create bot)
- `GET /api/v1/feedback_types/{feedback_type}`
- `POST /api/v1/bot_feedback`
- `POST /api/v1/chatbots_usage` (record usage)
- `GET /api/v1/chatbots/questions/{sid}`
- `GET /api/v1/agent_tools` (list registered tools)
- Bot management UI: `GET /api/v1/bot_management` (list bots)
- Bot document upload: `PUT /api/v1/bot_management?bot={name}` (upload files/URLs)
- NextStop agent: `/api/v1/agents/nextstop` and related routes

### Background jobs & Redis tracker
The application wires a `BackgroundService` for agents with a Redis-backed tracker. Ensure Redis is reachable at `CACHE_URL`. When invoking `POST /api/v1/agents/nextstop`, the server returns a `task_id` that you can poll via `GET /api/v1/agents/nextstop/results/{task_id}`. If Redis is unavailable, background tracking will fail.

Note: Endpoints require `navigator-auth` session/token. See your auth setup for login and token retrieval.

## Development
- Install dev tools: `uv pip install -r requirements/requirements-dev.txt` or `pip install -r requirements/requirements-dev.txt`
- Lint/test: `pylint parrot`, `pytest -q`
- Black: `black .`

## Troubleshooting
- Missing deps on Linux: ensure build tools and headers are installed
- BigQuery errors: validate `BIGQUERY_CREDENTIALS` path/JSON
- Auth 401/403: ensure session middleware and token headers are set
- Tool errors: verify ToolManager initialization and tool registration


