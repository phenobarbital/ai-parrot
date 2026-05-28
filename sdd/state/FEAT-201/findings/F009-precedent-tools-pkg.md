---
id: F009
query_id: Q014
type: read
intent: Inspect ai-parrot-tools pyproject as the per-backend-extras precedent.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 70
parent_id: null
depth: 0
---

# F009 — `ai-parrot-tools` is the per-backend-extras precedent to mirror

## Summary

`ai-parrot-tools` is the closest analog for the FEAT-201 packaging shape:
a satellite distribution with one extra per backend, depending on
`ai-parrot` for the abstract base classes, using setuptools + uv
workspace. **However**, it ships under a separate top-level
(`parrot_tools.*`) and is bridged into `parrot.tools.*` via a sys.meta_path
redirector in core — exactly the convention FEAT-201 deliberately breaks.

## Citations

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 1-31
  symbol: project metadata + core deps
  excerpt: |
    [build-system]
    requires = ["setuptools>=67.6.1", "wheel>=0.44.0"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "ai-parrot-tools"
    dynamic = ["version"]
    ...
    dependencies = [
        "ai-parrot>=0.24.56",
        "PyGithub>=2.1",
    ]

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 33-72
  symbol: per-backend extras
  excerpt: |
    [project.optional-dependencies]
    pdf = [...]
    jira = ["jira>=3.10"]
    slack = ["slack-sdk>=3.0"]
    aws = ["boto3>=1.28"]
    docker = ["docker>=7.1"]
    git = ["gitpython>=3.1"]
    ...
    all = [
        "ai-parrot-tools[jira,pdf,msword,slack,aws,docker,git,analysis,excel,sandbox,codeinterpreter,pulumi,sitesearch,office365,scraping,finance,db,flowtask,google,arxiv,wikipedia,weather,messaging,security]"
    ]

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 81-87
  symbol: `tool.setuptools.packages.find` — separate top-level
  excerpt: |
    [tool.setuptools.dynamic]
    version = {attr = "parrot_tools.__version__"}

    [tool.setuptools.packages.find]
    where = ["src"]
    include = ["parrot_tools*"]

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 91-92
  symbol: `tool.uv.sources`
  excerpt: |
    [tool.uv.sources]
    ai-parrot = { workspace = true }

## Notes

- FEAT-201's `ai-parrot-embeddings` pyproject should reuse this shape
  (`[build-system]`, `[project]`, per-backend extras, `all` aggregator,
  `[tool.uv.sources] ai-parrot = workspace`), but the
  `[tool.setuptools.packages.find]` block must differ:
  - sibling precedent: `include = ["parrot_tools*"]` (own top-level)
  - FEAT-201 choice:   `include = ["parrot*"]` + `namespaces = true`
    (contributes under existing `parrot.*` namespace)
