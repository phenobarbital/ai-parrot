---
id: F004
query_id: Q004/Q005
type: read
intent: Locate local MCP configuration and existing Rust/PyO3/Maturin patterns
executed_at: 2026-09-05T13:52:00Z
depth: 0
parent_id: null
---

# F004 — Local MCP exposure and PyO3 packaging already exist, but Obscura is absent

## Summary

Local MCP toolkits are configured through `.parrot/mcp-toolkits.yaml` using an importable `AbstractToolkit` class, constructor kwargs, tool filtering, and environment variables; built-in scraping and browsing toolkits already use this path. The `navrules` package demonstrates a maturin-managed PyO3 extension with an `abi3-py311` Rust dependency. Repository search found no existing Obscura integration, dependency, crate, or configuration entry in the project files searched.

## Citations

- path: `docs/mcp-local-toolkits.md`
  lines: 45-81, 99-105, 109-115
  symbol: `mcp-toolkits.yaml` schema and built-ins
  excerpt: |
    toolkits:
      <name>:
        class: <dotted.path.to.AbstractToolkitSubclass>
        kwargs: {}
        env: {}
    `scraping` and `browsing` are built-in toolkit entries.

- path: `packages/navrules/pyproject.toml`
  lines: 1-4, 40-44
  symbol: `tool.maturin`
  excerpt: |
    build-backend = "maturin"
    [tool.maturin]
    python-source = "src"
    manifest-path = "rust/Cargo.toml"
    features = ["pyo3/extension-module"]

- path: `packages/navrules/rust/Cargo.toml`
  lines: 8-23
  symbol: `navrules_native` dependencies and features
  excerpt: |
    crate-type = ["cdylib", "rlib"]
    pyo3 = { version = "0.29", features = ["abi3-py311"] }
    extension-module = ["pyo3/extension-module"]

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`
  lines: 1-12
  symbol: `DriverFactory`
  excerpt: |
    Provides the single entry point for obtaining an AbstractDriver.

## Notes

PyO3 support proves packaging precedent, not feasibility of embedding Obscura. The upstream crate API, V8 linkage, platform artifacts, and async/threading model must be evaluated before proposing a native binding as the first milestone.
