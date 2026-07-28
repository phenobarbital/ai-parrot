# TASK-1955: Optional Rust `parrot_codec` extension + maturin `python-source` fix

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1954
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Without a GIL release, offloading compression to an executor
buys nothing (G9) — which is why large payloads currently pass through
uncompressed. This task adds the optional PyO3 extension that makes the
executor route real: `py.allow_threads()` releases the GIL while the transform
runs off-loop.

Q5 resolved: the crate ships **inside ai-parrot's existing maturin setup, next
to `parrot/yaml-rs/`** — not as a satellite crate. A prerequisite inside this
task is fixing the `python-source` hyphen/underscore discrepancy in
`packages/ai-parrot/pyproject.toml` before a second extension module is added.

The Python implementation (TASK-1954) is the executable specification: the
Rust path must pass **the exact same test suite**.

---

## Scope

- **Prerequisite**: reconcile `[tool.maturin] python-source =
  "src/parrot/yaml_rs"` (underscore) with the on-disk directory
  `packages/ai-parrot/src/parrot/yaml-rs` (hyphen). Confirm which one the
  current wheel build actually uses before changing anything, and make the
  fix without breaking the existing `parrot.yaml_rs._yaml_rs` module name.
- Add the `parrot_codec` PyO3 crate alongside `yaml-rs` and extend the maturin
  configuration to build both extension modules.
- Implement the columnar transform in Rust with a **single FFI crossing**:
  bytes/str in → parse → transform → return buffer. Wrap the transform in
  `py.allow_threads()`.
- Dispatch in `codecs/columnar.py`: detect the extension via `lazy_import`
  (`parrot/_imports.py:84`), cached at module level, logged **once at debug**
  when absent — never per call.
- **Dispatch rule**: only the bytes/str input path goes to Rust. For
  `dict`/`list` input the Python path runs — per-row `extract()` under the GIL
  can be slower than pure Python, so crossing the boundary with materialized
  Python objects is a pessimization.
- Wire `rust_available` into `BudgetRouter` so the `EXECUTOR` route becomes
  reachable.
- Parity test suite: run TASK-1954's tests against the Rust path, skipped
  cleanly when the extension is not compiled.
- Document the build (`maturin develop`) in the feature docs stub for
  TASK-1962.

**NOT in scope**:
- Rewriting `json_compact` in Rust — `MINIMAL` is inline-only by design.
- Making the Rust path mandatory. Runtime optionality (G8) is unchanged: the
  pure-Python fallback must remain fully functional.
- Publishing/CI wheel matrix changes beyond what building a second module
  requires.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/codec-rs/Cargo.toml` | CREATE | PyO3 crate manifest (`crate-type = ["cdylib"]`, `pyo3/extension-module`) |
| `packages/ai-parrot/src/parrot/codec-rs/src/lib.rs` | CREATE | `#[pymodule] parrot_codec` + columnar transform with `allow_threads` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Fix `python-source` discrepancy; register the second extension module |
| `packages/ai-parrot/src/parrot/tools/compression/codecs/columnar.py` | MODIFY | Runtime detection + bytes/str dispatch |
| `packages/ai-parrot/src/parrot/tools/compression/budget.py` | MODIFY | Feed real `rust_available` into routing |
| `packages/ai-parrot/tests/tools/compression/test_rust_parity.py` | CREATE | Parity suite + clean skip when absent |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Facts

```toml
# packages/ai-parrot/pyproject.toml — VERBATIM, lines ~617-621
[tool.maturin]
python-source = "src/parrot/yaml_rs"      # ⚠️ UNDERSCORE
module-name = "parrot.yaml_rs._yaml_rs"
bindings = "pyo3"
features = ["pyo3/extension-module"]
```

```
# On disk — VERIFIED 2026-07-27:
packages/ai-parrot/src/parrot/yaml-rs        # ⚠️ HYPHEN — does not match the config above
```

- `parrot/yaml-rs/` — PyO3 crate inside the ai-parrot package: `pyo3 0.29` +
  `extension-module`, `crate-type = ["cdylib"]`.
