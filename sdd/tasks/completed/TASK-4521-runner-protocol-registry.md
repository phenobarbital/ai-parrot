# TASK-4521: Runner protocol, launcher normalisation and `.parrot/test_runners.toml` registry

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4520
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Defines the `RunnerAdapter` protocol every adapter (TASK-4524/4526/4527/4528)
implements, the shared launcher normalisation codex flagged as S3, and the registry that merges the
four built-in kinds with `.parrot/test_runners.toml` — the ONLY extension point in v1 because sibling
repos vendor the kernel by path (brainstorm Q1). Extension adapters fail closed (S12).

---

## Scope

- Create `test_scope/runners/__init__.py`, `base.py`, `registry.py` per the spec skeleton.
- Built-in kinds are declared as a name→module table (`pytest`→`.pytest`, `vitest`→`.vitest`, `cargo`→`.cargo`, `parrot-e2e`→`.parrot_e2e`) and imported LAZILY on first use — the modules land in later tasks.
- `load_registry` parses the TOML with `tomllib`, validates sections, imports `[extensions]` adapters by `module:Class`, checks them against `RunnerAdapter` (attribute presence) and raises `ValueError` naming `CONFIG_PATH` on any failure.
- Add `[runners.vitest] test_script` boolean handling in `normalize_launcher_argv` (`pnpm test` ⇒ `vitest run` only when not disabled).
- Extend `test_stdlib_only.py` to import `test_scope.runners` by path.

**NOT in scope**: Concrete adapters (TASK-4524/4526/4527/4528); planner use (TASK-4524); contract validation (TASK-4522).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/__init__.py` | CREATE | package exports |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/base.py` | CREATE | protocol + normaliser |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py` | CREATE | registry + TOML loader |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py` | CREATE | unit tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py` | MODIFY | cover runners/ |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
import tomllib  # stdlib; same usage as sdd_coder/lint.py:22
import importlib  # stdlib
from ..datatypes import Invocation, RunReport, TestTarget  # created by TASK-4520
from ..policy import TIERS, ScopePolicy  # verified: test_scope/policy.py:78,82
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
TIERS: tuple[str, ...] = ("task", "merge", "feature")   # line 78
class ScopePolicy:                                        # line 82
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py — existing launcher helpers to reuse (do not duplicate):
def env_prefix_of(argv) -> list[str]          # line 29
def strip_env_prefix(argv) -> list[str]       # line 39
def _strip_uv_run_prefix(argv) -> list[str]   # line 50
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py:1-5 — "Stdlib-only … Never import ``models`` (Pydantic) here." (applies to runners/ too)
```

### Does NOT Exist
- ~~`test_scope/runners/`~~ — created here
- ~~`.parrot/test_runners.toml` in the repo~~ — TASK-4537 creates it; absent ⇒ built-in defaults
- ~~a Python entry-point registry~~ — out of scope (spec Non-Goals)
- ~~`tomli`~~ — use stdlib `tomllib`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/base.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#strip_env_prefix",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#_strip_uv_run_prefix",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py#ScopePolicy"
  ]
}
```

---

## Implementation Notes

- Relative imports only (`from ..datatypes import …`) so the package works both as `parrot.flows.dev_loop.test_scope.runners` and path-imported `test_scope.runners`.
- Extension import: `importlib.import_module(module)`; a ModuleNotFoundError, a missing attribute, or a protocol miss ⇒ `ValueError(f"{CONFIG_PATH}: …")`. Never fall back to pytest-only.
- Default timeouts (open question §8 Q4, placeholders): pytest 60, vitest 120, cargo 300, parrot-e2e 900.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Write `base.py` (protocol + `normalize_launcher_argv` + constants) — *why*: adapters and the registry depend only on it.
2. Write `registry.py` with lazy built-in import and TOML merge — *why*: adapter modules land in later tasks.
3. Write tests with fake adapters injected through `RunnerRegistry(...)` — *why*: no built-in adapter exists yet.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/base.py` (CREATE)
```python
"""Runner adapter protocol and launcher normalisation (FEAT-709 M1). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..contract import strip_env_prefix
from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import ScopePolicy

EXCERPT_MAX_LINES: int = 30
DEFAULT_TIMEOUTS: Mapping[str, int] = {"pytest": 60, "vitest": 120, "cargo": 300, "parrot-e2e": 900}
LAUNCHER_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("uv", "run"), ("python", "-m"), ("python3", "-m"), ("pnpm", "exec"), ("pnpm", "run"), ("npx",),
)


def normalize_launcher_argv(argv: Sequence[str], *, pnpm_test_is_vitest: bool = True) -> list[str]:
    """Strip env assignments and known launcher chains; return the runner-headed argv.

    `pnpm test` / `pnpm run test` map to `vitest run` only when ``pnpm_test_is_vitest``.
    An unknown or ambiguous chain is returned unchanged (callers then match nothing).
    """
    argv = strip_env_prefix(argv)
    # FILL IN: loop removing LAUNCHER_PREFIXES (uv run flags like --no-sync stripped as in
    #          contract._strip_uv_run_prefix); map pnpm test/run test; basename argv[0] — bounded by spec §2 S3
    return list(argv)


@runtime_checkable
class RunnerAdapter(Protocol):
    """One test runner. Implementations are stateless; settings arrive per call."""

    kind: str
    binaries: tuple[str, ...]
    default_tiers: frozenset[str]
    report_format: str

    def matches(self, argv: Sequence[str]) -> bool: ...
    def operands(self, argv: Sequence[str]) -> list[str] | None: ...
    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool: ...
    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]: ...
    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str: ...
    def invocation(
        self, targets: Sequence[TestTarget], *, distribution: str, worktree: Path,
        settings: Mapping[str, str], policy: ScopePolicy, report_path: str,
    ) -> Invocation: ...
    def parse_report(
        self, *, report_path: Path | None, exit_code: int, stdout: str, stderr: str,
        duration_s: float, timed_out: bool, suite: str,
    ) -> RunReport: ...
    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]: ...
```
**Why**: Names and signatures are fixed by spec §3 M1; adapters in four later tasks implement exactly this.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py` (CREATE)
```python
"""Runner registry: built-ins merged with `.parrot/test_runners.toml` (FEAT-709 M1). Stdlib only."""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..policy import TIERS
from .base import DEFAULT_TIMEOUTS, RunnerAdapter, normalize_launcher_argv

