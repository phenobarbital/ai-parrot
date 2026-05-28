---
id: F004
query_id: Q004
type: grep
intent: Verify parrot-formdesigner is/isn't a hard dependency of ai-parrot
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F004 — `parrot-formdesigner` is NOT declared as a dependency of `ai-parrot`

## Summary

`grep "formdesigner" packages/ai-parrot/pyproject.toml` returns zero
matches in dependency tables. The workspace root `pyproject.toml`
declares `ai-parrot`, `ai-parrot-tools`, `ai-parrot-loaders`,
`ai-parrot-pipelines` as workspace members but does NOT pull in
`parrot-formdesigner`. This explains why the shim has the local
fallback — it cannot assume the package is installed.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 542
  excerpt: |
    "parrot.forms.renderers" = ["templates/*.j2"]

- path: `pyproject.toml`
  lines: 13-18, 117-122
  excerpt: |
    dependencies = [
        "ai-parrot",
        "ai-parrot-tools",
        "ai-parrot-loaders",
        "ai-parrot-pipelines",
    ]
    ...
    [tool.uv.sources]
    ai-parrot = { workspace = true }
    ai-parrot-tools = { workspace = true }
    ai-parrot-loaders = { workspace = true }
    ai-parrot-pipelines = { workspace = true }

## Notes

`parrot-formdesigner` IS a workspace member (it lives under
`packages/parrot-formdesigner/`) so `uv sync` builds it, but no
`pyproject.toml` lists it as a runtime dep. Removing the shim's
fallback requires either:
  (a) adding `parrot-formdesigner` to the appropriate extras of
      `ai-parrot` (likely under `integrations` or a new `forms` extra), OR
  (b) extracting msteams into `ai-parrot-integrations` and declaring
      the dep only there.
