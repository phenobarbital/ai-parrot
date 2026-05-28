---
id: F002
query_id: Q020
type: read
intent: Check host pyproject namespace/package configuration.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 40
parent_id: null
depth: 0
---

# F002 — Host pyproject already declares `namespaces = true`

## Summary

`packages/ai-parrot/pyproject.toml` declares `namespaces = true` under
`[tool.setuptools.packages.find]`. Setuptools' package discovery is
therefore already namespace-aware on the host side. There is no host-side
config blocker to a satellite distribution contributing modules under
`parrot.*`.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 529-532
  symbol: `tool.setuptools.packages.find`
  excerpt: |
    [tool.setuptools.packages.find]
    where = ["src"]
    include = ["parrot*"]
    namespaces = true

- path: `packages/ai-parrot/pyproject.toml`
  lines: 549-553
  symbol: `tool.maturin`
  excerpt: |
    [tool.maturin]
    python-source = "src/parrot/yaml_rs"
    module-name = "parrot.yaml_rs._yaml_rs"
    bindings = "pyo3"
    features = ["pyo3/extension-module"]

## Notes

- The Maturin Rust extension at `parrot.yaml_rs._yaml_rs` is the only
  binary component in the host package. It is unaffected by FEAT-201 —
  no embeddings/stores/rerankers code touches it.
- The new `ai-parrot-embeddings` pyproject must mirror this
  configuration: `namespaces = true` + `include = ["parrot*"]`, OR omit
  `__init__.py` at `parrot/` entirely (pure PEP 420 namespace package).
