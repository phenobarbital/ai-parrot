---
type: feature
base_branch: dev
---

# Feature Specification: `parrot devloop` CLI Homologation v2 — skip flags, doc shortcut, feature-flow pre-build, usage report

**Feature ID**: FEAT-409
**Date**: 2026-08-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x (next)

---

## 1. Motivation & Business Requirements

### Problem Statement

The `parrot devloop` CLI console (`packages/ai-parrot/src/parrot/cli/devloop/`)
was homologated with the web console (`examples/dev_loop/server.py`) in
FEAT-388, covering the feature-mode wizard, free-text intake, and multi-backend
dev-agent pool. Since then, the dev-loop flow has gained several capabilities
that the web console (`server.py`) already exposes but the CLI does not:

1. **`skip_jira` / `skip_qa` bypass** — `server.py` accepts these in the form
   payload and passes them as `extra_shared` to `runner.run()`. The CLI has no
   flags for this and does not pass `extra_shared` at all.

2. **SDD document shortcut** — `server.py` accepts `document_path` +
   `document_kind` directly in the form to create a `FeatureBrief` from an
   existing SDD markdown (brainstorm, proposal, or spec). The CLI can only do
   this via `--brief feature.yaml` with a handcrafted YAML — no direct flag.

3. **Feature-mode flow full wiring** — `server.py` pre-builds the feature
   flow via `build_dev_loop_feature_flow(...)` with `dispatcher_builder`,
   `pool_max`, `skip_qa`, `require_plan_approval`, and seeds it into
   `runner._feature_flow`. The CLI only builds the bug-mode flow; the runner
   lazy-builds the feature flow with thin defaults (no dispatcher builder, no
   pool max from config, no `skip_qa`, no `require_plan_approval`).

4. **Usage report** — `usage_report.py` (`UsageReport`, `build_usage_report`,
   `render_usage_markdown`) exists and the runner persists `.usage.json` to
   disk after every run. Neither the CLI auto-displays this nor offers a
   command to view it.

### Goals

- Add `--skip-jira` and `--skip-qa` flags, wired through `extra_shared`.
- Add `--doc PATH` / `--doc-kind KIND` flags to create a `FeatureBrief`
  directly from an SDD markdown, with suffix-based kind inference.
- Pre-build the feature-mode flow in `build_runtime()` with full wiring.
- Auto-display the usage report after every run; add `/usage` slash command.
- Add `--no-usage` flag to suppress auto-display.

### Non-Goals (explicitly out of scope)

- Nova adversarial backend selection (`DEV_LOOP_ADVERSARIAL_BACKEND`) — follow-up.
- Full adversarial/parallel code-review upgrade in the CLI — follow-up.
- Wiki toolkit wiring for feature-mode handoff — follow-up.
- Git toolkit / `DEV_LOOP_REPOS` multi-repo targeting — follow-up.
- Run bundle display/download — follow-up.
- Changes to `runner.py`, `usage_report.py`, `intake.py`, or `server.py`.

---

## 2. Architectural Design

### Overview

Five incremental modules, all touching the CLI layer only (no flow-engine
changes). The runner already supports `extra_shared`, `_feature_flow`
pre-seeding, and persists `.usage.json` to disk — the CLI simply needs to
surface these capabilities.

### Component Diagram

```
parrot devloop run --skip-jira --doc spec.md --no-usage
       │
       ▼
  __init__.py          ← new flags, _infer_doc_kind(), mutual exclusion
       │
       ▼
  console.py           ← start() new kwargs, _dispatch_initial doc route,
       │                  _dispatch_run extra_shared, post-run usage display,
       │                  _cmd_usage handler
       ▼
  bootstrap.py         ← build_runtime() pre-builds feature flow,
       │                  reads DEV_LOOP_SKIP_QA, passes skip_qa to
       │                  bug-mode flow, DevLoopRuntime.feature_flow_available
       ▼
  runner.run()         ← already accepts extra_shared, _feature_flow pre-seed
       │
       ▼
  .usage.json          ← already persisted by runner._persist_run_bundle()
       │
       ▼
  console.py           ← reads .usage.json, renders Rich Panel post-run
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevLoopRunner.run()` | consumes | Already accepts `extra_shared` kwarg |
| `DevLoopRunner._feature_flow` | pre-seeds | Private attr, same pattern as `server.py` |
| `build_dev_loop_feature_flow()` | calls | New import in `bootstrap.py` |
| `build_dev_loop_flow()` | passes `skip_qa` | Currently not passed from CLI bootstrap |
| `UsageReport` | reads from disk | `.usage.json` persisted by runner |
| `render_usage_markdown()` | calls | For Rich Panel display |
| `FeatureBrief` | constructs | Direct construction from `--doc` flag |
| `conf.OUTPUT_DIR` | reads | For `.usage.json` path resolution |

