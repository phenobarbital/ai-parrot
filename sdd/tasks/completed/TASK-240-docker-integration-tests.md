# TASK-240: Docker Toolkit Integration Tests

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-239
**Assigned-to**: claude-opus-4-6

---

## Context

> Integration tests that run against a live Docker daemon. These verify end-to-end functionality: running containers, checking logs, compose deployment, build, exec, and cleanup.
> Implements spec Section 4 — Integration Tests.

---

## Scope

- Create `tests/tools/docker/test_integration.py` with integration tests.
- All tests marked with `@pytest.mark.integration` and `@pytest.mark.skipif` (skip if Docker not available).
- Tests:
  - `test_docker_ps_live` — list containers
  - `test_docker_run_and_stop` — run redis, verify, stop, remove
  - `test_docker_logs_output` — get logs from running container
  - `test_docker_build` — build image from test Dockerfile
  - `test_docker_exec` — run command inside container
  - `test_compose_generate_and_up` — generate, deploy, verify, tear down
  - `test_docker_prune` — prune stopped containers
  - `test_docker_test_health` — health-check running container

**NOT in scope**: Unit tests (TASK-239).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/docker/test_integration.py` | CREATE | Integration tests |
| `tests/tools/docker/fixtures/Dockerfile` | CREATE | Test Dockerfile for build tests |

---

## Implementation Notes

### Skip Decorator
```python
import shutil
import pytest

docker_available = shutil.which("docker") is not None

@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegration:
    ...
```

### Key Constraints
- Every test must clean up after itself (remove containers, images, compose stacks).
- Use unique container names with test prefix (e.g., `parrot-test-*`).
- Tests should be idempotent and safe to run repeatedly.
- Test Dockerfile should be minimal (e.g., `FROM alpine:latest\nCMD ["echo", "hello"]`).

---

## Acceptance Criteria

- [ ] Integration tests created and marked properly
- [ ] Tests skip gracefully when Docker is not available
- [ ] Full lifecycle test: run → logs → exec → stop → rm
- [ ] Build test: create image from Dockerfile
- [ ] Compose lifecycle: generate → up → down
- [ ] All tests clean up resources after completion
- [ ] `pytest tests/tools/docker/test_integration.py -v -m integration` passes when Docker is available

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-239 must be done
2. **Ensure Docker daemon is running** for test execution
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** test file and fixtures
5. **Run** integration tests to verify
6. **Move this file** to `sdd/tasks/completed/TASK-240-docker-integration-tests.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-09
**Notes**: Created 9 integration tests across 5 test classes:
- `TestDockerIntegrationPS` (3 tests): ps, ps --all, images
- `TestDockerIntegrationLifecycle` (1 test): full run→logs→exec→inspect→test→stop→rm cycle
- `TestDockerIntegrationBuild` (1 test): build from test Dockerfile with cleanup
- `TestDockerIntegrationCompose` (1 test): generate→up→down lifecycle
- `TestDockerIntegrationPrune` (1 test): prune stopped containers
- `TestDockerIntegrationHealth` (2 tests): not-found and running container checks

All tests use unique `parrot-test-*` prefixed names, clean up after themselves, and skip when Docker is unavailable. All 9 tests pass in ~27s.

**Deviations from spec**: none
