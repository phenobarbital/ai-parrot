# Dev-Loop Orchestration — Examples (FEAT-129 + FEAT-132 + FEAT-250)

> **FEAT-132 upgrades** (2026-04-28): The flow now starts with an
> `IntentClassifierNode` that validates the incoming brief and routes
> by `WorkBrief.kind`: `"bug"` briefs go through `BugIntakeNode` before
> Research; `"enhancement"` and `"new_feature"` briefs skip directly to
> `ResearchNode`. The Jira issuetype is now derived from the kind field
> (Bug / Story / New Feature). A plan-summary comment is posted on newly
> created tickets. See **Routing by kind** below.
>
> **FEAT-250 upgrades**: the flow gained a terminal **`CloseNode`** (closes
> out the run / transitions Jira), the QA node now runs an additional
> **code-review gate** (`sdd-codereview`) on top of the deterministic
> criteria, `DeploymentHandoffNode` opens the PR as a **draft**, the clone
> is **provisioned before Development**, and there is a separate
> **revision-mode** run (`DevLoopRunner.run_revision`) that updates an
> existing PR instead of opening a new one. See **What FEAT-250 changed**
> below.

Runnable examples for the eight-node `AgentsFlow`
(`IntentClassifier → [BugIntake →] Research → Development → QA →
DeploymentHandoff → Close`, with a `FailureHandler` `on_error` fan-in)
defined in `sdd/specs/dev-loop-orchestration.spec.md` and implemented
under `parrot/flows/dev_loop/`.

```
examples/dev_loop/
├── README.md          ← this file
├── e2e_demo.py        ← self-contained end-to-end demo (no external services)
├── quickstart.py      ← real-mode programmatic example (no UI)
├── server.py          ← aiohttp server: real flow + WS multiplexer
└── static/
    └── index.html     ← vanilla-JS UI client (no build step)
```

Both real-mode entry points wire the **real** flow — no fakes, no stubs.
They differ only in how the run is triggered: `quickstart.py` runs the brief
through `DevLoopRunner` once and exits; `server.py` exposes an HTTP +
WebSocket surface so the UI client can start runs and visualise the merged
event stream live.

## Setup — running from a clean checkout

This repository is a **`uv` workspace** (`[tool.uv.workspace]` in the root
`pyproject.toml`). One sync installs every member package editable, with all
transitive dependencies, into `.venv`:

```bash
uv sync                       # creates .venv + installs the workspace
source .venv/bin/activate
python examples/dev_loop/e2e_demo.py
```

That is **all** `e2e_demo.py` needs — it imports only `parrot.*` and simulates
every external service in-process (no Redis, `claude` CLI, Jira, or API keys).

For the **real-mode** scripts (`quickstart.py` / `server.py`) you additionally
need:

* the **`jira`** package — `parrot_tools.jiratoolkit.JiraToolkit` imports it
  lazily and raises `ImportError: Please install the 'jira' package` otherwise:
  ```bash
  uv pip install jira
  ```
* a running **Redis** and the credentials listed in **Prerequisites (real
  mode)** below.

> **Note:** a couple of direct imports (`tenacity`, `tqdm`) are currently
> satisfied transitively rather than being declared in `ai-parrot`'s
> `pyproject.toml`. `uv sync` resolves them from the lockfile, so a normal
> workspace sync works; this is only a concern if you install `ai-parrot`
> standalone outside the workspace.

## Zero-dependency demo — `e2e_demo.py`

The fastest way to see the whole flow working. It executes the REAL engine
(`AgentsFlow` scheduler, OR-join routing, `DevLoopRunner` semaphore, FEAT-176
lifecycle telemetry) end-to-end, but every external service is simulated
in-process: the Claude Code dispatcher returns canned subagent outputs, Jira
calls are recorded in memory, Redis XADDs are captured by a fake client, and
`git push` / `gh pr create` are no-ops returning a fake PR URL.

**No Redis, no `claude` CLI, no Jira, no API keys.**

```bash
source .venv/bin/activate
python examples/dev_loop/e2e_demo.py
```

It runs six scenarios and prints, for each: executed/failed/skipped nodes,
the `FlowResult`, the simulated Jira audit trail, the captured
`flow:{run_id}:flow` stream events, and the typed FEAT-176 lifecycle event
timeline (one trace per run, per-node durations):

1. **Bug, happy path** — `IntentClassifier → BugIntake → Research →
   Development → QA → DeploymentHandoff → Close`; `failure_handler`
   skip-propagated; draft PR opened + `Close` transitions Jira.
2. **Enhancement** — `bug_intake` is skip-propagated (kind routing).
3. **QA fails (deterministic)** — `deployment_handoff` + `close` skipped;
   escalation comment + "Needs Human Review" + reassignment.
4. **Hard error in Development** — the `on_error` fan-in fires
   `failure_handler`; `qa`/`deployment_handoff`/`close` are skipped; status
   `partial`.