CONFIG_PATH: str = ".parrot/test_runners.toml"
BUILTIN_MODULES: Mapping[str, str] = {"pytest": "pytest", "vitest": "vitest", "cargo": "cargo", "parrot-e2e": "parrot_e2e"}


class RunnerRegistry:
    """Resolve adapters by kind or argv; carries per-kind settings."""

    def __init__(self, adapters: Mapping[str, RunnerAdapter], settings: Mapping[str, Mapping[str, str]]) -> None:
        self._adapters = dict(adapters)
        self._settings = {kind: dict(value) for kind, value in settings.items()}

    def adapter_for_kind(self, kind: str) -> RunnerAdapter:
        """Raises KeyError listing the known kinds."""
        # FILL IN: lazy import of BUILTIN_MODULES[kind] via importlib.import_module(f"{__package__}.{mod}")
        #          and its module-level ADAPTER; cache in self._adapters
        raise KeyError(kind)

    def adapter_for_argv(self, argv: Sequence[str]) -> RunnerAdapter | None:
        """Normalise the launcher chain, then ask each known adapter (built-ins first, then extensions)."""
        normalized = normalize_launcher_argv(argv, pnpm_test_is_vitest=self._pnpm_test_is_vitest())
        # FILL IN: iterate kinds, return the first adapter whose matches(normalized) is True
        return None

    def settings_for(self, kind: str) -> Mapping[str, str]:
        return dict(self._settings.get(kind, {}))

    def tiers_for(self, kind: str) -> frozenset[str]:
        # FILL IN: settings "tiers" ∩ adapter.default_tiers; a tier outside the adapter's set raises ValueError
        return self.adapter_for_kind(kind).default_tiers

    def timeout_for(self, kind: str) -> int:
        return int(self._settings.get(kind, {}).get("timeout_s", DEFAULT_TIMEOUTS.get(kind, 60)))

    @property
    def binaries(self) -> tuple[str, ...]:
        # FILL IN: union of every loadable adapter's binaries, sorted
        return ()

    def _pnpm_test_is_vitest(self) -> bool:
        return str(self._settings.get("vitest", {}).get("test_script", "true")).lower() != "false"


def load_registry(worktree: Path) -> RunnerRegistry:
    """Built-ins ∪ TOML. Raises ValueError naming CONFIG_PATH on any invalid input (fail closed)."""
    path = Path(worktree) / CONFIG_PATH
    if not path.is_file():
        return RunnerRegistry({}, {})
    # FILL IN: tomllib.loads; allowed top-level keys {"runners", "extensions"}; [runners.<kind>] values
    #          stringified (tiers joined by ","); [extensions] kind = "module:Class" imported + isinstance
    #          check against RunnerAdapter; tiers ⊆ TIERS — every failure ValueError(f"{CONFIG_PATH}: …")
    return RunnerRegistry({}, {})
```
**Why**: Lazy built-in loading lets this land before the adapter modules exist; `ValueError` naming the config path is the fail-closed contract (S12).

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/__init__.py` (CREATE)
```python
"""Test runner adapters for the test-scope kernel (FEAT-709). Stdlib only."""

from .base import EXCERPT_MAX_LINES, RunnerAdapter, normalize_launcher_argv
from .registry import CONFIG_PATH, RunnerRegistry, load_registry

__all__ = ["CONFIG_PATH", "EXCERPT_MAX_LINES", "RunnerAdapter", "RunnerRegistry", "load_registry", "normalize_launcher_argv"]
```
**Why**: Do NOT import the concrete adapters here — they are lazy.

### FILL IN checklist
- [ ] `normalize_launcher_argv` — launcher loop; bounded by S3 (ambiguous ⇒ unchanged)
- [ ] `adapter_for_kind` / `adapter_for_argv` — lazy import + ordering
- [ ] `tiers_for` — intersection and ValueError on forbidden tier (S11)
- [ ] `load_registry` — TOML validation, extension import + protocol check (S12)
- [ ] tests: normaliser table, TOML override, malformed TOML, missing extension, protocol miss

---

## Acceptance Criteria

- [ ] `normalize_launcher_argv` maps `PYTHONPATH=x uv run --no-sync pytest a.py`, `python -m pytest`, `pnpm exec vitest run`, `pnpm test`, `npx vitest` to runner-headed argv.
- [ ] Malformed TOML, unknown top-level key, bad tier, unimportable or non-conforming extension ⇒ `ValueError` containing `.parrot/test_runners.toml`.
- [ ] `test_stdlib_only.py` imports `test_scope.runners` by path with no `parrot`/pydantic.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4521 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note


- Task: TASK-4521
- Feature: language-agnostic-validation-runners
- Implementation SHA: f8110ebc2594c7f8c727f357c64be19c3a50949d
- Closed at (UTC): 2026-10-20T13:38:44+00:00
- Fix commits: f8110ebc2594c7f8c727f357c64be19c3a50949d

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 159.1s · Tokens: n/a |