- `packages/navrules/` — satellite maturin/PyO3 crate (`pyo3 0.24`,
  `abi3-py311`) — the alternative placement precedent, **rejected by Q5**.
- `maturin==1.9.6` pinned as a dev dependency (root `pyproject.toml:69`).

### Verified Imports

```python
from parrot._imports import lazy_import      # verified: parrot/_imports.py:84

def lazy_import(module_path: str, package_name: str | None = None,
                extra: str | None = None) -> ModuleType: ...
```

### Does NOT Exist

- ~~`parrot_codec`~~ — you are creating it. Nothing imports it today.
- ~~`rtk` as a library crate / `rtk::filter()`~~ — RTK is a **binary** crate
  (Clap `Commands` enum in `src/main.rs`); there is nothing linkable from
  PyO3. Do not add it as a dependency.
- ~~`py.allow_threads()` reachable from pure Python~~ — GIL release exists
  ONLY inside the Rust extension.
- ~~A working `python-source` path~~ — the configured path
  (`src/parrot/yaml_rs`) does not match the on-disk directory
  (`src/parrot/yaml-rs`). Investigate before assuming either is correct;
  do not "fix" it by renaming the on-disk directory without checking what
  imports `parrot.yaml_rs`.
- ~~An `abi3` setting on the ai-parrot crate~~ — `abi3-py311` is used by
  `packages/navrules`, NOT by `yaml-rs`. Do not copy it blindly.

---

## Implementation Notes

### Pattern to Follow

```rust
// lib.rs — single FFI crossing, GIL released for the transform
#[pyfunction]
fn columnarize(py: Python<'_>, payload: &[u8], min_rows: usize) -> PyResult<Vec<u8>> {
    py.allow_threads(|| transform(payload, min_rows))
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

#[pymodule]
fn parrot_codec(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(columnarize, m)?)?;
    Ok(())
}
```

```python
# columnar.py — detection once, log once, never per call
_RUST = None
_RUST_CHECKED = False

def _rust():
    global _RUST, _RUST_CHECKED
    if not _RUST_CHECKED:
        _RUST_CHECKED = True
        try:
            _RUST = lazy_import("parrot_codec")
        except Exception:
            logger.debug("parrot_codec extension not available; using Python path")
    return _RUST
```

### Key Constraints

- Use the modern PyO3 `Bound<'py, T>` API (project Rust rule), not the
  deprecated reference patterns.
- Return `PyResult<T>`; convert Rust errors via
  `.map_err(|e| PyRuntimeError::new_err(e.to_string()))`.
- **Never cross the FFI boundary with materialized Python dicts** — that is
  the documented pessimization. Bytes/str in, buffer out.
- The Rust path must produce **byte-identical** output to the Python path for
  every input in TASK-1954's suite. Any divergence is a bug in the Rust path,
  not a "Rust variant".
- Extension absent → single `debug` log for the whole process, Python path,
  all tests green. Extension present → parity suite green.
- Adding a Rust module to the core wheel makes the build depend on the Rust
  toolchain. Runtime optionality (G8) is unchanged, but call this out in the
  Completion Note so TASK-1962 documents it.
- `cargo test` for internal Rust logic; `pytest` for the exposed API.

### References in Codebase

- `packages/ai-parrot/src/parrot/yaml-rs/` — the in-package PyO3 crate to
  model (pyo3 0.29, `crate-type = ["cdylib"]`).
- `packages/navrules/` — satellite crate structure, for reference only.
- `parrot/_imports.py:84` — `lazy_import`, the same pattern used for `faiss`
  and `sentence_transformers`.

---

## Acceptance Criteria

- [ ] `python-source` discrepancy resolved; `maturin build` succeeds and
      `import parrot.yaml_rs` still works exactly as before.
- [ ] `maturin develop` produces an importable `parrot_codec`.
- [ ] `test_rust_python_parity`: the Rust path passes TASK-1954's suite with
      byte-identical outputs; skipped cleanly when the extension is absent.
