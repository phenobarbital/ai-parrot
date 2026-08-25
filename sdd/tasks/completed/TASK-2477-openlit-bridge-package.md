# TASK-2477: OpenLIT Bridge Package

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Creates the minimal `ai-parrot-openlit-bridge` package that replaces the `openlit`
SDK in the `observability-openlit` extra. This package provides:
1. `validate_endpoint(url)` — async probe checking OTLP endpoint reachability
2. `parrot-openlit-check` CLI entry point
3. Bundled `docker-compose.openlit.yml` snippet

The package has zero heavy dependencies — only `aiohttp` (already a workspace dep).

Implements spec §3 Module 9.

---

## Scope

- Create package structure under `packages/ai-parrot-openlit-bridge/`
- Implement `validate_endpoint(url)` async function
- Implement `parrot-openlit-check` CLI entry point
- Bundle `docker-compose.openlit.yml` template
- Create `pyproject.toml` with minimal deps
- Write unit tests

**NOT in scope**: Wiring the extra in ai-parrot's pyproject.toml (TASK-2476 handles that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-openlit-bridge/pyproject.toml` | CREATE | Package metadata, deps, entry point |
| `packages/ai-parrot-openlit-bridge/src/ai_parrot_openlit_bridge/__init__.py` | CREATE | Package init with validate_endpoint export |
| `packages/ai-parrot-openlit-bridge/src/ai_parrot_openlit_bridge/probe.py` | CREATE | validate_endpoint implementation |
| `packages/ai-parrot-openlit-bridge/src/ai_parrot_openlit_bridge/cli.py` | CREATE | CLI entry point |
| `packages/ai-parrot-openlit-bridge/docker-compose.openlit.yml` | CREATE | Docker compose snippet |
| `packages/ai-parrot-openlit-bridge/tests/test_probe.py` | CREATE | Unit tests |
| `packages/ai-parrot-openlit-bridge/README.md` | CREATE (not originally listed) | Referenced by `pyproject.toml`'s `readme` field; matches every other workspace package's convention |
| `packages/ai-parrot-openlit-bridge/src/ai_parrot_openlit_bridge/py.typed` | CREATE (not originally listed) | PEP 561 marker, referenced by `tool.setuptools.package-data` |
| `packages/ai-parrot-openlit-bridge/tests/test_cli.py` | CREATE (not originally listed) | Unit tests for the `parrot-openlit-check` CLI entry point (AC explicitly requires CLI exit-code coverage) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# This is a NEW standalone package — no existing parrot imports needed.
# Dependencies:
import aiohttp  # already a workspace dependency
```

### Does NOT Exist
- ~~`ai-parrot-openlit-bridge` package~~ — does not exist under `packages/`; must be created
- ~~`validate_endpoint()` function~~ — does not exist; must be created

---

## Implementation Notes

### Package Structure
```
packages/ai-parrot-openlit-bridge/
├── pyproject.toml
├── docker-compose.openlit.yml
├── src/
│   └── ai_parrot_openlit_bridge/
│       ├── __init__.py
│       ├── probe.py
│       └── cli.py
└── tests/
    └── test_probe.py
```

### pyproject.toml
```toml
[project]
name = "ai-parrot-openlit-bridge"
version = "0.1.0"
description = "Minimal OpenLIT OTLP endpoint validation for ai-parrot"
requires-python = ">=3.10"
dependencies = [
    "aiohttp>=3.9",
]

[project.scripts]
parrot-openlit-check = "ai_parrot_openlit_bridge.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_parrot_openlit_bridge"]
```

### probe.py Pattern
```python
"""OTLP endpoint validation probe."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class EndpointStatus:
    """Result of an OTLP endpoint probe."""
    reachable: bool
    status_code: Optional[int] = None
    collector_info: Optional[str] = None
    error: Optional[str] = None


async def validate_endpoint(
    url: str,
    *,
    timeout: float = 5.0,
    headers: dict[str, str] | None = None,
) -> EndpointStatus:
    """Probe an OTLP endpoint for reachability.

    Sends a lightweight HTTP request to the OTLP health or traces endpoint
    and returns status information.

    Args:
        url: OTLP base URL (e.g. "http://localhost:4318").
        timeout: Request timeout in seconds.
        headers: Optional auth headers.

    Returns:
        EndpointStatus with reachability info.
    """
    # Try the standard OTLP HTTP health path
    health_url = f"{url.rstrip('/')}/v1/traces"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                health_url,
                headers=headers or {},
                timeout=aiohttp.ClientTimeout(total=timeout),
                data=b"",  # empty POST to traces endpoint
            ) as resp:
                return EndpointStatus(
                    reachable=True,
                    status_code=resp.status,
                    collector_info=resp.headers.get("server"),
                )
    except Exception as exc:
        return EndpointStatus(
            reachable=False,
            error=str(exc),
        )
```

### cli.py Pattern
```python
"""CLI entry point for parrot-openlit-check."""
import argparse
import asyncio
import sys

from ai_parrot_openlit_bridge.probe import validate_endpoint


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an OTLP endpoint for OpenLIT compatibility.",
    )
    parser.add_argument("url", help="OTLP base URL (e.g. http://localhost:4318)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout in seconds")
    args = parser.parse_args()

    result = asyncio.run(validate_endpoint(args.url, timeout=args.timeout))
    if result.reachable:
        print(f"✅ Endpoint reachable: {args.url}")
        print(f"   Status: {result.status_code}")
        if result.collector_info:
            print(f"   Collector: {result.collector_info}")
        sys.exit(0)
    else:
        print(f"❌ Endpoint unreachable: {args.url}")
        print(f"   Error: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### Key Constraints
- Zero heavy dependencies — only `aiohttp`
- The `validate_endpoint()` function is best-effort, never blocking
- CLI exit code: 0 for reachable, 1 for unreachable
- Package must be installable standalone: `pip install ai-parrot-openlit-bridge`

---

## Acceptance Criteria

- [ ] Package structure exists under `packages/ai-parrot-openlit-bridge/`
- [ ] `from ai_parrot_openlit_bridge import validate_endpoint` works
- [ ] `validate_endpoint("http://reachable:4318")` returns `EndpointStatus(reachable=True, ...)`
- [ ] `validate_endpoint("http://nonexistent:4318")` returns `EndpointStatus(reachable=False, error=...)`
- [ ] `parrot-openlit-check http://localhost:4318` CLI works (exit 0 on success, 1 on failure)
- [ ] `docker-compose.openlit.yml` exists and is valid YAML
- [ ] All tests pass: `pytest packages/ai-parrot-openlit-bridge/tests/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-openlit-bridge/`

---

## Test Specification

```python
# packages/ai-parrot-openlit-bridge/tests/test_probe.py
import pytest
import aiohttp
from unittest.mock import patch, AsyncMock, MagicMock

from ai_parrot_openlit_bridge.probe import validate_endpoint, EndpointStatus


class TestValidateEndpoint:
    @pytest.mark.asyncio
    async def test_reachable_endpoint(self):
        """Returns reachable=True for a responsive endpoint."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"server": "otel-collector"}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await validate_endpoint("http://localhost:4318")
            assert result.reachable is True
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_unreachable_endpoint(self):
        """Returns reachable=False for a dead endpoint."""
        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await validate_endpoint("http://nonexistent:4318")
            assert result.reachable is False
            assert result.error is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — this task has none (independent package)
