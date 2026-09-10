# TASK-3079: Models, policy, result budget, worktree lock and shared toolkit base

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models", §2 "Overview", §3 Module M1. Every later task
(Git, reader, contracts, writer, hooks) imports from this package. This task
creates the `parrot_tools.tool_optimizations` package, its Pydantic
contracts, the operation policy (limits, byte budget, path policy), the
cross-process worktree lock, and the shared `AbstractToolkit` base that
enforces raw-argument validation and JSON-dict serialization at the tool
boundary.

**Decisions fixed here (do not re-decide in later tasks):**

1. **Package layout** (`packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/`):
   `__init__.py` (lazy exports only), `models.py` (all Pydantic contracts +
   per-tool argument models), `policy.py` (`OptimizationPolicy`, byte budget,
   path checks, `WorktreeLock`), `base.py` (`OptimizationToolkitBase`).
   Spec §3 lists only `{__init__,models,policy}.py` for M1; `base.py` is an
   explicit, recorded addition so the three toolkits share one validation
   seam.
2. **Raw-argument validation happens in `AbstractToolkit._pre_execute`.**
   `MCPToolAdapter.execute()` calls `tool._execute(**arguments)` directly
   (`packages/ai-parrot/src/parrot/mcp/adapter.py:79`), bypassing
   `AbstractTool.execute()` schema validation. `ToolkitTool._execute()`
   still invokes `toolkit._pre_execute(self.name, **hook_kwargs)` with the
   RAW kwargs (`packages/ai-parrot/src/parrot/tools/toolkit.py:183`)
   BEFORE unknown-key stripping (`toolkit.py:193-198`). So `_pre_execute`
   sees every raw key and is the enforcement point for MCP input. The
   public methods ALSO validate their own arguments (direct Python calls
   must be safe too — spec §6 "Does NOT Exist").
3. **Result serialization.** Public methods return Pydantic models.
   `OptimizationToolkitBase._post_execute` converts them to
   `ToolResult(status="success", result=<compact JSON-safe dict>, metadata={})`.
   Reason: the adapter `str()`s any non-`ToolResult` return
   (`adapter.py:83-91`) and `json.dumps` only a `ToolResult.result` dict
   (`adapter.py:107-110`). Domain failures are still `status="success"` at
   the `ToolResult` level with `result["status"] == "error"|"uncertain"`;
   MCP `isError` is reserved for argument rejection and crashes. Keep
   `metadata={}` so the adapter does not append a "Metadata:" blob.
4. **Byte budget.** `max_result_bytes` measures
   `json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`
   of the domain dict (before `ToolResult`/MCP wrapping). Never slice JSON;
   shrink content/records and re-serialize. Minimum configured budget is
   4,096 bytes.
5. **Locking.** `WorktreeLock` is an `fcntl.flock(LOCK_EX)` on
   `<git-dir>/parrot-tool-optimizations.lock` (the per-worktree git dir,
   which for linked worktrees is `.git/worktrees/<name>/`). flock is
   advisory, released by the kernel on process death, so no stale-lock
   deletion is ever needed or allowed. Timeout via non-blocking `LOCK_NB`
   polling in a thread (`asyncio.to_thread`).

---

## Scope

