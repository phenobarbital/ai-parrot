# TASK-239: Docker Toolkit Unit Tests

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-237, TASK-238
**Assigned-to**: claude-session

---

## Context

> Comprehensive unit tests for all Docker toolkit components: config, models, executor, compose generator, and toolkit.
> Implements spec Section 4.

---

## Scope

- Create `tests/tools/docker/` test directory with `__init__.py` and `conftest.py`.
- Create test files:
  - `test_config.py` — DockerConfig defaults and custom values
  - `test_models.py` — All Pydantic model validation
  - `test_executor.py` — CLI arg building, output parsing, daemon detection (mocked)
  - `test_compose.py` — YAML generation and validation
  - `test_toolkit.py` — Tool exposure, daemon checks, error handling (mocked)
- All executor/toolkit tests must mock subprocess calls (no real Docker required).
- Use `pytest-asyncio` for async tests.

**NOT in scope**: Integration tests requiring live Docker daemon (TASK-240).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/docker/__init__.py` | CREATE | Package init |
| `tests/tools/docker/conftest.py` | CREATE | Shared fixtures |
| `tests/tools/docker/test_config.py` | CREATE | Config tests |
| `tests/tools/docker/test_models.py` | CREATE | Model validation tests |
| `tests/tools/docker/test_executor.py` | CREATE | Executor tests (mocked) |
| `tests/tools/docker/test_compose.py` | CREATE | Compose generator tests |
| `tests/tools/docker/test_toolkit.py` | CREATE | Toolkit integration tests (mocked) |

---

## Implementation Notes

### Fixtures (conftest.py)
```python
import pytest
from parrot.tools.docker.config import DockerConfig
from parrot.tools.docker.models import ComposeServiceDef


@pytest.fixture
def docker_config():
    return DockerConfig(use_docker=False, timeout=30)


@pytest.fixture
def sample_compose_services():
    return {
        "redis": ComposeServiceDef(
            image="redis:alpine",
            ports=["6379:6379"],
            healthcheck={"test": ["CMD", "redis-cli", "ping"], "interval": "10s"}
        ),
        "postgres": ComposeServiceDef(
            image="postgres:16-alpine",
            ports=["5432:5432"],
            environment={"POSTGRES_DB": "testdb", "POSTGRES_USER": "testuser", "POSTGRES_PASSWORD": "testpass"}
        )
    }


@pytest.fixture
def mock_docker_ps_output():
    return '{"ID":"abc123","Names":"redis","Image":"redis:alpine","Status":"Up 2h","Ports":"6379","CreatedAt":"now"}'
```

### Key Constraints
- All tests must pass without Docker installed.
- Mock `asyncio.create_subprocess_exec` for executor tests.
- Test both success and error paths.

---

## Acceptance Criteria

- [ ] All test files created in `tests/tools/docker/`
- [ ] `pytest tests/tools/docker/ -v` passes (all unit tests)
- [ ] Config: defaults, custom values, resource limits
- [ ] Models: all 11 models validated
- [ ] Executor: arg building, output parsing, daemon check
- [ ] Compose: single-service, multi-service, healthcheck YAML generation
- [ ] Toolkit: tool count, tool names, daemon check, error handling
- [ ] No tests require live Docker daemon

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-237, TASK-238 must be done
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** all test files
4. **Run** `pytest tests/tools/docker/ -v` to verify
5. **Move this file** to `sdd/tasks/completed/TASK-239-docker-unit-tests.md`
6. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Created comprehensive unit test suite — 128 tests total, all passing:

| File | Tests | Coverage |
|---|---|---|
| `conftest.py` | — | Shared fixtures: config, executor, toolkit, compose services, mock outputs |
| `test_config.py` | 10 | Defaults, custom values, resource limits, serialization, schema |
| `test_executor.py` | 47 | Init, build_run_args (12), build_exec_args (4), build_build_args (4), _build_cli_args (11), parse_ps_output (5), parse_images_output (2), check_daemon (3), check_compose (2), run_command (3), result helpers (3) |
| `test_models.py` | 24 | All 11 models + parametrized JSON schema generation |
| `test_compose.py` | 14 | to_dict, generate, volume extraction, healthcheck, multi-service |
| `test_toolkit.py` | 29 | Tool count/names, daemon checks, success/error paths, prune warning, return types |

All tests run without Docker installed (subprocess calls mocked). No lint errors.
