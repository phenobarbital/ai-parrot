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
├── server.py          ← OPERATIONS console: bug/enhancement/new_feature + feature
├── server_dev.py      ← DEVELOPMENT console: the dev-flow (FEAT-412), port 8081
└── static/
    ├── index.html     ← operations UI (served by server.py)
    └── dev.html       ← development UI with the HITL panel (served by server_dev.py)
```

**Two consoles, two audiences** (FEAT-412). They share Redis, the streaming
layer and the artifact conventions, and they can run side by side:

| | `server.py` + `index.html` | `server_dev.py` + `dev.html` |
|---|---|---|
| For | operating: bugs, log triage, ticketed work | developing: turning an idea into a PR |
| Port | 8080 | **8081** |
| Intake | summary + affected component + log sources | natural language, or an SDD document |
| CloudWatch | yes | **never wired** |
| Jira | required for bug runs | optional, link-only |
| HITL | read-only gate audit trail | **interactive** — answers gates from the browser |

See **Development console** below.

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
| `DEV_LOOP_LOG_FETCH_MODE` (default `auto`) | When `ResearchNode` may query a **remote** log backend (CloudWatch/Elasticsearch): `auto` = bug runs only, `always` = every work kind, `never` = disabled. Local `inline`/`attached_file` sources are never gated. The UI also stops attaching a CloudWatch source at all for non-bug kinds. |
| `DEV_LOOP_CLOUDWATCH_ENABLED` (default `true`) | Server-wide CloudWatch kill switch. `false` stops the console building a `CloudWatchToolkit` at all **and** stops it attaching a `cloudwatch` source to a bug brief — the local-laptop case, where the query is pure latency and a guaranteed credential error. Orthogonal to `DEV_LOOP_LOG_FETCH_MODE` (which work kinds may fetch) — this one is whether CloudWatch exists. A single run can also opt out with the request form's **Skip CloudWatch for this run** toggle (`skip_cloudwatch` on the payload). |
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

## Development console — `server_dev.py` + `static/dev.html` (FEAT-412)

```bash
source .venv/bin/activate
python examples/dev_loop/server_dev.py
# open http://localhost:8081        (PORT / HOST / REDIS_URL env still win)
```

Redis is the only hard requirement. **No `CLOUDWATCH_*` and no `JIRA_*` env is
needed** — the dev-flow wires no log toolkits at all, and Jira is link-only:
when `JIRA_INSTANCE`/`JIRA_USERNAME` are unset the server logs one line and
runs with `jira_toolkit=None`.

Because the port differs, this console runs **alongside** the operations one
(8080) against the same Redis.

### The topology

```
dev_intake ─(enhancement | new_feature)→ ideation ─┐
     └──────(feature)──────────────────────────────┤
                                                   ▼
planner → development → synthesis → qa ─(passed)→ feature_handoff → close
                ↑                    │                  ▲   (draft PR)
                └─(retry, bounded)───┤                  │
                                     ▼                  │
                              feedback_router ──(accept_with_notes)
                                     ├─(escalate)→ failure_handler
                          (+ on_error fan-in from every middle node)