- Create the package with the four modules above.
- Implement in `models.py` (all Pydantic v2, `model_config = ConfigDict(extra="forbid")`):
  - `StepResult`: `name: str`, `exit_code: int | None`, `timed_out: bool`,
    `state_changed: bool`, `stdout: str = ""`, `stderr: str = ""`,
    `truncated: bool = False`.
  - `OperationResult`: `status: Literal["ok", "error", "uncertain"]`,
    `operation: str`, `data: dict[str, Any] = {}`,
    `error: OperationError | None`, `steps: list[StepResult] = []`,
    `truncated: bool = False`, `diagnostic_path: str | None = None`,
    `elapsed_ms: int`.
  - `OperationError`: `code: str` (snake_case, e.g. `range_required`,
    `path_outside_root`, `secret_file`, `unrelated_staged`), `message: str`,
    `details: dict[str, Any] = {}`.
  - `SourceResult`: `path: str` (repo-relative POSIX), `sha256: str`,
    `size_bytes: int`, `start_line: int`, `end_line: int`, `content: str`,
    `truncated: bool`, `next_line: int | None`, `eof: bool`.
  - `SourceInfo`: `path`, `sha256`, `size_bytes`, `line_count: int | None`
    (None when only threshold detection ran), `is_large: bool`,
    `max_lines: int`, `large_file_bytes: int`, `range_required: bool`.
  - `WriterLimits`: `max_packet_bytes: int = 128_000`,
    `max_context_bytes: int = 128_000`, `max_patch_bytes: int = 128_000`,
    `max_output_tokens: int = 8_192`, `generation_deadline_seconds: int = 180`,
    `max_repairs: Literal[0, 1] = 1`. All `gt=0`.
  - `ReferenceSlice`: `path`, `sha256`, `start_line: int (ge=1)`,
    `end_line: int (ge=1)`, `purpose: str`; validator `start_line <= end_line`.
  - `TargetFile`: `path`, `action: Literal["create", "modify"]`,
    `expected_sha256: str | None`, `planned_changes: str`,
    `blocks: list[str]` (min 1); validator: `modify` requires
    `expected_sha256` (64 lowercase hex), `create` requires `None`.
  - `DelegationPacket`: `schema_version: Literal[1]`, `task_id: str`
    (`^TASK-\d{3,}$`), `spec_path: str`, `design_complete: Literal[True]`,
    `targets: list[TargetFile]` (min 1, unique paths), `references:
    list[ReferenceSlice]`, `implementation_blocks: list[str]` (min 1,
    unique), `acceptance_criteria: list[str]` (min 1),
    `validation_commands: list[list[str]]` (each argv non-empty, all `str`),
    `limits: WriterLimits = WriterLimits()`.
  - `PatchManifest`: `artifact_id: str`, `task_id: str`,
    `packet_sha256: str`, `patch_sha256: str`,
    `before_hashes: dict[str, str | None]`, `after_hashes: dict[str, str]`,
    `allowed_paths: list[str]`, `configured_model: str`,
    `actual_model: str | None`, `used_fallback: bool`,
    `usage: dict[str, int | None]` (`prompt_tokens`, `completion_tokens`,
    `total_tokens`; `None` = unknown), `repairs: int`, `elapsed_ms: int`,
    `validation_state: Literal["validated", "rejected"]`,
    `created_at: str` (ISO-8601 UTC).
  - Per-tool argument models (used by `@tool_schema` AND `_pre_execute`):
    `GitRecentArgs(ref: str = "HEAD", limit: int = Field(3, ge=1, le=50))`,
    `GitFetchArgs(remote: str = "origin", branch: str = "dev", recent: int = Field(3, ge=1, le=50))`,
    `GitPreflightArgs()`, `GitPrepareFilesArgs(paths: list[str] = Field(min_length=1))`,
    `GitPullArgs(remote: str = "origin", branch: str | None = None)`,
    `GitPushArgs(remote: str = "origin", branch: str | None = None)`,
    `SourceInfoArgs(path: str)`,
    `SourceReadArgs(path: str, start_line: int | None = Field(None, ge=1), end_line: int | None = Field(None, ge=1), expected_sha256: str | None = None)`
    with a model validator requiring both or neither range end and
    `start_line <= end_line`,
    `WriterGenerateArgs(task_path: str)`,
    `WriterApplyArgs(artifact_id: str, reviewed_sha256: str)` (both
    validated: artifact id `^[0-9a-f]{32}$`, sha `^[0-9a-f]{64}$`).
    Every string field: `min_length=1`, `max_length=4096`.
