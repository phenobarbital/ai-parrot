---
type: Wiki Overview
title: 'TASK-1083: Add `config` argument to `CloudSploitToolkit.run_scan` / `run_compliance_scan`'
id: doc:sdd-tasks-completed-task-1083-cloudsploit-toolkit-config-surface-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per FEAT-160 proposal §3 ("What Changes" → sixth bullet) and §2.1 (Localization
relates_to:
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.toolkit
  rel: mentions
---

# TASK-1083: Add `config` argument to `CloudSploitToolkit.run_scan` / `run_compliance_scan`

**Feature**: FEAT-160 — CloudSploit `--config` support for run_scan
**Spec**: `sdd/proposals/cloudsploit-config-support.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1079, TASK-1082
**Assigned-to**: unassigned

---

## Context

Per FEAT-160 proposal §3 ("What Changes" → sixth bullet) and §2.1 (Localization
row 5): expose the new `config` argument at the **toolkit level** — where the
LLM-agent-facing tool signature is defined. The toolkit resolves the effective
config path with this precedence (resolved during proposal Q&A):

```
effective = config if config is not None else self.config.config_file
```

When the call-arg overrides a non-None model default, emit a **DEBUG**-level log
note so override behaviour is traceable in agent runs. Then forward to the
executor.

This is the last task of the feature — it makes the new capability visible to
agents and humans.

---

## Scope

- Add `config: Optional[str] = None` parameter to:
  - `CloudSploitToolkit.run_scan`
  - `CloudSploitToolkit.run_compliance_scan`
- Resolve precedence with a single helper or inline expression. Forward the
  resolved value to `self.executor.run_scan(config=...)` /
  `self.executor.run_compliance_scan(config=...)`.
- When `config is not None` AND `self.config.config_file is not None` AND
  `config != self.config.config_file`, emit
  `self.logger.debug("Overriding CloudSploitConfig.config_file=%s with per-call config=%s", self.config.config_file, config)`.
- Update agent-facing docstrings to mention the parameter and the precedence
  rule (since the docstring becomes the LLM tool description).
- Tests in `tests/cloudsploit/test_toolkit.py`.

**NOT in scope**:
- Anything not in `toolkit.py` or `test_toolkit.py`.
- File-existence checks — that's TASK-1082's job inside the executor.
- Implicit type coercion of `config` (e.g., `Path` objects). Document `str` only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py` | MODIFY | Add `config` arg to `run_scan` and `run_compliance_scan`; resolve precedence; DEBUG log on override; forward to executor |
| `packages/ai-parrot-tools/tests/cloudsploit/test_toolkit.py` | MODIFY | Add 4 tests: arg forwarding, model-default fallback, override + log, no-config baseline |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in toolkit.py
from typing import Optional
from ..toolkit import AbstractToolkit
from .executor import CloudSploitExecutor
from .models import CloudSploitConfig, ComplianceFramework, ScanResult
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:25-39
class CloudSploitToolkit(AbstractToolkit):
    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        self.executor = CloudSploitExecutor(self.config)
        # `self.logger` is provided by AbstractToolkit (do NOT re-create)

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:43-83
async def run_scan(
    self,
    plugins: Optional[list[str]] = None,
    ignore_ok: bool = False,
    suppress: Optional[list[str]] = None,
) -> ScanResult:
    results_json, collection_json, _stdout, stderr, code = (
        await self.executor.run_scan(
            plugins=plugins, ignore_ok=ignore_ok, suppress=suppress,
        )
    )
    ...

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:85-122
async def run_compliance_scan(
    self,
    framework: str,
    ignore_ok: bool = True,
) -> ScanResult:
    ...
    results_json, _collection_json, _stdout, stderr, code = (
        await self.executor.run_compliance_scan(
            framework=fw, ignore_ok=ignore_ok,
        )
    )
```

After TASK-1082 lands, the executor methods `run_scan` and `run_compliance_scan`
accept a `config: Optional[str] = None` parameter. **Verify this is the case
by reading executor.py before implementing.**

### Does NOT Exist
- ~~`self.config_file`~~ on the toolkit — the path lives on
  `self.config.config_file` (the Pydantic model).
- ~~`self.logger.info` for the override note~~ — use **`self.logger.debug`** so
  it doesn't spam production logs. The proposal explicitly chose DEBUG.
- ~~A `CloudSploitToolkit._resolve_config(...)` helper~~ — the resolution is a
  one-liner; don't create a dedicated method unless duplication arises.

---

## Implementation Notes

### Pattern to Follow
```python
async def run_scan(
    self,
    plugins: Optional[list[str]] = None,
    ignore_ok: bool = False,
    suppress: Optional[list[str]] = None,
    config: Optional[str] = None,
) -> ScanResult:
    """Run a CloudSploit security scan against cloud infrastructure.

    Args:
        plugins: Specific plugins to run. If None, runs all plugins.
        ignore_ok: If True, exclude passing (OK) results.
        suppress: Regex patterns to suppress specific results.
        config: Path to a CloudSploit JS credentials file. When set, takes
            precedence over `CloudSploitConfig.config_file` and over env-var
            credentials. The file must exist on disk.

    Returns:
        ScanResult with typed findings and summary.
    """
    effective_config = (
        config if config is not None else self.config.config_file
    )
    if (
        config is not None
        and self.config.config_file is not None
        and config != self.config.config_file
    ):
        self.logger.debug(
            "Per-call config=%s overrides CloudSploitConfig.config_file=%s",
            config, self.config.config_file,
        )

    results_json, collection_json, _stdout, stderr, code = (
        await self.executor.run_scan(
            plugins=plugins,
            ignore_ok=ignore_ok,
            suppress=suppress,
            config=effective_config,
        )
    )
    # ... rest unchanged
```

Apply the same pattern to `run_compliance_scan`.

### Key Constraints
- Docstring wording matters — it becomes the LLM tool description. Be precise
  about precedence and that the file must exist.
- DEBUG-level log only (not INFO). The proposal Q&A locked this in.
- Do NOT log when `config == self.config.config_file` (redundant) or when only
  one is set (no override happening).
- The agent-tool framework registers public async methods; do not rename
  `run_scan` or `run_compliance_scan`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:43-83` —
  current `run_scan` body.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:85-122` —
  current `run_compliance_scan` body.

---

## Acceptance Criteria

- [ ] `toolkit.run_scan(config="/path/cfg.js")` forwards `config="/path/cfg.js"`
      to `executor.run_scan`.
- [ ] `toolkit.run_scan()` with `CloudSploitConfig(config_file="/cfg.js")`
      forwards `config="/cfg.js"` (model default applied).
- [ ] `toolkit.run_scan(config="/override.js")` with
      `CloudSploitConfig(config_file="/orig.js")` forwards
      `config="/override.js"` AND emits one DEBUG log.
- [ ] `toolkit.run_scan()` with `CloudSploitConfig()` (no file) forwards
      `config=None` and emits NO DEBUG log.
- [ ] Same four behaviours for `run_compliance_scan(framework="hipaa", ...)`.
- [ ] All existing tests in `test_toolkit.py` still pass.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
      clean.

---

## Test Specification

```python
import logging
from unittest.mock import AsyncMock, patch
import pytest
from parrot_tools.cloudsploit.toolkit import CloudSploitToolkit
from parrot_tools.cloudsploit.models import CloudSploitConfig


class TestRunScanConfig:
    @pytest.mark.asyncio
    async def test_call_arg_forwarded(self):
        toolkit = CloudSploitToolkit(CloudSploitConfig())
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = ('{"plugin":{}}', '', '', '', 0)
            await toolkit.run_scan(config="/p/cfg.js")
            assert mock.await_args.kwargs["config"] == "/p/cfg.js"

    @pytest.mark.asyncio
    async def test_model_default_applies(self):
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/d/cfg.js")
        )
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = ('{"plugin":{}}', '', '', '', 0)
            await toolkit.run_scan()
            assert mock.await_args.kwargs["config"] == "/d/cfg.js"

    @pytest.mark.asyncio
    async def test_call_arg_overrides_model_default_and_logs(self, caplog):
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/orig.js")
        )
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = ('{"plugin":{}}', '', '', '', 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_scan(config="/override.js")
            assert mock.await_args.kwargs["config"] == "/override.js"
            assert any("overrides" in r.message.lower()
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_config_no_log(self, caplog):
        toolkit = CloudSploitToolkit(CloudSploitConfig())
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = ('{"plugin":{}}', '', '', '', 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_scan()
            assert mock.await_args.kwargs["config"] is None
            assert not any("overrides" in r.message.lower()
                           for r in caplog.records)
```

---

## Agent Instructions

When you pick up this task:

1. **Confirm dependencies**: TASK-1079 (config_file field) and TASK-1082
   (executor accepts `config=`) must be in `sdd/tasks/completed/`.
2. **Read the proposal** §3 ("What Changes" → toolkit bullet) and §5 (resolved
   precedence rule).
3. **Verify the Codebase Contract** by reading `toolkit.py:25-122`.
4. **Implement** the parameter, precedence logic, DEBUG log, and forwarding.
5. **Run the full feature test suite**:
   `pytest packages/ai-parrot-tools/tests/cloudsploit/ -v`.
6. **Move this file** to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Added `config: Optional[str] = None` to both `run_scan` and `run_compliance_scan`. Implemented precedence rule (`config if config is not None else self.config.config_file`) and DEBUG log on override. 8 new tests pass (4 for run_scan, 4 for run_compliance_scan). All 35 toolkit tests pass.

**Deviations from spec**: none
