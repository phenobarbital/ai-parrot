---
name: rust-pyo3-function
description: Implement or modify a Rust function exposed to Python via PyO3 in eo-processor. Use when adding new compute kernels, fixing numerical/shape bugs in the Rust core, or wiring Rust functions into the Python module safely and consistently.
license: Proprietary. See repository LICENSE
compatibility: Requires Rust toolchain and Python packaging via maturin; assumes NumPy arrays passed through PyO3/numpy bindings.
metadata:
  author: eo-processor maintainers
  version: "1.0"
---

# Rust + PyO3 function skill (eo-processor)

Use this skill when you need to add or change a Rust implementation that is exposed to Python. The goal is: **correct math + stable API + high performance + predictable behavior**.

## Activation checklist (before you code)

1. Identify the *public Python name* of the function (e.g., `ndvi`) and confirm whether this is:
   - a new function, or
   - a behavior change, or
   - a bug fix (no API change).
2. Find existing patterns in:
   - `src/` for Rust/PyO3 style
   - `python/eo_processor/` for exports/docstrings
   - `python/eo_processor/__init__.pyi` for typing
   - `tests/` for numerical expectations.
3. Define expected behavior for:
   - shape mismatches
   - division by zero / near-zero denominators
   - NaN/Inf handling
   - dtype support and output dtype.

If anything is ambiguous, decide based on existing functions in this repo (stay consistent).

---

## Design rules (repo conventions)

### 1) Keep the core pure
- Rust compute kernels should be **pure functions**: no file I/O, no network access, no global state.
- Deterministic results for deterministic inputs.

### 2) Validate shapes early, fail clearly
- If the function expects aligned shapes, check and raise a Python-friendly error.
- Do not silently broadcast unless the repo already does that everywhere.

### 3) Numerical stability is not optional
- For normalized differences and ratios, guard denominators with a small epsilon.
- Use a *consistent* epsilon strategy across similar functions.
- Make NaN behavior explicit (propagate vs sanitize) and match existing functions.

### 4) Avoid unnecessary allocations
- Prefer single-pass loops where possible.
- Avoid creating multiple temporaries for large rasters.
- If using ndarray operations, be mindful of intermediate allocations.

### 5) Don’t introduce `unsafe` without a compelling reason
- If you think you need `unsafe`, stop and provide:
  - justification (benchmark evidence),
  - a safety argument,
  - tests that would catch UB-like symptoms.

---

## Implementation workflow (step-by-step)

### Step A: Specify the API contract
Write down:
- signature at Python level (args, defaults, return)
- expected input shapes and dtypes
- output dtype
- error behavior & messages

Example contract for a normalized difference:
- Inputs: `a`, `b` float arrays (1D or 2D depending on existing patterns)
- Output: float array same shape
- Math: `(a - b) / (a + b + EPS)`
- Errors: shape mismatch -> `ValueError` (or the project’s standard)

### Step B: Implement Rust function with PyO3 glue
Typical structure:
1. Accept `Python` token and `PyReadonlyArray*` inputs.
2. Convert to `ndarray::ArrayView*` using `.as_array()`.
3. Validate shape compatibility.
4. Allocate output (or create new array) and fill it.
5. Return `PyArray*` via `into_pyarray(py)` (or existing conventions).

Prefer returning a new array rather than mutating inputs.

### Step C: Register with the module
- Ensure the `#[pyfunction]` is added to the module in the `#[pymodule]` initializer.
- Keep ordering, naming, and grouping consistent with neighboring functions.

### Step D: Maintain Python surface coherence
Whenever you add/rename a Rust-exposed function, you almost always need to update:
- `python/eo_processor/__init__.py` (exports and `__all__`)
- `python/eo_processor/__init__.pyi` (typing stub)
- docs (`README.md` at minimum; `docs/` if used by the repo)
- tests (`tests/`)

If the change is internal-only, do not export it publicly.

---

## Error handling guidance (PyO3)

- Prefer returning `PyResult<T>`.
- Use Pythonic errors; typical choices:
  - `ValueError` for invalid shapes/values
  - `TypeError` for wrong types (rare if signature enforces arrays)
- Error messages should be:
  - actionable
  - short
  - consistent across functions.

---

## Performance guidance

### What to optimize first
1. Avoid extra allocations / temporaries.
2. Ensure tight loops with minimal branching in the inner loop.
3. Use contiguous iteration patterns when possible.

### When to benchmark
Benchmark if:
- you’re adding a new kernel, or
- you changed the inner loop, or
- you changed dtype handling.

Don’t claim speedups without before/after numbers and array sizes.

---

## Testing expectations (what to add)

Add tests that cover:
1. **Correctness**: known inputs with known outputs (small arrays).
2. **Stability**: near-zero denominators; ensure outputs are finite if expected.
3. **Shape behavior**: mismatch raises the correct error.
4. **NaN behavior**: if inputs contain NaN, outcome matches contract.
5. **Dtype behavior**: float32/float64 if supported by project conventions.

For numerical comparisons:
- use tolerances appropriate for float64/float32
- avoid exact equality for floats unless intentionally exact.

---

## Documentation expectations

For a new EO index function, document:
- the formula
- what each band represents
- recommended input scaling (e.g., reflectance 0–1 vs scaled ints)
- typical output range and interpretation

Keep docs short in `README.md` and move deeper material to `docs/` if present.

---

## “Done” checklist (must be true before you stop)

- [ ] Rust function implemented with correct math and shape checks
- [ ] Function is registered in the PyO3 module
- [ ] Python exports updated (if public)
- [ ] Typing stubs updated (if public)
- [ ] Tests added/updated and pass
- [ ] Docs updated (if public)
- [ ] Lint/format gates pass for Rust (+ Python if touched)
- [ ] No unnecessary new dependencies

---

## Common pitfalls (avoid these)

- Returning wrong shape due to accidental broadcast or flattening
- Implicit dtype casts causing precision loss
- Division by zero producing noisy Inf/NaN without being documented
- Adding a Rust function but forgetting Python `__init__.py` / `__init__.pyi`
- Performance regressions from extra temporaries
- Changing behavior without updating tests and docs

---

## Local references (repo)

- Engineering rules & checklists: `AGENTS.md`
- User docs and API overview: `README.md`, `QUICKSTART.md`
- Existing workflows/examples: `WORKFLOWS.md`, `examples/`
- Rust crate entrypoints and module registration: `src/`
- Python exports/stubs: `python/eo_processor/`
- Tests: `tests/`