- Implement in `policy.py`:
  - `OptimizationPolicy(BaseModel, extra="forbid")`: `repo_root: Path`,
    `max_lines: int = 350 (ge=1)`, `large_file_bytes: int = 64_000 (ge=1)`,
    `max_result_bytes: int = 64_000 (ge=4096)`,
    `command_timeout_seconds: float = 30 (gt=0)`,
    `network_timeout_seconds: float = 120 (gt=0)`,
    `deny_secret_files: bool = True`. `repo_root` is resolved
    (`Path.resolve()`) and must be an existing directory.
  - `measure_json_bytes(obj: Any) -> int` and `compact_json(obj) -> str`
    using the exact serializer in Decision 4.
  - `fit_to_budget(result: OperationResult, budget: int) -> OperationResult`:
    if over budget, first clip each `StepResult.stdout/stderr` (whole
    lines, from the end, set `truncated=True`), then drop `data` list
    records from the end, then replace `data` with
    `{"omitted": true}`; the returned object always fits; never slices
    JSON text.
  - `relative_posix(root: Path, target: Path) -> str`.
  - `check_no_symlink_components(root: Path, candidate: str) -> Path`:
    walk `root / candidate` (normalized, NOT resolved) and `os.lstat`
    each component below `root`; raise `SymlinkRejectedError` if any is a
    symlink. Compose with `resolve_within_root` / `resolve_readable_path`
    from confinement (call those FIRST for containment + secret policy,
    then this check) in a helper
    `resolve_operand(policy, candidate, *, must_exist: bool) -> Path`.
  - `class WorktreeLock`: `__init__(lock_path: Path, timeout_seconds: float)`;
    `async __aenter__/__aexit__`; opens `lock_path` with `O_CREAT|O_RDWR`,
    0o600, tries `fcntl.flock(fd, LOCK_EX | LOCK_NB)` in
    `asyncio.to_thread` with 50 ms sleeps until timeout →
    `LockTimeoutError`. Never unlinks the lock file.
  - Exceptions: `PolicyError(ValueError)` base; `SymlinkRejectedError`,
    `LockTimeoutError`, `BudgetError`.
- Implement in `base.py`:
  - `class OptimizationToolkitBase(AbstractToolkit)` with
    `__init__(self, *, repo_root: str | Path, policy: OptimizationPolicy | None = None, **policy_overrides_and_toolkit_kwargs)`.
    Build `self.policy` from `repo_root` + any keys that are
    `OptimizationPolicy` fields found in kwargs (pop them), forward the
    rest to `super().__init__(**kwargs)`. Record
    `self._init_kwargs.update({"repo_root": str(self.policy.repo_root), ...policy fields})`
    (mirrors `ReadOnlyRepoToolkit.__init__`, `repo/toolkit.py:129-141`).
  - Class attribute `arg_models: dict[str, type[BaseModel]] = {}`
    mapping METHOD name → argument model. Subclasses populate it.
  - `async _pre_execute(self, tool_name, /, **kwargs)`: pop
    `_permission_context`; look up the model by the tool's original
    method name (`tool_name` equals the method name because no
    `tool_prefix` is set — assert `self.tool_prefix is None`); run
    `model.model_validate(kwargs)`; on `ValidationError` raise
    `ValueError(f"invalid arguments for {tool_name}: {compact summary}")`.
    Unknown tool names → `ValueError`.
  - `async _post_execute(self, tool_name, result, /, **kwargs)`: if
    `result` is a `BaseModel` → `ToolResult(status="success", result=result.model_dump(mode="json"), metadata={})`;
    if already a `ToolResult` or a `dict` → pass through unchanged.
  - Helper `_error(operation, code, message, details=None, steps=None, started=perf_counter) -> OperationResult`
    and `_ok(operation, data, steps, started, truncated=False)`; both call
    `fit_to_budget` with `self.policy.max_result_bytes`.
  - Helper `_repo_relative(self, candidate: str, *, readable: bool) -> str`
    using `resolve_operand`.
- `__init__.py`: module docstring + `__all__` + PEP 562 `__getattr__`
  that lazily imports names from `models`/`policy`/`base` so importing
  the package does NOT import pydantic eagerly (the hook runtime in
  TASK-3088 must stay stdlib-light on import).
- Write `packages/ai-parrot-tools/tests/tool_optimizations/__init__.py`
  (empty) and `test_policy.py`.

