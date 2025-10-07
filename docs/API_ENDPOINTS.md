# API Endpoints Reference

[Back to README](../README.md)

Primary HTTP endpoints exposed by the application as configured in `app.py` and handler modules. All routes are served by `aiohttp` under navigator’s middleware (auth/session).

## Authentication
Endpoints generally require a valid session (navigator-auth). Provide session cookie or Authorization header as configured.

---
## Chat and Bots

### Bot management UI endpoints
- Registered via `BotManagement.setup(self.app, r'/api/v1/bot_management{slash:/?}{bot:[^/]*}')`.
  - GET `/api/v1/bot_management` — List all available chatbots and their configuration summary.
  - PUT `/api/v1/bot_management?bot={name}` — Upload files/URLs to index into a chatbot's vector store. Optional form fields: `loader`, `source_type` and loader-specific kwargs.

### Feedback types
- GET `/api/v1/feedback_types/{feedback_type}` — List enum values by category (`good` or `bad`).

### Bot feedback
- POST `/api/v1/bot_feedback` — Submit chatbot feedback (BigQuery backend).

### Prompt library
- Base `/api/v1/chatbots/prompt_library` — ModelView CRUD for `PromptLibrary`.

### Chatbot usage and shared questions
- Base `/api/v1/chatbots_usage` — ModelView for `ChatbotUsage` (BigQuery).
- POST `/api/v1/chatbots_usage` — Record a chatbot usage event (writes to BigQuery).
- Request body (JSON):
  - `chatbot_id` (uuid, required): Bot identifier.
  - `sid` (uuid, optional): Session id. If omitted, server may generate it in some contexts.
  - `user_id` (int, optional): User id. If omitted, resolved from session when available.
  - `source_path` (str, optional, default: `web`): Source identifier/path.
  - `platform` (str, optional, default: `web`): Client platform.
  - `origin` (str, optional): Client IP. Filled from request when omitted.
  - `user_agent` (str, optional): HTTP User-Agent. Filled from request when omitted.
  - `question` (str, optional): Prompt sent to the bot.
  - `response` (str, optional): Model response text.
  - `used_at` (int, required): Event time in epoch milliseconds.
  - `event_timestamp` (datetime/string, optional): Timestamp; if provided it's normalized.
  
  Notes:
  - The server computes `_at` internally as `"{sid}:{used_at}"` when missing.
  - UUID and datetime fields are normalized to strings for BigQuery storage.

  Example:
  ```bash
  curl -X POST http://<host>/api/v1/chatbots_usage \
    -H "Content-Type: application/json" \
    -d '{
      "chatbot_id": "00000000-0000-0000-0000-000000000000",
      "sid": "11111111-1111-1111-1111-111111111111",
      "user_id": 1,
      "question": "Hello?",
      "response": "Hi!",
      "used_at": 1737062400000
    }'
  ```

  Response (201):
  ```json
  {
    "message": "Chatbot Usage recorded.",
    "question": "Hello?",
    "sid": "11111111-1111-1111-1111-111111111111"
  }
  ```
- GET `/api/v1/chatbots/questions/{sid}` — Retrieve a shared Q/A by session ID.

### Chat endpoints
- GET `/api/v1/chats` — List available chats (registered by `BotManager`).
- GET `/api/v1/chat/{chatbot_name}` — Get chatbot metadata and configuration summary.
- POST `/api/v1/chat/{chatbot_name}` — Converse with the chatbot. JSON body requires `query`; optional: `search_type`, `return_sources`, `llm`, `model`, and additional kwargs.
- POST `/api/v1/chat/{chatbot_name}/{method_name}` — Invoke a public bot method. Missing required parameters will be reported with `required_params`.

---
## Agents (NextStop)
Base: `/api/v1/agents/nextstop` (registered in `app.py`).

- GET `/api/v1/agents/nextstop` — Return stored records for the current user (from `troc.nextstop_responses`).
- POST `/api/v1/agents/nextstop` — Start a background job; responds 202 with `task_id`.
- GET `/api/v1/agents/nextstop/results/{sid}` — Background job status/result by `task_id`.
- GET `/api/v1/agents/nextstop/status` — Agent status payload.
- GET `/api/v1/agents/nextstop/find_jobs` — Find background jobs for current user.

### POST /api/v1/agents/nextstop
Starts a background task handled by `NextStopAgent`. Requires authentication.

Accepted JSON body (send one of the following selectors):
- `store_id` (string) — generate report for a specific store.
- `manager_id` (string) and `employee_id` (string) — compare employee vs manager.
- `employee_id` (string) — generate report for an employee.
- `manager_id` (string) — generate team performance report.
- `query` (string) — free-form query.

Optional fields:
- `program` (string, default: `hisense`) — used as `program_slug`.
- `project` (string, default: `Navigator`) — used in manager/team flows.

Responses:
- 202 Accepted
  - Returns `task_id` and echo of selector fields. Use this id to poll results.
- 400 Bad Request
  - When no selector is provided.

Examples:

Store report
```bash
curl -X POST "$HOST/api/v1/agents/nextstop" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "store_id": "BBY1028",
    "program": "hisense"
  }'
```

Team performance
```bash
curl -X POST "$HOST/api/v1/agents/nextstop" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "manager_id": "aplacencia@hisenseretail.com",
    "program": "hisense"
  }'
```

Free-form query
```bash
curl -X POST "$HOST/api/v1/agents/nextstop" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "query": "Generate a weekly performance report",
    "program": "hisense"
  }'
```

### GET /api/v1/agents/nextstop/results/{task_id}
Returns background job status tracked in Redis.

Response payload (subset):
- `task_id` (string)
- `status` (string: pending|running|done|failed)
- `result` (any)
- `error` (string|null)
- `stacktrace` (string|null)
- `attributes` (object)
- `created_at`, `started_at`, `finished_at`

### GET /api/v1/agents/nextstop
Returns the list of `NextStopStore` records that belong to the current user (filtered by `employee_id` or `manager_id` from the session), or 204 when none.

### GET /api/v1/agents/nextstop/find_jobs
Lists jobs for the current user according to tracker attributes (`agent_name`, `user_id`).

Notes:
- Handlers come from `resources.nextstop.NextStopAgent` and `parrot/handlers/agents/*`.
- Job tracking uses `BackgroundService` with `tracker_type='redis'`. Ensure Redis is configured via `CACHE_URL`.

---
## Tools Catalog
- GET `/api/v1/agent_tools` — Returns the list of available tool definitions registered in the app.

---
## Notes
- Additional routes may be available depending on navigator integrations. See `app.py` and handler classes for details.
- Error payloads are standardized via `BaseView.error` and `JSONResponse` helpers.


