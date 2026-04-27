# TASK-890: Documentation — README "Optional capabilities" section

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-886
**Assigned-to**: unassigned

---

## Context

Spec acceptance criterion: "Documentation: a short section in the
package README under 'Optional capabilities' describes how to enable
the dev-loop flow and what it does."

Also document the runtime requirements (`gh` CLI optional, Jira
service-account, Redis, `claude-agent-sdk` extra) and the navconfig
settings (TASK-876).

---

## Scope

- Add a new section to the AI-Parrot README:
  - Title: `### Dev-Loop Orchestration`
  - Sub-sections: "What it does", "Prerequisites", "Configuration",
    "Quickstart".
  - Quickstart shows the 5-line wiring inside a host application
    (instantiate dispatcher, build flow, register webhook, run via
    orchestrator).
  - Configuration sub-section lists each of the six navconfig
    settings introduced by TASK-876 with their default and meaning.
- If an "Optional capabilities" parent section does not yet exist,
  create it.
- Add a one-line entry to `pyproject.toml` describing the
  `[claude-agent]` extra (if not already present from FEAT-124) — the
  dev-loop flow inherits this dependency.

**NOT in scope**:
- A new dedicated docs page (`docs/...`). The spec asks only for a
  README section.
- API reference for every class — the docstrings are the API ref.
- Tutorials / migration guides.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `README.md` (root) OR `packages/ai-parrot/README.md` | MODIFY | New "Dev-Loop Orchestration" section. Locate the right one by reading the existing structure. |
| `packages/ai-parrot/pyproject.toml` | MODIFY (verify) | Confirm `[claude-agent]` extra references `claude-agent-sdk>=0.1.68` (already done by FEAT-124; verify only). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

N/A — pure documentation.

### Does NOT Exist

- ~~A `docs/dev-loop.md`~~ as a separate file — out of scope.
- ~~Auto-generated API docs~~ — the project does not run sphinx.

---

## Implementation Notes

### README section (drop-in template)

```markdown
### Dev-Loop Orchestration

> _Optional. Requires the `[claude-agent]` extra:
> `pip install ai-parrot[claude-agent]`_

A 5-node `AgentsFlow` that fixes "small operational bugs" automatically:

```
BugIntake → Research → Development → QA → DeploymentHandoff
                                       │
                                       ↓ (qa failed / hard error)
                                  FailureHandler (escalate to a human)
```

The flow takes a Pydantic `BugBrief` (Jira ticket + log sources +
acceptance criteria) and produces a PR plus a Jira ticket transitioned
to "Ready to Deploy". Failures escalate back to the original reporter.

**Prerequisites**

- Python 3.11+ with `ai-parrot[claude-agent]` installed.
- `claude-agent-sdk >= 0.1.68` and either `ANTHROPIC_API_KEY` or a
  configured `claude` CLI in `PATH`.
- Redis 6+ for two-stream observability.
- Jira service account credentials wrapped in a
  `parrot.auth.credentials.StaticCredentialResolver`.
- (Optional) `gh` CLI for PR creation. Falls back to
  `parrot_tools.gittoolkit.GitToolkit` HTTP if unavailable.

**Configuration (navconfig)**

| Setting | Default | Purpose |
|---|---|---|
| `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` | `3` | Cap on concurrent Claude Code dispatches. |
| `FLOW_MAX_CONCURRENT_RUNS` | `5` | Cap on concurrent flow runs. |
| `FLOW_BOT_JIRA_ACCOUNT_ID` | `""` | Jira accountId of the service-account bot. |
| `WORKTREE_BASE_PATH` | `.claude/worktrees` | Base directory for per-feature worktrees. |
| `FLOW_STREAM_TTL_SECONDS` | `604800` | Retention for Redis dispatch streams (7 days). |
| `ACCEPTANCE_CRITERION_ALLOWLIST` | `["flowtask","pytest","ruff","mypy","pylint"]` | Allowed shell-command heads. |

**Quickstart**

```python
from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher, build_dev_loop_flow,
    register_pull_request_webhook,
)

dispatcher = ClaudeCodeDispatcher(
    max_concurrent=3,
    redis_url="redis://localhost:6379/0",
    stream_ttl_seconds=604800,
)
flow = build_dev_loop_flow(
    dispatcher=dispatcher,
    jira_toolkit=jira,                 # already wrapping flow-bot creds
    log_toolkits={"cloudwatch": cw, "elasticsearch": es},
    redis_url="redis://localhost:6379/0",
)
register_pull_request_webhook(orchestrator, secret=GITHUB_WEBHOOK_SECRET)
# Run via your AutonomousOrchestrator with a BugBrief in ctx.
```
```

### Key Constraints

- README stays under one screenful for this section. Push deeper
  detail to docstrings.
- Do NOT add screenshots, ASCII art beyond the topology box, or
  diagrams.
- No marketing language. Imperative + factual only.

---

## Acceptance Criteria

- [ ] The README contains a "Dev-Loop Orchestration" section.
- [ ] The section lists prerequisites, the six navconfig settings,
  and a working quickstart snippet.
- [ ] The quickstart snippet's imports resolve (compile-check by
  copy-pasting into a Python REPL with the package installed).
- [ ] `pyproject.toml`'s `[claude-agent]` extra is documented to
  pin `claude-agent-sdk>=0.1.68`.
- [ ] Markdown lints clean (whatever the project uses; if no linter,
  visual review is sufficient).

---

## Test Specification

N/A — documentation task. Verification is by:

1. `python -c "import parrot.flows.dev_loop; print('ok')"` succeeds in
   a venv with `ai-parrot[claude-agent]` installed.
2. The quickstart snippet's imports resolve.

---

## Agent Instructions

1. Confirm TASK-886 is completed.
2. Read the existing top-level README to find the right place for the
   new section (likely under "Features" or a pre-existing
   "Optional capabilities" / "Integrations" section).
3. Update index → `"in-progress"`.
4. Add the README section. Verify imports resolve.
5. Move to completed.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