**NOT in scope**: any Git command, file reading, model calls, MCP config,
hooks, SDD templates (TASK-3080+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/__init__.py` | CREATE | Lazy exports |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py` | CREATE | Contracts + argument models |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py` | CREATE | Policy, budget, path checks, lock |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py` | CREATE | Shared toolkit base with validation seam |
| `packages/ai-parrot-tools/tests/tool_optimizations/__init__.py` | CREATE | Test package |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_policy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports and signatures. Verify with `grep`
> before using anything not listed here.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # packages/ai-parrot/src/parrot/tools/toolkit.py:206
from parrot.tools.abstract import ToolResult              # packages/ai-parrot/src/parrot/tools/abstract.py:250
from parrot.tools.decorators import tool_schema           # packages/ai-parrot/src/parrot/tools/decorators.py:39
from parrot.tools.repo.confinement import (               # packages/ai-parrot/src/parrot/tools/repo/confinement.py
    PathOutsideRootError,   # :55
    SecretFileError,        # :59
    resolve_within_root,    # :63  (root: Path, candidate: str) -> Path
    is_secret_path,         # :93  (rel_path: str) -> bool
    resolve_readable_path,  # :115 (root: Path, candidate: str) -> Path
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                       # :206
    return_direct: bool = False                   # :235
    exclude_tools: tuple[str, ...] = ()           # :243
    tool_prefix: str | None = None                # :257
    prefix_separator: str = "_"                   # :260
    confirming_tools: frozenset = frozenset()     # :275
    llm_dependent_tools: frozenset = frozenset()  # :294
    auto_open: bool = False                       # :319
    def __init__(self, **kwargs): ...             # :321  (stores self._init_kwargs = dict(kwargs) at :351)
    async def _prepare_kwargs(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]  # :438
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None                          # :455
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any             # :470
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]          # :486
    def _generate_tools(self) -> None             # :539  — every public `async def` becomes a tool; names in exclude_tools skipped (:548-560)
    def _create_tool_from_method(self, name, bound_method) -> ToolkitTool  # :637 — reads bound_method._args_schema (:653)

class ToolkitTool(AbstractTool):                  # :35
    async def _execute(self, **kwargs) -> Any     # :145
    # :183 await toolkit._pre_execute(self.name, **hook_kwargs)   hook_kwargs = raw kwargs + "_permission_context"
    # :186 kwargs = await toolkit._prepare_kwargs(self.name, kwargs)
    # :193-198 unknown kwargs stripped ONLY AFTER the hooks above
    # :203 result = await toolkit._post_execute(self.name, result, **kwargs)

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                      # :250
    success: bool = True; status: str = "success"; result: Any; error: Optional[str] = None
    metadata: Dict[str, Any] = {}                 # :253-257
class AbstractTool(EventEmitterMixin, ABC):       # :281
    args_schema: Type[BaseModel] = AbstractToolArgsSchema   # :298
    async def execute(self, *args, **kwargs) -> ToolResult  # :872  (normalises non-ToolResult at :1048-1066)

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None)  # :39 — sets func._args_schema (:52)

# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                             # :8
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]  # :58
    # :59 confirm = arguments.pop("confirm", None)   :79 result = await self.tool._execute(**arguments)
    # :83-91 non-ToolResult → {"text": str(result)}   :101 _toolresult_to_mcp → json.dumps(result.result) when dict

# packages/ai-parrot/src/parrot/tools/repo/toolkit.py — pattern to mirror for _init_kwargs
class ReadOnlyRepoToolkit(AbstractToolkit):       # :76
    def __init__(self, *, repo_root: Path, ..., max_result_bytes: int = 64_000, command_timeout: float = 20.0, **kwargs)  # :79
    # :129-141 self._init_kwargs.update({...serialisable ctor kwargs...})
