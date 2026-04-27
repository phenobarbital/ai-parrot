# Dev-Loop Integration Tests

Live tests for the dev-loop orchestration flow (FEAT-129). These
tests exercise the full dispatch + flow + streaming + webhook surface
against real external services and are gated behind the `live`
pytest marker.

CI runs **only** the unit tests under
`packages/ai-parrot/tests/flows/dev_loop/`. The tests in this
directory are run manually on a developer machine.

## Prerequisites

| Variable | Required for | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | E2E tests | Used by the `claude` CLI under the hood. |
| `claude` CLI on PATH | E2E tests | Install via the project's `[claude-agent]` extra plus `npm i -g @anthropic-ai/claude-cli`. |
| `redis` Python package | All live tests | Installed by default. |
| Live Redis instance | E2E tests | `redis://localhost:6379/0` by default; override via `REDIS_URL`. |
| `JIRA_TEST_PROJECT_KEY` | E2E happy-path | Sandbox project for safe ticket creation. |
| `GITHUB_REPOSITORY` + `GITHUB_TOKEN` | E2E happy-path | Used by `DeploymentHandoffNode` REST fallback. |

## Run

```bash
# Run only the live tests (skips when prerequisites are missing).
source .venv/bin/activate
PYTHONPATH=packages/ai-parrot/src pytest -m live \
    packages/ai-parrot/tests/flows/dev_loop/integration/ -v

# Run them as part of a wider sweep (skips when missing prereqs).
PYTHONPATH=packages/ai-parrot/src pytest \
    packages/ai-parrot/tests/flows/dev_loop/ -v
```

## Cleanup

The tests are designed to be hermetic:

* Worktrees are created under a `tmp_path` and torn down by pytest.
* Redis streams use ephemeral `run_id`s prefixed with `run-` and expire
  via `FLOW_STREAM_TTL_SECONDS`.
* Jira tickets created against the sandbox project are NOT deleted
  automatically — set `JIRA_TEST_PROJECT_KEY` to a project where you
  expect throwaway tickets to accumulate.

## Test files

| File | Purpose |
|---|---|
| `test_end_to_end_happy_path.py` | Full flow → PR opened. **Currently a skip-stub** until the test environment exposes `JIRA_TEST_PROJECT_KEY` + `GITHUB_REPOSITORY` + `GITHUB_TOKEN`. The skeleton in the file documents the intended structure for future maintainers. |
| `test_end_to_end_qa_failure_path.py` | QA fails → ticket lands in *Needs Human Review*; no PR. **Skip-stub** for the same reason. |
| `test_concurrency.py` | Dispatcher cap enforcement. Runs without `claude` CLI thanks to a slow-mock client; only requires `redis` Python package. |
| `test_websocket_replay.py` | `FlowStreamMultiplexer` replay on reconnect. Uses an in-process stream stub — no live Redis needed. |