```

Everything from `planner` onward behaves exactly like the feature-mode chain —
same node types, same predicates, same bounded repair loop. Only the intake is
new. The run always ends at a **draft PR against `dev`**; the flow never
merges.

### The three intents

The intent is a **user choice in the UI** — there is no LLM classification
anywhere in this flow.

| Intent | Intake | Ideation writes | Then |
|---|---|---|---|
| `enhancement` | natural language (`title` + `description`) | `sdd/proposals/<slug>.proposal.md` — a **light** proposal: scope, rationale, impact, open questions (no options analysis) | planner → … |
| `new_feature` | natural language (`title` + `description`) | `sdd/proposals/<slug>.brainstorm.md` — a **full** brainstorm: options A/B/C + a recommendation | planner → … |
| `feature` | an existing SDD document (`document_path` + `document_kind`) | *nothing — ideation is skipped by routing* | planner → … |

`title` is the slug source. **If the target document already exists it is
resumed and extended in place** — never overwritten, never `-2`-suffixed. The
resolved path is shown in the gate title so you can spot (and reject) an
unintended reuse; if the existing document is clearly about something else the
subagent refuses to touch it and returns the collision as an open question.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves `static/dev.html` |
| `/api/config` | GET | Backends/models catalog, the three intents, `document_kinds`, `nl_kinds`, `gate_resolve_url_template`, and the dev defaults (`ideation_max_rounds`, `gate_ttl_questions`, `require_plan_approval`, `qa_max_retries`, `development_pool_max`, `max_concurrent_runs`, …). Carries **no** `log_group`, `time_window_minutes` or `jira_project`. |
| `/api/flow/run` | POST | Start (or **resume**) a run. Body per the intent (below); an optional `run_id` resumes that run. Returns `run_id`, `resume` (null for a fresh run), `mode`, `kind`, `ws_url`, `state_ws_url`, `bundle_url`, `gate_resolve_url`, the effective `model_plan`, and `model_plan_ignored` — one `field: requested=… effective=…` line per submitted seat the server is not honouring (empty when every expressed seat matches). |
| `/api/flow/{run_id}/checkpoint` | GET | **Is this run resumable?** Read-only probe: `found`, `status`, `checkpoint_id`, `completed_nodes`, `active`, plus a `reason`/`help` pair. `resumable` is `null` here — with no brief to fingerprint the answer is *unknown*, not *no*. |
| `/api/flow/{run_id}/gates/{gate_id}/resolve` | POST | **The HITL write path** — resolve a gate. `server.py` never mounts this. |
| `/api/flow/{run_id}/cancel` | POST | Cancel a run |
| `/api/flow/{run_id}/ws` | GET | `flow_stream_ws` — `?view=flow\|dispatch\|both\|state` |
| `/api/flow/{run_id}/bundle` | GET | Finished run's bundle (`?format=md` for the report) |
| `/api/flow/{run_id}/replay` | GET | JSON dump of stored events |

### Run payloads

Natural language (`enhancement` / `new_feature`):

```bash
curl -X POST http://localhost:8081/api/flow/run \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "new_feature",
    "title": "compression budget telemetry",
    "description": "Add per-tool telemetry to the compression budget so operators can see which tool blew the budget.",
    "context": "See PR #1204 for the original budget work.",
    "require_plan_approval": true
  }'
```

`title` and `description` are required; everything else is optional. There is
**no** `affected_component`, `log_sources`, `acceptance_criteria`, `reporter`
or `escalation_assignee` — those are bug-intake concepts.

Existing document (`feature`) — identical to the ops console's feature payload:

```bash
curl -X POST http://localhost:8081/api/flow/run \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "feature",
    "document_path": "sdd/proposals/my-feature.brainstorm.md",
    "document_kind": "brainstorm"
  }'
```

Optional in both shapes: `jira_issue_key` (link-only), `dev_agents`,
`judge_panel`, `skip_qa`, `skip_jira`, `require_plan_approval`.

### Resuming an interrupted run (FEAT-480)

A dev-flow run checkpoints after every node. Pass the original `run_id` back
and the work already done — `dev_intake`, `ideation` (including the answered
open questions), `planner` and the worktree/spec/task-index it created — is
**restored instead of re-dispatched**; execution picks up at the first node
that never completed.

```bash
# 1. Is the run still recoverable? (24h Redis TTL by default)
curl -s http://localhost:8081/api/flow/run-3f9a1c02/checkpoint | jq
# {"found": true, "status": "running", "checkpoint_id": 7,
#  "completed_nodes": ["dev_intake", "ideation", "planner"], "resumable": null, ...}

# 2. Resume it — SAME brief as the original run, plus its run_id.
curl -X POST http://localhost:8081/api/flow/run \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "feature",
    "document_path": "sdd/proposals/my-feature.brainstorm.md",
    "document_kind": "brainstorm",
    "run_id": "run-3f9a1c02"
  }'