### Data Models

No new data models. Uses existing:

```python
# FeatureBrief — already exists (models/base.py:725)
FeatureBrief(
    document_path="sdd/specs/my-feature.spec.md",
    document_kind="spec",  # or inferred from suffix
    dev_agents=[...],      # optional, from --dev-agent flags
    judge_panel=None,      # optional
    jira_issue_key=None,   # optional
)
```

### New Public Interfaces

```python
# __init__.py — new utility function
def _infer_doc_kind(path: str) -> str:
    """Infer document_kind from filename suffix.

    .spec.md → "spec", .proposal.md → "proposal",
    .brainstorm.md → "brainstorm", default → "brainstorm".
    """
```

No new public classes. All changes are internal to the CLI package.

---

## 3. Module Breakdown

### Module 1: Click surface — new flags

- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/__init__.py`
- **Responsibility**: Add `--skip-jira`, `--skip-qa`, `--doc`, `--doc-kind`,
  `--no-usage` flags to `run_cmd`. Implement `_infer_doc_kind()`. Validate
  mutual exclusion of `--doc` / `--brief` / `--text`. Propagate new args to
  `console.start()`.
- **Depends on**: None.

### Module 2: Document shortcut route

- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
- **Responsibility**: `start()` accepts new kwargs (`skip_jira`, `skip_qa`,
  `doc_path`, `doc_kind`, `show_usage`). `_dispatch_initial` handles `--doc`
  route: constructs `FeatureBrief` directly, merges `--dev-agent` flags,
  bypasses wizard/intake entirely.
- **Depends on**: Module 1.

### Module 3: extra_shared wiring

- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
- **Responsibility**: `_dispatch_run` builds an `extra_shared` dict from
  `skip_jira`/`skip_qa` booleans and passes it to
  `runner.run(brief, run_id=run_id, extra_shared=extra_shared)`.
- **Depends on**: Module 1, Module 2.

### Module 4: Feature-mode flow pre-build

- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py`
- **Responsibility**: After building the bug-mode flow, pre-build the feature
  flow via `build_dev_loop_feature_flow(...)` with full wiring
  (`development_dispatcher_builder`, `development_pool_max`,
  `require_plan_approval`, `skip_qa`, `codereview_dispatcher`,
  `graph_memory`) and seed it into `runner._feature_flow`. Read
  `DEV_LOOP_SKIP_QA` from conf. Pass `skip_qa` to `build_dev_loop_flow()`
  (currently missing). Add `feature_flow_available: bool` to
  `DevLoopRuntime`. Graceful degradation on failure (warning, no crash).
- **Depends on**: None (independent of Modules 1-3).

### Module 5: Usage report display + `/usage` command

- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
- **Responsibility**: Auto-display usage report after run completion in
  `_interactive_loop` (reading from `.usage.json` persisted by the runner).
  Add `_cmd_usage` slash command handler. Controlled by `show_usage` bool
  (suppressed by `--no-usage`). Add to `/help` output.