- [ ] `test_lazy_import_fallback`: extension absent → Python path, exactly one
      debug log for the process, no per-call noise.
- [ ] `dict`/`list` input never crosses the FFI boundary (assert the Rust
      function is not called for those inputs).
- [ ] With the extension present, `BudgetRouter` returns `Route.EXECUTOR` for
      over-threshold payloads; without it, `Route.PASSTHROUGH` (G9).
- [ ] Full suite green in BOTH states (extension present / absent).
- [ ] `cargo test` passes for the crate.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_rust_parity.py
import pytest

parrot_codec = pytest.importorskip(
    "parrot_codec", reason="Rust extension not compiled (maturin develop)"
)

from parrot.tools.compression import FilterLevel, get_codec


@pytest.fixture
def codec():
    return get_codec("columnar")()


class TestRustParity:
    def test_rust_python_parity(self, codec, row_oriented_payload, monkeypatch):
        """Same inputs → same outputs on both paths."""
        rust_out = codec.compress(
            _to_bytes(row_oriented_payload), level=FilterLevel.NORMAL, params={}
        )
        monkeypatch.setattr(
            "parrot.tools.compression.codecs.columnar._rust", lambda: None
        )
        py_out = codec.compress(
            _to_bytes(row_oriented_payload), level=FilterLevel.NORMAL, params={}
        )
        assert rust_out.payload == py_out.payload
        assert rust_out.lossy == py_out.lossy

    def test_dict_input_never_crosses_ffi(self, codec, row_oriented_payload, monkeypatch):
        called = []
        monkeypatch.setattr(parrot_codec, "columnarize",
                            lambda *a, **k: called.append(1))
        codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        assert not called


def test_lazy_import_fallback(monkeypatch, caplog):
    """Extension absent → Python path, one debug log, no per-call noise."""
    import parrot.tools.compression.codecs.columnar as mod
    monkeypatch.setattr(mod, "_RUST", None)
    monkeypatch.setattr(mod, "_RUST_CHECKED", False)
    with caplog.at_level("DEBUG"):
        for _ in range(10):
            mod._rust()
    assert sum("parrot_codec" in r.message for r in caplog.records) <= 1
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 6, Q5, §6 Rust/PyO3 facts, G8/G9).
2. **Check dependencies** — TASK-1954 must be in `sdd/tasks/completed/`. The
   Python suite is your specification; do not start before it is green.
3. **Verify the Codebase Contract** — inspect
   `packages/ai-parrot/src/parrot/yaml-rs/Cargo.toml` and the `[tool.maturin]`
   block, and determine how the current build resolves the mismatched
   `python-source` BEFORE changing it.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria in both states (extension present/absent).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — including the wheel-build/toolchain
   implication for TASK-1962 to document.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-07-28
**Notes**:

- **Major finding during the prerequisite investigation — changes the
  meaning of "existing maturin setup"**: the root
  `packages/ai-parrot/pyproject.toml`'s `[build-system]` is
  `setuptools.build_meta` (Cython-based), NOT maturin. The `[tool.maturin]`
  block at that file's bottom is therefore **inert/dead configuration** —
  setuptools has no knowledge of it and never invokes it. Verified
  directly: `import parrot.yaml_rs` / `import yaml_rs` both fail in this
  environment before this task (confirmed via `git stash` + fresh
  interpreter); `registry.py:19-22`'s `try: from parrot import yaml_rs /
  except ImportError: pass` silently falls back to PyYAML today. `yaml-rs`
  is actually a **fully independent, self-contained maturin sub-project**
  (its OWN `pyproject.toml` with `build-backend="maturin"`, own
  `Cargo.toml`), built by running `maturin develop`/`build` FROM WITHIN
  `src/parrot/yaml-rs/`, producing a bare-importable `yaml_rs` module (not
  `parrot.yaml_rs`) — installed into the shared venv as its own package.
  Given this, "ship inside ai-parrot's existing maturin setup, next to
  yaml-rs" (Q5) is implemented as: **mirror yaml-rs's ACTUAL working
  structure** (an independent sub-project, `packages/ai-parrot/src/parrot/codec-rs/`,
  per this task's own file table) rather than wiring through the root's
  inert `[tool.maturin]` block — migrating the ROOT build-system to
  maturin would be an invasive, high-risk change to ai-parrot's entire
  packaging pipeline (breaking Cython compilation, CI, etc.), far beyond
  "fix a hyphen/underscore mismatch," and was explicitly out of scope.
- **Prerequisite fix, scoped accordingly**: corrected the root
  `[tool.maturin]` block's `python-source`/`module-name` to describe what
  yaml-rs's OWN working config actually does
  (`python-source = "src/parrot/yaml-rs/python"`, `module-name =
  "yaml_rs"`, hyphen preserved, no `parrot.` prefix, no `_yaml_rs`
  submodule) — since the block is inert either way, this has zero runtime
  effect but corrects the documentation/discrepancy as instructed, and
  leaves a trail for a future (out-of-scope) root build-system migration.
  Extensively commented in place explaining the finding.
- **`parrot_codec` crate** (`codec-rs/`): a pure-Rust PyO3 extension
  module (no Python wrapper package, unlike yaml-rs — there is no
  "fallback to an old implementation inside the Rust package" story here,
  since `columnar.py`'s existing pure-Python path already IS the fallback)
  — `module-name = "parrot_codec"` builds directly to a bare-importable
  `parrot_codec` module. `Cargo.toml` mirrors yaml-rs (`pyo3 0.29`,
  `crate-type = ["cdylib"]`); added `serde_json`'s `preserve_order`
  feature specifically (without it, `serde_json::Map` is a sorted
  `BTreeMap` by default, which would silently violate G4's "first-seen
  column order, never sorted" determinism guarantee).
- **pyo3 0.29 API note**: the spec's own "Pattern to Follow" used
  `py.allow_threads(...)`, but pyo3 0.29 (the version this crate is pinned
  to, matching yaml-rs) renamed it to `py.detach(...)` — confirmed by a
  real compiler error (`E0599: no method named allow_threads`) and by
  reading `pyo3-0.29.0/src/marker.rs` directly. Used `detach`; documented
  the rename in a code comment so it isn't mistaken for a deviation from
  spec intent (it's the same GIL-release mechanism under a new name).
- **`columnarize_json`** implements ONLY the core transform (column
  extraction, null-column elision, constant-column factoring, positional
  row alignment) — exactly `ColumnarCodec._columnarize()`'s counterpart.
  All outer concerns (min_rows/heterogeneity/nested guards, QueryResult
  unwrapping) stay in Python; by the time Rust is invoked, Python has
  already confirmed eligibility. 9 `cargo test`s cover column ordering,
  null elision (including the "missing key counts as null" edge case),
  constant factoring (incl. the `len(rows) > 1` guard), row alignment with
  null-padding, determinism (25x repeat), and malformed-input rejection —
  all pass.
- **`columnar.py` dispatch rule, implemented exactly as specified**: only
  a `bytes`/`str` `result` (an ALREADY-serialized JSON row array or
  QueryResult-shaped object) is eligible for Rust — verified by
  `test_dict_input_never_crosses_ffi`. A bare row-array input crosses with
  the ORIGINAL bytes, no re-serialization; a QueryResult-shaped bytes
  input re-serializes only the extracted `rows` sub-array (the outer
  QueryResult shell never crosses the FFI boundary either way) — still a
  single FFI crossing for the transform itself. Added a LOCAL
  `_RUST`/`_RUST_CHECKED`/`_rust()` cache (per the task's own pattern),
  deliberately kept separate from `budget.py`'s `is_rust_available()` —
  they answer different questions (codec-local dispatch vs. router-level
  routing) even though they share an answer today.
- **`budget.py`: verified already correctly wired, NO changes made.**
  `is_rust_available()` (module-level cached detection, logged once at
  debug) and `CompressionStage`'s `self._rust_available` /
  `router.route(..., rust_available=self._rust_available)` wiring were
  BOTH already implemented in TASK-1950/1951 — re-read both files line by
  line to confirm before deciding not to touch them (Cardinal Rule: no
  scope creep / no busywork edits). Verified live:
  `is_rust_available()` now returns `True` with the extension built, and
  `BudgetRouter.route()` correctly returns `Route.EXECUTOR` for an
  over-threshold payload (was `PASSTHROUGH` before this task) — G9's
  "without Rust -> PASSTHROUGH, with Rust -> EXECUTOR" criterion verified
  both ways.
- **Built and verified for real** (not just code review): ran
  `maturin develop --release` inside `codec-rs/`; `import parrot_codec`
  works; ran the full `test_rust_parity.py` suite with the extension
  ACTUALLY PRESENT (not mocked) — byte-identical Rust vs. Python output
  confirmed for a bare row array, a QueryResult-shaped payload, and the
  heterogeneous/null-elision-only path; confirmed the Rust function is
  genuinely invoked for bytes input (a spy wrapper) and genuinely NOT
  invoked for dict/list input.
- **Necessary, documented ripple**: building the extension in THIS shared
  dev venv means `parrot_codec` is now importable process-wide, which
  flipped two PRE-EXISTING tests (TASK-1950's `test_budget.py`, TASK-1951's
  `test_stage.py`) that had hard-asserted "always absent" as an ambient
  environmental truth rather than an explicitly-forced state. Fixed both
  to force the state they actually test via monkeypatching
  (`budget_module.lazy_import` / `CompressionStage(..., rust_available=False)`)
  instead of relying on ambient reality — a strictly more correct fix,
  and necessary for `pytest` to be deterministic in ANY environment going
  forward (including CI once the extension is built there too).
- **Wheel-build/toolchain implication for TASK-1962**: `codec-rs/` is
  built SEPARATELY from the main `ai-parrot` wheel (own maturin
  sub-project, `maturin develop`/`build` run from within its directory) —
  it does NOT make the core `ai-parrot` wheel depend on the Rust
  toolchain (unlike what spec Q5's note anticipated, since that assumed
  wiring through the root's maturin config, which turned out to be
  inert). Runtime optionality (G8) is fully preserved: without running
  `maturin develop` in `codec-rs/`, `parrot_codec` is simply not
  importable and every code path already falls back to pure Python
  (verified via `test_lazy_import_fallback`). TASK-1962 should document:
  (1) `parrot_codec` is optional and built independently via
  `cd packages/ai-parrot/src/parrot/codec-rs && maturin develop --release`;
  (2) it requires the Rust toolchain (`cargo`/`rustc`) ONLY when a user
  wants the accelerated path; (3) it does not affect `pip install
  ai-parrot` at all.
- Verification: full compression suite 134/134 green (6 benchmarks
  correctly skipped) + 6/6 new Rust parity tests (running for REAL, not
  skipped, since the extension is built); `cargo test` 9/9 green;
  broader `tests/tools/`+`tests/clients/` unchanged at 51 pre-existing
  failures; `ruff check` clean on all touched Python files (one
  pre-existing, untouched `F401` in `test_stage.py`, unrelated); root
  `pyproject.toml` re-parses as valid TOML.

**Deviations from spec**: implemented `parrot_codec` as an independent
maturin sub-project (mirroring `yaml-rs`'s ACTUAL structure) rather than
wiring through the root `packages/ai-parrot/pyproject.toml`'s
`[tool.maturin]` block, because that block is inert (root build-system is
setuptools) and activating it would require migrating the entire
package's build system — far beyond this task's "fix a hyphen mismatch"
scope. `budget.py` was not modified (verified already correctly wired by
TASK-1950/1951, contrary to the task's Files table assuming it needed
changes). Two pre-existing tests (`test_budget.py`, `test_stage.py`)
needed fixing as a direct, necessary consequence of the extension now
being genuinely built in this environment — see "Necessary, documented
ripple" above.
