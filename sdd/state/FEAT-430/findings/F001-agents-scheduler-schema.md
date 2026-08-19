# F001 — AgentSchedule table schema

**Query:** Q001 (wiki_page)
**Citations:** `packages/ai-parrot-server/src/parrot/scheduler/models.py` :: `AgentSchedule`
**Wiki page:** `file:packages/ai-parrot-server/src/parrot/scheduler/models.py`
**Confidence:** high (direct source read)

## What was found

Table `navigator.agents_scheduler` (asyncdb Model, driver `pg`). Columns confirm
brainstorm §3.1 verbatim:

- `method_name VARCHAR` (nullable) — schedules arbitrary Python methods
- `schedule_type VARCHAR NOT NULL` + `schedule_config JSONB NOT NULL`
- `metadata JSONB DEFAULT '{}'` — natural scoping slot for `dashboard_id`
- `callbacks JSONB DEFAULT '[]'` — delivery hooks
- `send_result JSONB DEFAULT '{}'`
- `enabled`, `last_run`, `next_run`, `run_count`
- `created_by INTEGER`, `created_email VARCHAR` — ownership/permission hooks
- `is_crew BOOLEAN`, `scheduler_type VARCHAR DEFAULT 'default'`

## Constraint NOT anticipated by the brainstorm

`agent_id: str = Field(required=True)` and `agent_name: str = Field(required=True)`
are **required**, with `Meta.strict = True`. A dashboard-refresh schedule is not an
agent, so SPEC-A must either:
  (a) supply synthetic/sentinel agent_id + agent_name values, or
  (b) relax the model to make them optional for `method_name`-only rows.

This is a first-adopter friction point of exactly the kind brainstorm §3.1 warns about
("it exists but nobody uses it"). Affects the thin NavAPI wrapper design (§4.1.C).
