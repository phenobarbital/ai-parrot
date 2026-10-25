---
id: F012
query_id: Q012
type: read
intent: "Collect the repo's Rust/PyO3/maturin packaging precedents and native-artifact handling for the Rust phase"
executed_at: 2026-10-25T11:00:00Z
duration_ms: 5000
parent_id: null
depth: 0
---

# F012 — Three PyO3 extensions already ship (navrules, parrot_codec, yaml_rs); worktrees and release pipeline know how to handle them; no THIRD_PARTY.md exists

## Summary

`packages/navrules/rust/Cargo.toml` is a maturin-built `cdylib` with `pyo3 0.29` + `abi3-py311`, `serde`/`serde_json`, and an `extension-module` feature kept off for `cargo test`; `packages/ai-parrot/src/parrot/codec-rs` and `yaml-rs` are self-contained maturin sub-projects (`pyo3 0.29`, `serde_json` with `preserve_order` for determinism). Root `pyproject.toml` `[tool.parrot.worktree]` declares `native_group`s whose `.so` files `ensure_worktree` copies into worktrees and auto-builds via `make -C packages/navrules build-rust-wheel` (never `maturin develop`). `release.yml` builds navrules wheels with `PyO3/maturin-action@v1` across a target/manylinux matrix. The repo root has only `LICENSE`: no `THIRD_PARTY.md` or `NOTICE` file exists yet for attributed derived code.

## Citations

- path: `packages/navrules/rust/Cargo.toml`
  lines: 1-30
  symbol: `navrules_native`
  excerpt: |
    crate-type = ["cdylib", "rlib"]
    pyo3 = { version = "0.29", features = ["abi3-py311"] }
    serde_json = "1.0"
    [features]
    extension-module = ["pyo3/extension-module"]
    default = []

- path: `packages/ai-parrot/src/parrot/codec-rs/Cargo.toml`
  lines: 8-17
  symbol: `parrot_codec`
  excerpt: |
    crate-type = ["cdylib"]
    pyo3 = { version = "0.29", features = ["extension-module"] }
    serde_json = { version = "1.0", features = ["preserve_order"] }   # determinism guarantee (G4)

- path: `packages/ai-parrot/src/parrot/codec-rs/pyproject.toml`
  lines: 1-20
  symbol: `[tool.maturin]`
  excerpt: |
    build-backend = "maturin"
    [tool.maturin]
    module-name = "parrot_codec"
    bindings = "pyo3"

- path: `pyproject.toml`
  lines: 294-320
  symbol: `[tool.parrot.worktree]`, `[[tool.parrot.worktree.native_group]]`
  excerpt: |
    [[tool.parrot.worktree.native_group]]
    name = "navrules-pyo3"
    copy_globs = ["packages/navrules/src/navrules/_native/*.so"]
    abi_scoped = false
    build = ["make", "-C", "packages/navrules", "build-rust-wheel"]

- path: `packages/navrules/Makefile`
  lines: 16-28
  symbol: `build-rust-wheel`
  excerpt: |
    uv run --no-sync --with maturin maturin build --release --locked --out "$$tmp"; \
    [extract .so members into src]

- path: `.github/workflows/release.yml`
  lines: 387-392
  symbol: `Build wheel (PyO3/maturin-action@v1)`
  excerpt: |
    - name: Build wheel
      uses: PyO3/maturin-action@v1
      with:
        working-directory: packages/navrules
        manylinux: ${{ matrix.manylinux }}

- path: `LICENSE`
  lines: 1
  symbol: repo root licence files
  excerpt: |
    ls THIRD_PARTY* NOTICE* → no such file; only LICENSE exists

## Notes

A Rust compiler phase must add a `native_group`, a Makefile `build-rust-wheel` target, a release matrix job, and create `THIRD_PARTY.md` with the SemaFlow MIT header before the first derived line lands (brainstorm constraint).