```

In the console the same thing is the **"Resume a run — run_id"** field in
section 01, with a *Check* button that calls the probe above.

Rules worth knowing before you rely on it:

* **The brief must be identical.** Resume is gated by a SHA-256 fingerprint
  over the normalized brief (kind, title/description or document_path/
  document_kind, context, jira_issue_key, dev_agents, judge_panel), the
  topology version and the server's routing policy (`skip_qa`,
  `require_plan_approval`, `development_pool_max`, `ideation_max_rounds`, the
  model plan's pool shape/review backend). Change any of it and the server
  answers **409 `fingerprint_mismatch`** rather than silently starting over.
  A natural-language run cannot be resumed by pointing at the document its
  ideation produced — that is a *different* brief; re-post the original
  `title`/`description`.
* **An unknown or expired `run_id` is a 409, never a fresh run.** Checkpoints
  live in the ephemeral Redis tier for `FLOW_CHECKPOINT_REDIS_TTL` (24h);
  after that the run is gone.
* **The worktree must still be there.** A restored `planner_output` is
  validated against the real repo (registered worktree, expected branch, spec
  and task-index files present). If it moved, the run fails with a
  `RecoveredArtifactError` naming what is missing.
* Resume needs a server started with recovery wiring
  (`defaults.recovery_enabled` in `/api/config`); the console hides the field
  when it is false.

### The `open_questions` gate protocol

Ideation is **interactive and bounded**. Per round:

1. `IdeationNode` dispatches `sdd-ideation`, which writes/extends the document
   and reports the questions it still needs answered.
2. If there are any, the node opens **ONE gate carrying ALL of that round's
   questions** (`kind="open_questions"`, `questions=[...]`) and awaits it. The
   run **parks** while waiting (`DEV_LOOP_GATE_PARK`), so it releases its
   concurrency slot and a human can take hours.
3. `dev.html` receives `gate/opened` on the state WebSocket and renders one
   input per question. It renders from the folded **state**, not from the live
   action alone — so reloading the page mid-gate re-renders the pending gate.
4. You submit; the answers ride the next dispatch, and the subagent marks each
   answered question `- [x] <question> — *Resolved*: <answer>` in the document
   (the convention `/sdd-spec` §2b consumes) and folds the decision into the
   body.
5. A re-dispatch may surface new questions → a new gate, bounded by
   `DEV_FLOW_IDEATION_MAX_ROUNDS`. When the budget is spent, anything still
   `[ ]` **stays in the document and is carried into the spec's §8 by the
   planner** — it does not block the run.

**Partial answers are fine** — blanks stay open. **Rejecting aborts** the
ideation and routes the run to `failure_handler`. **Expiry is fail-closed**:
an unanswered gate expires the run into the failure path, because silence is
not consent for spec decisions.

Resolving a gate from the CLI (the same call the browser makes):

```bash
curl -X POST http://localhost:8081/api/flow/run-1a2b3c4d/gates/9f8e7d6c/resolve \
  -H 'Content-Type: application/json' \
  -d '{
    "resolution": "approved",
    "resolved_by": "jesus",
    "comment": "answered round 1",
    "answers": {
      "Which store backs the telemetry?": "pgvector",
      "Sync or async flush?": "async"
    }
  }'
```

Responses: `200` with the sequenced envelope · `400 invalid_body` ·
`400 answers_required` (approving an `open_questions` gate with no answers —
use `"resolution": "rejected"` to abort instead) · `404 unknown_run` /
`unknown_gate` · `409 already_resolved` (first writer wins, and the body names
who won). To abort:

```bash
curl -X POST http://localhost:8081/api/flow/run-1a2b3c4d/gates/9f8e7d6c/resolve \
  -H 'Content-Type: application/json' \
  -d '{"resolution": "rejected", "resolved_by": "jesus", "comment": "wrong document"}'
