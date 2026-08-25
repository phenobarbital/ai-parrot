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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