5. **Code-review fails (FEAT-250 gate)** — the deterministic criteria pass
   but the `sdd-codereview` verdict fails, so the QA gate
   (`passed = deterministic AND code_review`) blocks: `deployment_handoff` +
   `close` skipped, escalation via `failure_handler`.
6. **Revision mode (FEAT-250 G6)** — `DevLoopRunner.run_revision(RevisionBrief)`
   runs the short flow `development → qa → revision_handoff → close`. The
   `RevisionHandoffNode` pushes the **existing** branch and comments the
   **same** PR (`add_pr_comment`) — it never opens a new PR — and `Close`
   runs in `mode="revision"`.

Use it as a template for wiring the flow into your own harness: everything
specific to the simulation lives in the `Simulated*`/`Fake*` classes
(`SimulatedDispatcher`, `SimulatedJira`, `SimulatedGit`, `FakeRedis`,
`FakeLLM`).

## Prerequisites (real mode)

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

## Routing by kind

`FEAT-132` introduces `IntentClassifierNode` as the flow entry point. It
validates the brief and routes execution based on `WorkBrief.kind`:

```
 WorkBrief.kind
      │
      ├─ "bug"          ─► IntentClassifier ─► BugIntake ─► Research ─► ...
      │
      └─ "enhancement"  ─►
         "new_feature"  ─► IntentClassifier ──────────────► Research ─► ...
```

The Jira issuetype is derived from the kind:

| `kind` | Jira issuetype |
|---|---|
| `bug` (default) | Bug |
| `enhancement` | Story |
| `new_feature` | New Feature |

Additionally, when a **new** ticket is created (not reused), `ResearchNode`
posts a plan-summary as the first Jira comment. The LLM used for plan
generation is controlled by `DEV_LOOP_PLAN_LLM` (see Prerequisites table).
On the **reuse** path (`existing_issue_key` is set), no plan-summary comment
is posted — only the standard re-trigger comment.

## What FEAT-250 changed

The flow topology and QA gate were extended after FEAT-132. The examples
exercise all of it:

* **Terminal `CloseNode`** — runs after `DeploymentHandoff` (initial path) or
  `RevisionHandoff` (revision path) and finalises the run. Its output carries
  a `mode` field (`"initial"` vs `"revision"`). On failure/QA-fail paths it is
  skipped and `FailureHandler` runs instead.
* **Code-review QA gate** — `QANode` now dispatches an `sdd-codereview`
  subagent in addition to the deterministic `sdd-qa` run. The report's
  `passed` is `deterministic_passed AND code_review_passed`, so a qualitative
  review failure blocks deployment even when every executable criterion
  passes. The verdict is backward-tolerant: a dispatch error is treated as a
  pass so an infra hiccup never blocks the flow (the deterministic gate is the
  hard guarantee; code-review is additive). Scenario 5 in `e2e_demo.py`
  demonstrates the blocking case.
* **Draft PR** — `DeploymentHandoffNode` opens the PR as a draft.
* **Repo provisioning before Development** — the clone is provisioned ahead of
  the Development node rather than inside Research.
* **Revision mode** — `DevLoopRunner.run_revision(RevisionBrief)` builds a
  short flow (`development → qa → revision_handoff → close`) that reuses an
  existing clone + branch + open PR. `RevisionHandoffNode` pushes the existing
  branch and comments the same PR via `git_toolkit.add_pr_comment(...)`; it
  never opens a new PR. To use it, construct the runner with the revision
  dependencies:

  ```python
  runner = DevLoopRunner(
      flow,
      dispatcher=dispatcher,
      jira_toolkit=jira_toolkit,
      git_toolkit=git_toolkit,   # exposes async add_pr_comment(pr_number, body)
      redis_url=redis_url,
  )
  result = await runner.run_revision(
      RevisionBrief(
          repo_path="…",          # existing clone (the Development node's cwd)
          branch="feat-999-…",     # existing feature branch
          pr_number=4242,          # the open draft PR to update
          repository="owner/name",
          jira_issue_key="NAV-1",
          feedback="reviewer comment to act on",
          head_sha="…",            # head SHA at trigger time (dedup)
      )
  )
  ```

  Scenario 6 in `e2e_demo.py` runs this end-to-end with simulated I/O.

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

* Eight panels, one per node (IntentClassifier, BugIntake, Research,
  Development, QA, Handoff, Close, Failure), with status pills
  (`idle / queued / running / passed / failed`). The Close and Failure
  panels are driven by the flow-level `flow.node_started` /
  `flow.node_completed` envelopes (those nodes aren't dispatched, so they
  emit no `dispatch.*` events).
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
    "time_window_minutes": 90,
    "existing_issue_key": "NAV-8241"
  }'
```

Omit `existing_issue_key` to auto-detect duplicates or create a new ticket.
Set it to force re-use of a specific Jira issue — Research will append a
re-triggered comment instead of opening a new one, and no plan-summary
comment will be posted (the plan was already commented when the ticket was
first created).

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

* **UI stuck on "idle"** → check the server logs; `IntentClassifierNode` raises
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