3. **Create the package structure** as documented above
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2477-openlit-bridge-package.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Created the `ai-parrot-openlit-bridge` package under
`packages/ai-parrot-openlit-bridge/` (auto-picked-up by the workspace's
`members = ["packages/*"]` glob — no root `pyproject.toml` change needed).
`probe.py` implements `validate_endpoint(url, *, timeout=5.0, headers=None)
-> EndpointStatus`, a best-effort async OTLP-reachability check (empty POST
to `<url>/v1/traces`) that never raises. `cli.py` wraps it as the
`parrot-openlit-check` console script (exit 0/1). Bundled
`docker-compose.openlit.yml` (OpenLIT collector + Postgres backing store)
and a `README.md`. Verified end-to-end: installed the package editable via
`uv pip install -e packages/ai-parrot-openlit-bridge --no-deps`, confirmed
`from ai_parrot_openlit_bridge import validate_endpoint` imports cleanly,
and ran the real (uninstalled after) `parrot-openlit-check` console script
against an actually-closed port (`http://localhost:19999`), observing the
real `❌ ... exit 1` output — not just the mocked unit tests. 8 new unit
tests added (5 for `probe.py`, 3 for `cli.py`), all pass; `ruff check` on
the whole package is fully clean (brand-new package, no pre-existing
baseline to preserve). `docker-compose.openlit.yml` validated as parseable
YAML via `yaml.safe_load()`.

**Deviations from spec**: (1) Used `setuptools` as the build backend
(matching every other package in this workspace, e.g.
`ai-parrot-loaders`) instead of the task's illustrative `hatchling`
snippet — `hatchling` is not used anywhere else in the repo and would be
an unnecessary new build-backend dependency for a workspace member. (2)
`requires-python = ">=3.11"` (matching the workspace-wide floor in the
root `pyproject.toml` and every sibling package) instead of the task's
illustrative `>=3.10`. (3) Added `README.md`, `py.typed`, and
`tests/test_cli.py` (not in the original Files table) — see the note
added to that table. (4) Per the task's explicit "NOT in scope" note,
`packages/ai-parrot/pyproject.toml`'s `observability-openlit` extra was
NOT re-wired to depend on this new package — TASK-2476 (already
completed, sequenced before this task) left it as an empty
backward-compat placeholder. Wiring `observability-openlit =
["ai-parrot-openlit-bridge"]` is a natural follow-up but is out of this
task's stated scope and was not done.

**Post-review fix**: the adversarial code review (run after all 8 tasks
completed) flagged this exact gap as an "Important" finding — closing it
before merge rather than leaving two "not my scope" notes pointing at each
other. Wired `observability-openlit = ["ai-parrot-openlit-bridge"]` in
`packages/ai-parrot/pyproject.toml` and added the corresponding
`ai-parrot-openlit-bridge = { workspace = true }` entry to the root
`pyproject.toml`'s `[tool.uv.sources]` (matching every sibling satellite
package's existing pattern). Updated `test_extras_still_exist_with_empty_
deps` (renamed `test_extras_still_exist_without_the_sdks`) and added
`test_observability_openlit_installs_bridge_package` in
`test_integrations_removed.py` to assert the new wiring. Also fixed a
docstring/behavior mismatch the same review caught in `config.py`'s
`from_env()` (claimed `OBSERVABILITY_OPENLIT_RECORDER` could be set to a
URL directly; the code only ever parsed it as a boolean) and added a
debug log in `bootstrap.py`'s otel branch so setting
`OBSERVABILITY_OPENLIT_RECORDER` alongside `OBSERVABILITY_BACKEND=otel`
no longer silently does nothing without a trace of why.
