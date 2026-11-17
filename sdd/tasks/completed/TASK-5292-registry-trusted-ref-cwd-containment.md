# TASK-5292: Runner registry reads from a trusted git ref; runner cwd stays inside the worktree

**Feature**: FEAT-834 — runner registry loads from a trusted ref; runner cwd stays in the worktree
**Spec**: `sdd/specs/runners-registry-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:29e8e7ad138f`

---

## Context

Spec §1-§2 (Module 1). `load_registry(worktree)` reads `.parrot/test_runners.toml` from the working tree and
`_extension_adapter` imports + constructs every `[extensions]` entry. Engine-process callers pass a
seat-writable attempt worktree, so a seat can make the engine import a module. This task adds an optional
trusted `ref` (read the TOML from git, never from the working tree) and rejects runner `cwd` values that leave
the worktree. TASK-5293 then makes the engine callers pass the ref.

---

## Scope

- `load_registry(worktree, *, ref=None)`:
  - `ref is None` → unchanged behaviour.
  - `ref` set → empty or `-`-prefixed `ref` raises `ValueError`; `git rev-parse --verify --quiet <ref>^{commit}`
    failing raises `ValueError`; `git cat-file -e <ref>:.parrot/test_runners.toml` failing returns
    `RunnerRegistry({}, {})`; otherwise `git show <ref>:.parrot/test_runners.toml` content goes through the
    same parse/validate path as the file read.
- At load time, any runner setting `cwd` that is absolute, or whose `posixpath.normpath` is `..` or starts with
  `../`, raises `ValueError(f"{CONFIG_PATH}: runner {kind!r} cwd must stay inside the worktree")`.
- `VitestAdapter._contained_cwd(worktree, settings) -> Path`: resolve `worktree / settings["cwd"]`, raise
  `ValueError` unless it is inside `worktree.resolve()`. Use it in `mirror_targets` and `invocation`
  (`invocation` keeps returning the original relative `settings["cwd"]` string in `Invocation.cwd`).
  `validate_settings` returns `["vitest: cwd must stay inside the worktree"]` for an escaping cwd (no raise).
- New tests listed under Test Specification.

**NOT in scope**: guard.py, background.py, engine.py (TASK-5293); the TOML schema; seat-side callers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py` | MODIFY | `ref=` support, cwd validation |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py` | MODIFY | `_contained_cwd` + uses |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py` | MODIFY | ref + cwd tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py` | MODIFY | escaping-cwd test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# registry.py today (lines 5-12): importlib, tomllib, Mapping, Sequence, Path, Any, TIERS, DEFAULT_TIMEOUTS,
# RunnerAdapter, normalize_launcher_argv. Add ONLY stdlib: `import posixpath`, `import subprocess`.
# vitest.py today (lines 5-10): Mapping, Sequence, Path, Invocation, RunReport, TestTarget, TIERS, ScopePolicy,
# parse_junit_report. No new imports needed.
from parrot.flows.dev_loop.test_scope.runners import RunnerRegistry, load_registry  # tests: test_runners_registry.py:10
```

### Existing Signatures to Use
```python
CONFIG_PATH: str = ".parrot/test_runners.toml"                    # registry.py:14
class RunnerRegistry:                                              # registry.py:23
    def __init__(self, adapters: Mapping[str, RunnerAdapter], settings: Mapping[str, Mapping[str, str]]) -> None
def _settings_from_toml(raw_settings: Mapping[str, Any]) -> dict[str, str]:   # registry.py:101
def _extension_adapter(kind: str, target: object) -> RunnerAdapter:          # registry.py:117
def load_registry(worktree: Path) -> RunnerRegistry:                          # registry.py:133 (1 occurrence)
        tiers = setting.get("tiers")                                          # registry.py, 1 occurrence
class VitestAdapter:                                                          # vitest.py:16
    def mirror_targets(self, changed, *, worktree: Path, settings) -> list[str]  # vitest.py:42; cwd at :44
    def invocation(self, targets, *, distribution, worktree, settings, policy, report_path) -> Invocation  # :66; cwd=settings["cwd"] at :86
    def validate_settings(self, settings, *, worktree: Path) -> list[str]   # vitest.py:114; package.json check at :120
```

### Does NOT Exist
- No `trusted_ref`/`ref` parameter on `load_registry` yet, no `RunnerRegistry.from_git`, no `load_registry_from_ref`.
- No `_contained_cwd` or other cwd helper in `runners/base.py` or `vitest.py`.
- No git helper module inside `test_scope/runners/`; call `subprocess.run` directly (stdlib only — `test_stdlib_only.py`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py#load_registry",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py#_extension_adapter",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py#VitestAdapter"
  ]
}
```

---

## Implementation Notes

- Fail closed: a bad ref must raise, never fall back to the working tree — the fallback is exactly the hole.
- Reject `-`-prefixed refs before calling git — because `git show -x:path` would be parsed as an option.
- Validate `cwd` at load time too (not only in vitest) — because other adapters and `Invocation.cwd` consumers
  receive the setting as-is.

---

## Implementation Blueprint

