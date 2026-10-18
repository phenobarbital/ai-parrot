---
id: F003
query_id: Q002,Q007
type: grep
intent: "Find the declared google-genai pin across workspace pyprojects and the SDK surface used"
executed_at: 2026-10-15T17:44:00Z
parent_id: null
depth: 0
---

# F003 — Two divergent google-genai pins; SDK surface is `genai.Client` + `genai.types`

## Summary

Only **two** distributions pin the SDK, and they disagree:
`ai-parrot-client-google` requires `>=2.23.0` while `ai-parrot-embeddings`
still sits at `>=2.18.1`. Core `ai-parrot` deliberately carries no pin
(FEAT-523 removed a stray one). The venv currently resolves **2.24.0**. All
pins are floors (`>=`), never ceilings, so a bump is a floor raise, not an
unpinning. The SDK surface is narrow and concentrated: `from google import
genai` plus `from google.genai import types` across 9 modules, with
`google.genai.errors` used only by the reel error mapper.

## Citations

- path: `packages/ai-parrot-client-google/pyproject.toml`
  lines: 27
  symbol: `dependencies`
  excerpt: |
    "google-genai>=2.23.0",

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: 49-55
  symbol: `dependencies`
  excerpt: |
    # google-genai SDK (`from google import genai`). google-cloud-aiplatform is
    # ... to google-genai only; add a dedicated `vertex` extra if Vertex SDK use is
    "google-genai>=2.18.1",

- path: `packages/ai-parrot/pyproject.toml`
  lines: 508
  symbol: `dependencies` (comment)
  excerpt: |
    # FEAT-523: google-genai removed — it was a stray pin core never imported

- path: `pyproject.toml`
  lines: 130
  symbol: workspace root (comment)
  excerpt: |
    # google-cloud-aiplatform>=1.153 (needed for google-genai>=2.6) requires

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 23-33
  symbol: SDK imports
  excerpt: |
    from google import genai
    from google.genai.types import (
    from google.genai import types

- path: `packages/ai-parrot-embeddings/src/parrot/embeddings/google.py`
  lines: 29-56
  symbol: `GoogleEmbedding`
  excerpt: |
    from google import genai
    from google.genai import types

## Notes

Installed version measured with `uv pip show google-genai` → `2.24.0`,
`Required-by: ai-parrot-client-google, google-cloud-aiplatform`. The
`google-cloud-aiplatform` coupling noted at the workspace root is the known
constraint on how far the floor can move.