```

### Does NOT Exist
- ~~`parrot_tools.tool_optimizations`~~ — does not exist yet; this task creates it.
- ~~`AbstractToolkit.validate_args`~~ / ~~`AbstractToolkit.schema_for`~~ — no such hooks; use `_pre_execute`.
- ~~`ToolResult.data`~~ — the payload field is `result`.
- ~~`AbstractTool.execute` being called by the MCP adapter~~ — it calls `_execute` directly.
- ~~`parrot.tools.repo.confinement.resolve_no_symlink`~~ — symlink-component rejection is new (`policy.check_no_symlink_components`).
- ~~`fcntl.lockf` semantics == flock~~ — use `fcntl.flock`; `lockf` is per-process-and-range and behaves differently across fds.
- ~~A `models.py` in `parrot_tools/tool_optimizations` that other tasks may rename~~ — module names here are final.

---

## Implementation Notes

### Pattern to Follow
```python
# base.py — the validation seam (Decision 2 + 3)
class OptimizationToolkitBase(AbstractToolkit):
    arg_models: dict[str, type[BaseModel]] = {}

    def __init__(self, *, repo_root: str | Path, policy: OptimizationPolicy | None = None, **kwargs: Any) -> None:
        overrides = {k: kwargs.pop(k) for k in list(kwargs) if k in OptimizationPolicy.model_fields}
        super().__init__(**kwargs)
        self.policy = policy or OptimizationPolicy(repo_root=Path(repo_root), **overrides)
        self._init_kwargs.update({"repo_root": str(self.policy.repo_root), **self.policy.model_dump(mode="json", exclude={"repo_root"})})
        self.logger = logging.getLogger(__name__)

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        kwargs.pop("_permission_context", None)
        model = self.arg_models.get(tool_name)
        if model is None:
            raise ValueError(f"unknown tool {tool_name!r}")
        try:
            model.model_validate(kwargs)
        except ValidationError as exc:
            raise ValueError(f"invalid arguments for {tool_name}: {exc.errors()[0]['msg']}") from exc

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        if isinstance(result, BaseModel):
            return ToolResult(status="success", result=result.model_dump(mode="json"), metadata={})
        return result
```

```python
# policy.py — budget measurement (Decision 4)
def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)

def measure_json_bytes(obj: Any) -> int:
    return len(compact_json(obj).encode("utf-8"))
```

```python
# policy.py — advisory lock (Decision 5)
class WorktreeLock:
    def __init__(self, lock_path: Path, timeout_seconds: float) -> None: ...
    async def __aenter__(self) -> "WorktreeLock":
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                await asyncio.to_thread(fcntl.flock, self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    raise LockTimeoutError(str(self._path))
                await asyncio.sleep(0.05)
    async def __aexit__(self, *exc) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_UN); os.close(self._fd)   # never unlink
```

### Key Constraints
- `extra="forbid"` on EVERY model; argument models must reject unknown
  keys because `_pre_execute` sees raw MCP input.
- Ensure `from __future__ import annotations` is NOT used in `models.py`
  for the argument models, or `ToolkitTool._generate_args_schema_from_method`
  / `model_json_schema()` still work — verify `GitRecentArgs.model_json_schema()`
  in a test.
- `pytest` runs with `filterwarnings = error` (root `pyproject.toml:229`):
  any Pydantic deprecation warning fails the suite. Use `model_config = ConfigDict(...)`,
  `@field_validator`, `@model_validator(mode="after")` — never class `Config`.
- `asyncio_mode = auto` (`pytest.ini:3`): async tests need no marker.
- No `print`; use `self.logger` / module `logger`.
- Google-style docstrings + strict type hints on everything (a docstring
  becomes the LLM-visible tool description for public toolkit methods).
- Black line length 120 (`pyproject.toml [tool.black]`).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repo/toolkit.py:76-141` — constructor/`_init_kwargs` convention.
- `packages/ai-parrot/src/parrot/tools/repo/models.py:14` — `RepoToolError` error-shape precedent.
- `packages/ai-parrot/src/parrot/tools/repo/confinement.py` — reuse by composition, never copy.

---

## Acceptance Criteria

- [ ] `from parrot_tools.tool_optimizations import OptimizationPolicy, OperationResult, DelegationPacket, WorktreeLock, OptimizationToolkitBase` works (lazy `__getattr__`).
- [ ] `python -c "import parrot_tools.tool_optimizations"` does not import `pydantic` (assert `"pydantic" not in sys.modules` in a subprocess test).
- [ ] `OptimizationPolicy(max_result_bytes=1000)` raises; `4096` accepted.
- [ ] `fit_to_budget` output always satisfies `measure_json_bytes(...) <= budget`, including content with multibyte and JSON-escaped characters.
- [ ] `resolve_operand` rejects outside-root, symlinked components, and secret files (via `is_secret_path`), and accepts `.env.example`.
- [ ] `WorktreeLock` second holder times out; lock file is never deleted; a second process (via `subprocess` + `fcntl`) contending is refused.
- [ ] `_pre_execute` rejects unknown keys and out-of-range values with `ValueError`; `_post_execute` wraps a model into `ToolResult(status="success")` with `metadata == {}`.
- [ ] A stub subclass exposed through `StdioMCPServer` returns `isError: True` for a bad `tools/call` argument and `isError: False` with JSON text for a good one.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_policy.py -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/tool_optimizations` clean; `black --check` clean.
- [ ] Test log saved to `artifacts/logs/TASK-3079-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_policy.py
import json, os, subprocess, sys
from pathlib import Path
import pytest
from pydantic import ValidationError

