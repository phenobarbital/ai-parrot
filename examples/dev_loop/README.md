# Dev-Loop Orchestration — Examples (FEAT-129)

Runnable examples for the five-node `AgentsFlow`
(`BugIntake → Research → Development → QA → DeploymentHandoff`)
defined in `sdd/specs/dev-loop-orchestration.spec.md` and implemented
under `parrot/flows/dev_loop/`.

```
examples/dev_loop/
├── README.md          ← this file
├── quickstart.py      ← real-mode programmatic example (no UI)
├── server.py          ← aiohttp server: real flow + WS multiplexer
└── static/
    └── index.html     ← vanilla-JS UI client (no build step)
```

Both entry points wire the **real** flow — no fakes, no stubs. They differ
only in how the run is triggered: `quickstart.py` calls `flow.run_flow(...)`
once and exits; `server.py` exposes an HTTP + WebSocket surface so the UI
client can start runs and visualise the merged event stream live.

## Prerequisites

| Requirement | Why |
|---|---|
| `uv` + activated `.venv` (`source .venv/bin/activate`) | Per project policy |
| Local Redis on `REDIS_URL` (default `redis://localhost:6379/0`) | Two streams per run + multiplexer |
| `ANTHROPIC_API_KEY` (or any provider key the SDK accepts) | `ClaudeAgentClient` (FEAT-124) |
| `claude` CLI on `$PATH`, authenticated | The SDK shells out to it |
| `gh` CLI authenticated | `DeploymentHandoffNode` opens the PR |
| Jira service account: `JIRA_INSTANCE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_PROJECT`, `FLOW_BOT_JIRA_ACCOUNT_ID` | Tickets are created/transitioned by `flow-bot` (toolkit uses `basic_auth`); tickets are always opened as `Bug` |
| Reporter / escalation identities: `JIRA_REPORTER_ACCOUNT_ID`, `JIRA_ESCALATION_ACCOUNT_ID`, `FLOW_BOT_JIRA_ACCOUNT_ID` | Each accepts **either an email or a Jira accountId** — emails are resolved server-side via `jira_find_user`. `FLOW_BOT_JIRA_ACCOUNT_ID` is the fallback when reporter/escalation are unset. |
| `AWS_PROFILE` (default `cloudwatch`) and `CLOUDWATCH_LOG_GROUP` (default `fluent-bit-cloudwatch`) | `ResearchNode` pulls log excerpts; the log group is bound at toolkit construction, not per query |
| `DEV_LOOP_SUMMARY_LLM` (default `anthropic:claude-haiku-4-5-20251001`) | Model used by `ResearchNode` to summarize log excerpts when the raw Jira description would exceed Atlassian's 32 767-char cap |
| `DEV_LOOP_PLAN_LLM` (default `""` → falls back to `DEV_LOOP_SUMMARY_LLM`) | Optional override for the model used by `ResearchNode` to generate the plan-summary comment posted on newly-created tickets. When unset, the same model as `DEV_LOOP_SUMMARY_LLM` is used. FEAT-132. |

Quickest local Redis:
```bash
docker run --rm -p 6379:6379 redis:7
```

## Programmatic example — `quickstart.py`

```bash
source .venv/bin/activate
python examples/dev_loop/quickstart.py
```

What it does:

1. Builds a `ClaudeCodeDispatcher` with the global semaphore from
   `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`.
2. Builds a service-account `JiraToolkit` and the CloudWatch + ES log
   toolkits.
3. Calls `build_dev_loop_flow(...)` (factory at
   `parrot/flows/dev_loop/flow.py:101`).
4. Runs the bundled sample `BugBrief` (a deliberately broken
   `etl/customers/sync.yaml`) through `flow.run_flow(...)`.
5. Prints the final per-node outputs.

Use this script as the canonical reference for embedding the dev-loop
in your own service.

## Server + UI — `server.py` + `static/index.html`

```bash
source .venv/bin/activate
python examples/dev_loop/server.py
# open http://localhost:8080
```

`server.py` builds the same flow as `quickstart.py` and exposes:

| Endpoint | Method | Purpose |
|---|---|---|
| `/`                            | GET   | Serves the UI client |
| `/api/flow/run`                | POST  | Start a real flow run; body = `BugBrief` JSON (or `{}` for the sample) |
| `/api/flow/{run_id}/ws`        | GET   | `flow_stream_ws` — multiplexed WebSocket |
| `/api/flow/{run_id}/replay`    | GET   | JSON dump of every stored event for a run |

The UI is a single static file with no build step:

* Five panels, one per node, with status pills
  (`idle / queued / running / passed / failed`).
* "Start dev-loop run" POSTs to `/api/flow/run`, gets back a `run_id`,
  then opens a WebSocket to `/api/flow/{run_id}/ws?view=both&replay=true`.
* Each event is appended under its node's panel; the pill colour follows
  `dispatch.queued / dispatch.started / dispatch.completed / dispatch.failed`
  and the flow-level `flow.bug_brief_validated` / `flow.pr_opened` /
  `flow.completed` events.
* "Reconnect" replays history before resuming the live tail (useful after
  a network blip).

### Form payload (and equivalent curl)

The UI builds and posts this JSON shape to `POST /api/flow/run`. You can
also drive the same endpoint from the CLI:

```bash
curl -X POST http://localhost:8080/api/flow/run \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "enhancement",
    "summary": "Order webhook signature mismatch on retries",
    "affected_component": "etl/orders/webhook.yaml",
    "description": "Observed in prod 2026-04-28; only the second retry fails. See OPS-4321.",
    "acceptance_criteria": [
      "ruff check .",
      "mypy --no-incremental"
    ],
    "log_group": "fluent-bit-cloudwatch",
    "time_window_minutes": 90
  }'
```

The `kind` field controls how the flow routes the request (FEAT-132):

| UI radio | JSON value | Jira issuetype | Flow path |
|---|---|---|---|
| Bug (default) | `"bug"` | Bug | `IntentClassifier → BugIntake → Research → …` |
| Enhancement | `"enhancement"` | Story | `IntentClassifier → Research → …` (skips BugIntake) |
| New Feature | `"new_feature"` | New Feature | `IntentClassifier → Research → …` (skips BugIntake) |

The server normalises the payload into a `WorkBrief`, validates the
shell-command heads against `ACCEPTANCE_CRITERION_ALLOWLIST` (`flowtask`,
`pytest`, `ruff`, `mypy`, `pylint`), and starts a real flow run.

#### Acceptance-criterion syntax

Each acceptance criterion is **one line** in the textarea (or one
element in the JSON array). The parser classifies it by inspecting the
first whitespace-separated token:

| Line | Classified as | Behaviour |
|---|---|---|
| `task etl/customers/sync.yaml` | `ShellCriterion` | QA runs `task etl/customers/sync.yaml`, asserts exit code 0 |
| `ruff check .` | `ShellCriterion` | idem |
| `mypy --no-incremental` | `ShellCriterion` | idem |
| `pytest tests/loaders/test_csv.py -v` | `ShellCriterion` | idem |
| `pylint parrot/` | `ShellCriterion` | idem |
| `The customer count must equal 1500 after a sync of a 1500-row CSV` | `ManualCriterion` | text only — attached to the Jira ticket; QA auto-passes; human reviewer signs off |

Allowed shell heads (configurable via `ACCEPTANCE_CRITERION_ALLOWLIST`):
`task`, `flowtask`, `pytest`, `ruff`, `mypy`, `pylint`. Lines that don't
start with one of those are treated as manual criteria — there is no
"unknown command" error any more.

##### How do I syntax-check a Flowtask YAML?

The `task` binary doesn't expose a `--check` / `--syntax` flag, so pick
one of:

1. **Pytest fixture (preferred)** — write a tiny test that loads the
   YAML and asserts it parses + every component class resolves, then add
   `pytest tests/etl/test_yaml_syntax.py::test_customers_sync` as a
   shell criterion.
2. **Manual criterion** — drop a sentence like
   `The etl/customers/sync.yaml file parses cleanly and references existing components`
   in the textarea; it lands in the Jira description for the reviewer
   to verify.
3. **Run the task in dry mode** — `task -p <program> -t <task> --no-worker`
   still executes, so this is only safe if your task is idempotent /
   side-effect-free.

Common gotchas:

* **Trailing colon on the head is tolerated** (`task: foo.yaml` parses
  the same as `task foo.yaml`), but the canonical form has no colon.
* **No shell pipes / redirections**: QA runs commands via
  `subprocess.exec` with the args split as a list, not `shell=True`. To
  compose pipelines, write a wrapper script and invoke it via an
  allowlisted head (e.g. `pytest scripts/check_pipeline.py`).
* If you need a `FlowtaskCriterion` with a specific `task_path` /
  structured `args` array, post the full criterion dict via curl.

## Stream layout (for reference)

```
flow:{run_id}:flow                       ← BugIntake + DeploymentHandoff + flow events
flow:{run_id}:dispatch:research          ← every Claude Code event for the Research dispatch
flow:{run_id}:dispatch:development       ← idem for Development
flow:{run_id}:dispatch:qa                ← idem for QA
```

The multiplexer (`parrot.flows.dev_loop.streaming.FlowStreamMultiplexer`)
fans those in by timestamp, filters on `?view=`, and emits flat envelopes
the UI consumes verbatim:

```json
{"source": "dispatch", "node_id": "qa",
 "event_kind": "dispatch.completed",
 "ts": 1714388261.42, "payload": {"output_model": "QAReport", ...}}
```

## Troubleshooting

* **UI stuck on "idle"** → check the server logs; `BugIntakeNode` raises
  `ValueError` on disallowed `ShellCriterion.command` heads
  (`ACCEPTANCE_CRITERION_ALLOWLIST` defaults to
  `flowtask, pytest, ruff, mypy, pylint`).
* **`DispatchExecutionError: cwd outside WORKTREE_BASE_PATH`** →
  R4 in the spec. Either set `WORKTREE_BASE_PATH` to the parent of the
  worktree the `ResearchNode` returned, or let the default
  `.claude/worktrees` stand and don't override `worktree_path`.
* **`gh: command not found`** → install + `gh auth login` before hitting
  `DeploymentHandoffNode`.
* **`SDK timeout`** → bump `ClaudeCodeDispatchProfile.timeout_seconds`
  (default 1800s) in the per-node profiles inside the corresponding
  `parrot/flows/dev_loop/nodes/*.py`.