### `registry.py`
```python
# REPLACE `def load_registry(worktree: Path) -> RunnerRegistry:` (verified: registry.py:133, occurrences: 1)
def _read_config_at_ref(worktree: Path, ref: str) -> str | None:
    """Return the TOML text committed at ``ref``, or None when the file is absent there."""
    if not ref or ref.startswith("-"):
        raise ValueError(f"{CONFIG_PATH}: invalid trusted ref {ref!r}")
    def _git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=worktree, capture_output=True, text=True, check=False)
    if _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        raise ValueError(f"{CONFIG_PATH}: trusted ref {ref!r} does not resolve to a commit")
    if _git("cat-file", "-e", f"{ref}:{CONFIG_PATH}").returncode != 0:
        return None
    shown = _git("show", f"{ref}:{CONFIG_PATH}")
    if shown.returncode != 0:
        raise ValueError(f"{CONFIG_PATH}: unable to read at {ref!r}: {shown.stderr.strip()}")
    return shown.stdout


def load_registry(worktree: Path, *, ref: str | None = None) -> RunnerRegistry:
    """Load TOML settings and extensions, failing closed for every invalid input.

    Args:
        worktree: Checkout the registry belongs to.
        ref: When set, read the TOML committed at this git ref instead of the working tree.
            Engine-process callers pass the attempt base so a seat-written file is never imported.
    """
    if ref is not None:
        text = _read_config_at_ref(Path(worktree), ref)
        if text is None:
            return RunnerRegistry({}, {})
    else:
        path = Path(worktree) / CONFIG_PATH
        if not path.is_file():
            return RunnerRegistry({}, {})
        # FILL IN: keep the existing read_text + TOMLDecodeError handling, parse `text` once for both branches
    # ... existing body unchanged from `if not isinstance(data, dict) ...` onward
```

```python
# INSERT before `        tiers = setting.get("tiers")` (occurrences: 1)
        cwd = setting.get("cwd")
        if cwd is not None:
            normalized = posixpath.normpath(cwd.replace("\\", "/"))
            if posixpath.isabs(normalized) or Path(cwd).is_absolute() or normalized == ".." or normalized.startswith("../"):
                raise ValueError(f"{CONFIG_PATH}: runner {kind!r} cwd must stay inside the worktree")
```

### `vitest.py`
```python
    @staticmethod
    def _contained_cwd(worktree: Path, settings: Mapping[str, str]) -> Path:
        """Return the resolved runner cwd, refusing one outside ``worktree``."""
        root = Path(worktree).resolve()
        cwd = (root / settings["cwd"]).resolve()
        if cwd != root and root not in cwd.parents:
            raise ValueError(f"vitest: cwd {settings['cwd']!r} must stay inside the worktree")
        return cwd
```
- `mirror_targets`: replace line 44 with `cwd = self._contained_cwd(worktree, settings)`.
- `invocation`: call `self._contained_cwd(worktree, settings)` before building argv; keep `cwd=settings["cwd"]`.
- `validate_settings`: after the "cwd is required" check, `try: self._contained_cwd(...) except ValueError: return ["vitest: cwd must stay inside the worktree"]`.

**Why**: `Path.resolve()` follows symlinks, so a symlinked dir pointing outside is also refused.

### FILL IN checklist
- [ ] Single parse path for file and ref text (no duplicated validation).
- [ ] Tests from Test Specification.

---

## Acceptance Criteria

- [ ] AC-1 With `ref` set, a working-tree-only `[extensions]` entry is never imported.
- [ ] AC-2 Unknown / `-`-prefixed ref → `ValueError`; ref without the file → built-ins only.
- [ ] AC-3 Absolute or escaping `cwd` rejected by `load_registry` and by `VitestAdapter`.
- [ ] Existing tests in both test files and `test_stdlib_only.py` still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

- `test_load_registry_from_ref_ignores_working_tree_toml`: `git init` in `tmp_path`, commit a TOML with
  `[runners.pytest] timeout_s = 7`, then overwrite the working-tree TOML with `[extensions] evil = "evil_mod:Evil"`
  where `evil_mod` (on `sys.path` via monkeypatch) records construction; `load_registry(wt, ref="HEAD")` returns
  `timeout_for("pytest") == 7` and `evil_mod` was never imported.
- `test_load_registry_from_ref_without_config_is_empty`: committed tree has no TOML, working tree has one.
- `test_load_registry_rejects_bad_ref`: `ref="nope"` and `ref="--output=x"` raise `ValueError`.
- `test_load_registry_rejects_escaping_cwd`: parametrize `"/etc"`, `"../x"`, `"a/../../x"`.
- `test_vitest_rejects_cwd_outside_worktree`: `mirror_targets`/`invocation` raise, `validate_settings` returns the diagnostic.

Git in tests: set `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env or `-c user.name=t -c user.email=t@t` so commits work on CI.

---

## Agent Instructions

1. Work in `feat-FEAT-834-runners-registry-fixes`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Implement from the Blueprint, run the Validation Commands.
3. Commit only the listed files; close with `parrot sdd task close TASK-5292 runners-registry-fixes verified`.

---

## Completion Note

**Completed**: 2026-11-07 — commit a5d34546f1 (resolves `issue:29e8e7ad138f` together with TASK-5293).

`load_registry(worktree, *, ref=None)`: with `ref`, the TOML is read via `git show <ref>:.parrot/test_runners.toml`
(empty/`-`-prefixed/unresolvable ref → `ValueError`, absent file → built-ins); one parse path for both sources.
`_check_cwd` rejects absolute or escaping runner `cwd` at load time; `VitestAdapter._contained_cwd` (resolves
symlinks) guards `mirror_targets`, `invocation` and reports in `validate_settings`. 42 tests passed
(registry, vitest, stdlib-only); ruff + black clean.