- **Depends on**: Module 1 (for `--no-usage` flag), Module 3 (run must
  complete first).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_infer_doc_kind_spec` | 1 | `.spec.md` → `"spec"` |
| `test_infer_doc_kind_proposal` | 1 | `.proposal.md` → `"proposal"` |
| `test_infer_doc_kind_brainstorm` | 1 | `.brainstorm.md` → `"brainstorm"` |
| `test_infer_doc_kind_unknown` | 1 | `.md` (no known suffix) → `"brainstorm"` |
| `test_mutual_exclusion_doc_brief` | 1 | `--doc` + `--brief` → `UsageError` |
| `test_mutual_exclusion_doc_text` | 1 | `--doc` + `--text` → `UsageError` |
| `test_skip_jira_extra_shared` | 3 | `--skip-jira` → `extra_shared["skip_jira"] == True` |
| `test_skip_qa_extra_shared` | 3 | `--skip-qa` → `extra_shared["skip_qa"] == True` |
| `test_doc_creates_feature_brief` | 2 | `--doc spec.md` → `FeatureBrief(document_kind="spec")` |
| `test_doc_with_explicit_kind` | 2 | `--doc x.md --doc-kind proposal` → overrides inference |
| `test_doc_merges_dev_agents` | 2 | `--doc spec.md --dev-agent codex` → brief has dev_agents |
| `test_feature_flow_prebuilt` | 4 | `runner._feature_flow is not None` after `build_runtime()` |
| `test_feature_flow_degradation` | 4 | Pre-build failure → warning, `feature_flow_available=False` |
| `test_skip_qa_passed_to_bug_flow` | 4 | `DEV_LOOP_SKIP_QA=true` → `build_dev_loop_flow(skip_qa=True)` |
| `test_usage_auto_display` | 5 | Post-run renders usage Panel when `.usage.json` exists |
| `test_usage_suppressed` | 5 | `--no-usage` → no usage Panel rendered |
| `test_cmd_usage_active_run` | 5 | `/usage` → reads usage for active run |
| `test_cmd_usage_by_id` | 5 | `/usage run-abc123` → reads usage for specified run |
| `test_cmd_usage_not_found` | 5 | `/usage run-missing` → friendly message |

### Integration Tests

| Test | Description |
|---|---|
| `test_doc_flag_e2e` | `--doc` with a real spec file → FeatureBrief dispatched to (mocked) runner |
| `test_skip_flags_e2e` | `--skip-jira --skip-qa` → runner.run called with correct extra_shared |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_spec_file(tmp_path):
    """A minimal .spec.md file for --doc flag tests."""
    spec = tmp_path / "test-feature.spec.md"
    spec.write_text("# Test Spec\n\nMinimal spec for testing.")
    return str(spec)

@pytest.fixture
def sample_usage_json(tmp_path):
    """A minimal .usage.json for post-run display tests."""
    usage = tmp_path / "run-test01.usage.json"
    usage.write_text(UsageReport(
        run_id="run-test01", agents=[]
    ).model_dump_json())
    return usage
```

---

## 5. Acceptance Criteria

- [x] `--skip-jira` flag passes `extra_shared["skip_jira"] = True` to `runner.run()`
- [x] `--skip-qa` flag passes `extra_shared["skip_qa"] = True` to `runner.run()`
- [x] `--doc PATH` creates a `FeatureBrief` with `document_path=PATH`
- [x] `--doc-kind KIND` overrides suffix inference; without it, kind is inferred from suffix
- [x] `--doc` / `--brief` / `--text` are mutually exclusive (click.UsageError)
- [x] `--doc` composes with `--dev-agent` and `--skip-jira`/`--skip-qa`
- [x] `build_runtime()` pre-builds feature flow with `development_dispatcher_builder`, `development_pool_max`, `skip_qa`, `require_plan_approval`, `graph_memory`, `codereview_dispatcher`
- [x] Feature flow pre-build failure degrades gracefully (warning, `feature_flow_available=False`)
- [x] `DEV_LOOP_SKIP_QA` is read from conf and passed to both `build_dev_loop_flow()` and `build_dev_loop_feature_flow()`
- [x] Usage report auto-displays after run completion (Rich Panel with `render_usage_markdown` output)
- [x] `--no-usage` suppresses auto-display
- [x] `/usage [run-id]` slash command displays usage from `.usage.json`
- [x] All existing tests pass (no regressions in `tests/cli/devloop/`)
- [x] New unit tests cover all modules

---

## 6. Codebase Contract

### Verified Imports