from parrot_tools.tool_optimizations.models import OperationResult, StepResult, GitRecentArgs, SourceReadArgs, TargetFile
from parrot_tools.tool_optimizations.policy import (
    OptimizationPolicy, WorktreeLock, LockTimeoutError, SymlinkRejectedError,
    fit_to_budget, measure_json_bytes, resolve_operand,
)
from parrot_tools.tool_optimizations.base import OptimizationToolkitBase
from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig


def test_package_import_is_pydantic_free():
    code = "import sys, parrot_tools.tool_optimizations; print('pydantic' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"


def test_policy_minimum_budget(tmp_path):
    with pytest.raises(ValidationError):
        OptimizationPolicy(repo_root=tmp_path, max_result_bytes=1000)
    assert OptimizationPolicy(repo_root=tmp_path, max_result_bytes=4096).max_result_bytes == 4096


@pytest.mark.parametrize("payload", ["x" * 10_000, "ñ" * 10_000, '"\\' * 5_000])
def test_fit_to_budget_respects_escaped_bytes(payload):
    res = OperationResult(status="ok", operation="t", data={"records": [payload] * 5}, elapsed_ms=1,
                          steps=[StepResult(name="s", exit_code=0, timed_out=False, state_changed=False, stdout=payload)])
    fitted = fit_to_budget(res, 4096)
    assert measure_json_bytes(fitted.model_dump(mode="json")) <= 4096
    json.loads(json.dumps(fitted.model_dump(mode="json")))  # still valid JSON


def test_resolve_operand_rejects_symlink_and_secret(tmp_path):
    (tmp_path / "real.txt").write_text("x")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    (tmp_path / ".env").write_text("SECRET=1")
    policy = OptimizationPolicy(repo_root=tmp_path)
    with pytest.raises(SymlinkRejectedError):
        resolve_operand(policy, "link.txt", must_exist=True)
    with pytest.raises(Exception):  # SecretFileError
        resolve_operand(policy, ".env", must_exist=True)
    with pytest.raises(Exception):  # PathOutsideRootError
        resolve_operand(policy, "../outside", must_exist=False)


async def test_worktree_lock_contention(tmp_path):
    lock = tmp_path / "l.lock"
    async with WorktreeLock(lock, timeout_seconds=1):
        with pytest.raises(LockTimeoutError):
            async with WorktreeLock(lock, timeout_seconds=0.2):
                pass
    assert lock.exists()  # never deleted


def test_arg_models_forbid_unknown():
    with pytest.raises(ValidationError):
        GitRecentArgs(ref="HEAD", limit=3, extra=1)
    with pytest.raises(ValidationError):
        GitRecentArgs(limit=51)
    with pytest.raises(ValidationError):
        SourceReadArgs(path="a.py", start_line=5)  # end_line missing
    with pytest.raises(ValidationError):
        TargetFile(path="a.py", action="create", expected_sha256="0" * 64, planned_changes="x", blocks=["b"])


class _Stub(OptimizationToolkitBase):
    arg_models = {"git_recent": GitRecentArgs}
    async def git_recent(self, ref: str = "HEAD", limit: int = 3) -> OperationResult:
        """Stub."""
        return OperationResult(status="ok", operation="git_recent", data={"ref": ref, "limit": limit}, elapsed_ms=0)


async def test_mcp_raw_argument_rejection(tmp_path):
    server = StdioMCPServer(LocalServerConfig(name="t"))
    server.register_tools(_Stub(repo_root=tmp_path).get_tools())
    bad = await server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "git_recent", "arguments": {"limit": 999}}})
    assert bad["result"]["isError"] is True
    good = await server._handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                         "params": {"name": "git_recent", "arguments": {"limit": 2}}})
    assert good["result"]["isError"] is False
    assert json.loads(good["result"]["content"][0]["text"])["data"]["limit"] == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3079-tool-optimizations-models-policy.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