```

The same panel handles a `plan_approval` gate (approve/reject + comment, no
answer inputs) when you tick **Require plan approval** — see below.

### Per-run plan-approval gate

`dev.html`'s *Ideation & gates* tab has a **Require plan approval** toggle.
Ticking it sends `require_plan_approval: true`, which the server forwards as
`extra_shared["require_plan_approval"]`; `DevelopmentNode` honours that per-run
value **over** its build-time flag, so no flow rebuild is needed. An explicit
`false` suppresses a gate the server was built with; omitting the field leaves
the build-time default alone. The resulting gate opens after the planner and
before the dev-agent fleet dispatches.

### Per-seat LLM selectors (FEAT-486)

Every LLM-facing seat in the dev-flow is selectable. The console ships
opinionated defaults and exposes three selector groups plus one toggle:

| Selector group | Tab | Console default |
|---|---|---|
| Research primary model | *Ideation & gates* | `claude-opus-5` |
| Research partner (enable + backend + model) | *Ideation & gates* | **off**; `gpt` / `gpt-5.6-sol` when enabled |
| Development agent pool | *Agents & models* | `nova:zai.glm-5` + `nova:qwen.qwen3-coder-480b-a35b-v1:0` (both Bedrock, via `bedrock-mantle`) |
| Adversarial review pair | *Review & judges* | `claude-code`/`claude-opus-5` primary + `gpt-5.6-sol` counter-reviewer |

`GET /api/config` carries the server's **resolved** plan under
`defaults.model_plan`, so the UI shows what will really run rather than
what the source hardcodes. `POST /api/flow/run` accepts the same shape
back (`dev_agents`, `research_primary`, `research_partner`, `review`).

**Backends are validated strictly; models are free text.** An unknown
backend is a `400` naming every supported backend. A typo'd model surfaces
as a provider error on that seat — model lists are a curated suggestion,
never a whitelist.

Two behaviours worth knowing:

* **A single-`TASK-` feature collapses to one sub-agent**, whatever pool
  you declare. The task count is the signal; there is no flag.
* **NVIDIA NIM stays selectable but is never a default.** It currently
  returns `401 Unauthorized` for this account, so defaulting to it would
  break every run. `kimi-k3` is reachable via the `moonshot` backend, not
  via NIM.

> **Two things worth knowing, stated plainly.**
> 1. **`model_plan` is per-run (FEAT-490).** Every seat — ideation model,
>    review pair, and the development pool — takes effect for a single
>    submitted run, with no server restart. A submitted plan is fully
>    validated and echoed back in the run response as the plan that will
>    REALLY run. **The one case that does not apply a new submission is a
>    resume**: `POST /api/flow/run` with an explicit `run_id` that
>    preflights as resumable continues that run on the seats it was
>    created with (a resumed run's completed nodes already ran under
>    them — adopting a different plan mid-history would make the run
>    self-contradictory). A submission that differs from a resumed run's
>    seats is still fully validated and echoed back, and any difference is
>    logged as a warning — **field by field**, naming each seat, and only
>    for fields the console actually expressed (a blank input means
>    "keep the resumed run's seat", never an ignored choice) — and
>    returned as `model_plan_ignored` for the UI banner. Start a fresh run
>    (omit `run_id`) to use a different plan.
> 2. By default this console wires the FEAT-378 **judge panel** as its QA
>    reviewer, and an explicit reviewer wins over the plan by design. The
>    review pair is therefore configured and validated but not the active
>    reviewer — `defaults.model_plan.review_pair_active` reports this as
>    `false`, and the UI says so. Set `DEV_FLOW_USE_REVIEW_PAIR=true` to
>    drop the judge panel and let the plan assemble its review pair
>    (primary + Mantle counter-reviewer) as the active QA reviewer.

See `docs/dev_loop/dev-flow-model-plan.md` for the full reference.

### New configuration keys

| Key | Default | Meaning |
|---|---|---|
| `DEV_FLOW_IDEATION_MAX_ROUNDS` | `2` | Max Open-Questions HITL rounds (gates) per run. Leftover questions are carried into the spec, never re-asked forever. |
| `DEV_FLOW_GATE_TTL_QUESTIONS` | `86400` (24 h) | TTL for an `open_questions` gate. **Fail-closed** — expiry routes the run to `failure_handler`. |
| `DEV_FLOW_IDEATION_MODEL` | `claude-opus-5` | Research-primary seat model (FEAT-486; shared with FEAT-482). |
| `DEV_FLOW_DEV_POOL` | *(unset)* | Dev pool as a JSON array of `{agent, model, count}`. Only read when a `model_plan` is supplied. |
| `DEV_FLOW_RESEARCH_PARTNER` | `""` (disabled) | Complementary research partner (FEAT-482): `""` disables the seat, otherwise the backend — `gpt` or `nova`. Enable **and** backend in one key. |
| `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` / `_NOVA_MODEL` | `gpt-5.6-sol` / `us.amazon.nova-2-lite-v1:0` | Partner model, **per backend**. FEAT-486's `_ENABLED`/`_BACKEND`/`_MODEL` keys were retired by FEAT-487 and are inert. |
| `DEV_FLOW_REVIEW_PRIMARY_BACKEND` / `_MODEL` | `claude-code` / `claude-opus-5` | Write-enabled primary reviewer. |
| `DEV_FLOW_REVIEW_COUNTER_MODEL` | `gpt-5.6-sol` | Read-only counter-reviewer, over Bedrock Mantle. |
| `DEV_LOOP_MANTLE_REVIEW_MODEL` | `gpt-5.6-sol` | The Mantle counter-reviewer's own model key. Distinct from `DEV_LOOP_ADVERSARIAL_MODEL` (the codex seat's). Also used when `DEV_LOOP_ADVERSARIAL_BACKEND=mantle` selects the `mantle-adversarial` reviewer in the ops console. |
| `DEV_FLOW_USE_REVIEW_PAIR` | `false` | Dev console only: replace the judge panel with the model plan's review pair as the active QA reviewer. |
| `DEV_LOOP_LLM_MAX_TURNS` | `60` | Turn budget for the **in-process** coding loop (`nvidia`, `nova`, `zai`, `moonshot`, `grok`). One turn is one chat completion, so a real SDD task needs far more than the profile's conservative library default of 24. The agentic CLIs (`claude-code`, `codex`, `gemini`, `google_coding`) run their own loop and ignore this. When the budget runs out, the dispatcher spends one extra round with `tool_choice` forced to `final_output` to recover work already committed; a dispatch that then declares its own task in `incomplete_tasks` is still treated as failed and retried. |
| `DEV_LOOP_RESEARCH_MCP_ENABLED` | `true` | Kill switch for the research seats' MCP wiring (both consoles) — see the FEAT-484/485 section below. |
| `DEV_LOOP_RESEARCH_MCP_TOOLKITS` | `auto` | Which `.parrot/mcp-toolkits.yaml` sections to serve to the research seats (`auto` = the sections declared in the file). |
| `NOVA_CODE_MAX_CONCURRENT_DISPATCHES` | `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` | Concurrency cap when `DEV_LOOP_DEVELOPMENT_AGENT=nova`. |

Everything else is reused unchanged from the existing `DEV_LOOP_*` keys
(`DEV_LOOP_QA_MAX_RETRIES`, `DEV_LOOP_GATE_PARK`, `DEV_LOOP_JUDGE_PANEL`,
`DEV_LOOP_DEV_AGENTS`, `DEV_LOOP_DEV_POOL_MAX`, `DEV_LOOP_REPOS`,
`DEV_LOOP_DOCS_ARTIFACT_DIR`, `FLOW_MAX_CONCURRENT_RUNS`, …) — the dev-flow
deliberately does not fork the shared knobs.
`DEV_LOOP_REQUIRE_PLAN_APPROVAL` still sets the server-wide default that the
per-run toggle overrides.

### Not exposed

Revision mode (`DevLoopRunner.run_revision`) is a library/`e2e_demo` feature
and is not served by either console.

## Research-seat MCP access (FEAT-484/485)

Both consoles hand the dispatched **research agents** an explicit MCP
surface (built by the sibling module `mcp_wiring.py` at startup):

* **`wikitoolkit` graph search** (FEAT-403) — the read-only trio
  `wiki_query` / `wiki_page` / `wiki_related`. In the ops console this
  reaches `ResearchNode`'s `sdd-research` dispatch; the dev console's
  `IdeationNode` already ships it built in.
* **FEAT-485 local toolkit servers** — every section declared in
  `<repo>/.parrot/mcp-toolkits.yaml` is served as `parrot mcp-local
  <name>` and exposed to the research seats. Copy
  `mcp-toolkits.example.yaml` to get a `repo` section exposing the
  FEAT-484 **`ReadOnlyRepoToolkit`** (confined, strictly read-only
  repository access: `search_code`, `read_file`, `grep_files`,
  `git_log`/`git_show`/`git_blame`, opt-in `web_search`).

Because these dispatches run with `strict_mcp_config=True` (the headless
CLI ignores the filesystem `.mcp.json`), the servers are passed explicitly
on the dispatch profile, and each server entry carries
`--config <abs path>` so `parrot mcp-local` finds the YAML even though the
research dispatch cwd is `WORKTREE_BASE_PATH`, not the repo root. Use an
**absolute** `repo_root` in the YAML for the same reason.

Everything degrades gracefully: a missing `wikitoolkit` binary, a missing
or invalid YAML, or an unknown section name logs a warning and serves
whatever subset resolves. `DEV_LOOP_RESEARCH_MCP_ENABLED=false` turns the
whole wiring off; `DEV_LOOP_RESEARCH_MCP_TOOLKITS=repo,memory` pins an
explicit section list (which may include the built-ins
`scraping`/`browsing`/`memory` — mind their optional extras).

Related (FEAT-482/486): the ops console now also honours
`DEV_FLOW_RESEARCH_PARTNER_ENABLED` / `_BACKEND` / `_MODEL` for
`ResearchNode`'s collaborative-research partner — the partner itself uses
`ReadOnlyRepoToolkit` natively, no MCP required. The env pool
(`DEV_LOOP_DEV_AGENTS`) now also reaches the ops console's **feature**
topology, so `PlannerNode` suggests the operator's real backends there
too.

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