```python
# CLI package
from parrot.cli.devloop.console import DevLoopConsole      # console.py:46
from parrot.cli.devloop.bootstrap import (                  # bootstrap.py
    build_runtime,          # line 237
    DevLoopRuntime,         # line 71
    preflight,              # line 84
)

# Dev-loop flow builders
from parrot.flows.dev_loop import (
    build_dev_loop_flow,    # flow.py:274, re-exported via __init__.py
    DevLoopRunner,          # runner.py, re-exported
)
from parrot.flows.dev_loop.runner import (
    build_dev_loop_feature_flow,  # runner.py:178
)
from parrot.flows.dev_loop.agent_builder import (
    build_dispatcher,       # agent_builder.py, used with functools.partial
)

# Models
from parrot.flows.dev_loop.models import (
    FeatureBrief,           # models/base.py:725
    DevAgentSpec,           # models/base.py (in existing imports)
    parse_brief,            # models/base.py (discriminated union parser)
)

# Usage report
from parrot.flows.dev_loop.usage_report import (
    UsageReport,              # usage_report.py:63
    build_usage_report,       # usage_report.py:104 (not needed — read from disk)
    render_usage_markdown,    # usage_report.py:210
)

# Config
from parrot import conf
# conf.OUTPUT_DIR             # conf.py:48 — Path, e.g. /home/user/outputs
# conf.DEV_LOOP_SKIP_QA       # bool, defaults to False
# conf.DEV_LOOP_REQUIRE_PLAN_APPROVAL  # bool, defaults to False
# conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES  # int
# conf.FLOW_STREAM_TTL_SECONDS  # int

# Code review
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory  # already imported in bootstrap.py:257

# Graph memory
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory  # already imported in bootstrap.py:258
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
@dataclass
class DevLoopRuntime:                    # line 71
    runner: Any                          # line 74 — DevLoopRunner
    flow: Any                            # line 75 — AgentsFlow
    dispatcher: Any                      # line 76 — ClaudeCodeDispatcher
    jira_toolkit: Any = None             # line 77
    redis_url: str = ""                  # line 78
    reporter: str = ""                   # line 79
    escalation_assignee: str = ""        # line 80
    graph_memory: Any = None             # line 81

# packages/ai-parrot/src/parrot/cli/devloop/console.py
class DevLoopConsole:                    # line 46
    async def start(                     # line 65
        self, *, brief_file, revision, dev_agents, intake_text, skip_confirm
    ) -> int: ...
    async def _dispatch_initial(         # line 130
        self, *, brief_file, revision, dev_agents, intake_text, skip_confirm
    ) -> None: ...
    async def _dispatch_run(self, brief: Any) -> str:  # line 757
        # Currently: runner.run(brief, run_id=run_id) — NO extra_shared
    handlers = {                         # line 1006
        "runs", "attach", "cancel", "new", "feature", "revise", "help", "quit", "exit"
    }

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    _feature_flow: Optional[AgentsFlow]  # line 362
    async def run(                       # line 885
        self, brief, *, run_id=None, initial_task="", extra_shared=None
    ) -> FlowResult: ...
    def get_host(self, run_id) -> Optional[SessionHost]:  # line 382

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
def build_dev_loop_feature_flow(         # line 178
    *, dispatcher, jira_toolkit=None, git_toolkit=None, wiki_toolkit=None,
    redis_url, codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max=4, graph_memory=None, require_plan_approval=False,
    skip_qa=False, name="dev-loop-feature", publish_flow_events=True,
) -> AgentsFlow: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
def build_dev_loop_flow(                 # line 274
    *, dispatcher, jira_toolkit, log_toolkits, redis_url, name="dev-loop",
    publish_flow_events=True, lifecycle_events=True,
    development_dispatcher=None, development_profile=None,
    development_pool_config=None, development_dispatcher_builder=None,
    development_pool_max=4, git_toolkit=None, repos=None,
    codereview_dispatcher=None, require_deployment_approval=False,
    wiki_search=None, graph_memory=None, require_plan_approval=False,
    skip_qa=False,
) -> AgentsFlow: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class FeatureBrief(BaseModel):           # line 725
    document_path: str                   # line 738
    document_kind: Literal["brainstorm", "proposal", "spec"]  # line 747
    jira_issue_key: Optional[str] = None # line 755
    dev_agents: Optional[List[DevAgentSpec]] = None  # line 763
    judge_panel: Optional[JudgePanelConfig] = None   # line 771

# packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py
class UsageReport(_Frozen):              # line 63
    run_id: str
    generated_at: float
    agents: list[AgentUsage]
    total_input_tokens: int | None
    total_output_tokens: int | None
    total_rounds: int | None

def render_usage_markdown(report: UsageReport) -> str:  # line 210
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `run_cmd` new flags | `DevLoopConsole.start()` | kwargs passthrough | `__init__.py:115` |
| `_dispatch_run` extra_shared | `DevLoopRunner.run()` | `extra_shared=` kwarg | `runner.py:891` |
| `--doc` route | `FeatureBrief()` constructor | direct construction | `models/base.py:725` |
| `build_runtime()` feature pre-build | `runner._feature_flow` | private attr assignment | `runner.py:362` |
| `build_runtime()` skip_qa | `build_dev_loop_flow(skip_qa=)` | kwarg | `flow.py:295` |
| Post-run usage display | `.usage.json` on disk | `conf.OUTPUT_DIR / dev_loop_runs / {run_id}.usage.json` | `runner.py:596` |
| `_cmd_usage` | `UsageReport.model_validate_json()` | Pydantic deserialization | `usage_report.py:63` |

### Does NOT Exist (Anti-Hallucination)

- ~~`DevLoopRuntime.feature_flow_available`~~ — does not exist yet, Module 4 adds it
- ~~`DevLoopConsole._cmd_usage()`~~ — does not exist yet, Module 5 adds it
- ~~`DevLoopRuntime.show_usage`~~ — does not exist; `show_usage` is a console-level bool, not a runtime field
- ~~`runner.get_usage_report(run_id)`~~ — no such method; read `.usage.json` from disk instead
- ~~`DevLoopConsole.extra_shared`~~ — not an instance attr; built per-dispatch in `_dispatch_run`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Flag propagation**: same pattern as existing `dev_agents`/`intake_text`/`skip_confirm` — kwargs flow `run_cmd` → `console.start()` → `_dispatch_initial()` → `_dispatch_run()`.
- **Feature flow pre-seed**: identical to `server.py` `_on_startup` (lines 1459-1480) — `try/except` wrapping, `runner._feature_flow = build_dev_loop_feature_flow(...)`.
- **Usage from disk**: read the `.usage.json` the runner already persists (`runner.py:596-608`). Don't recalculate — avoids needing access to `shared_data` post-run.
- **Graceful degradation**: every new capability degrades silently (warning log) when prerequisites are missing. No new hard failures.

### Known Risks / Gotchas

- **`runner._feature_flow` is private** (`SLF001`): same `noqa: SLF001` comment as `server.py:1459`. This is the established pattern — the runner exposes no public setter because pre-seeding is an optimization, not a contract.
- **`_infer_doc_kind` suffix matching order**: `.spec.md` must be checked before `.md` (substring match). Use `name.endswith()` with the longest suffix first.
- **Usage file timing**: the runner persists `.usage.json` in `_persist_run_bundle` (called from the run's `finally` block). By the time the console detects `task.done()`, the file exists. Race condition is not possible because `task.result()` blocks until the coroutine (including `finally`) completes.
- **Backward compatibility**: all new `start()` kwargs have defaults (`None`/`False`). Existing tests calling `start(brief_file=...)` are unaffected.

### External Dependencies

No new external dependencies. All imports are from existing `parrot` packages.

---

## 8. Open Questions

No open questions. All design decisions were resolved during brainstorming:

- [x] Scope: skip-jira, skip-qa, doc shortcut, feature-flow pre-build, usage report — *Resolved in brainstorming*
- [x] `--spec` vs `--doc` naming → `--doc PATH` + `--doc-kind KIND` with suffix inference — *Resolved in brainstorming*: Option B chosen
- [x] Usage display mode → automatic + `/usage` command (A+C) — *Resolved in brainstorming*
- [x] Approach → Full homologation (B) — *Resolved in brainstorming*

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks in one worktree).
- All 5 modules touch the same 3 files (`__init__.py`, `console.py`,
  `bootstrap.py`), making parallel execution impractical.
- **Recommended order**: Module 1 → Module 4 → Module 2 → Module 3 → Module 5.
  Module 4 (bootstrap) is independent and can be done early. Modules 2 and 3
  depend on Module 1's flags. Module 5 depends on Module 3 (run completion).
- **Cross-feature dependencies**: none. All referenced code already exists on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-04 | Jesus Lara | Initial draft — brainstorming-approved design |
