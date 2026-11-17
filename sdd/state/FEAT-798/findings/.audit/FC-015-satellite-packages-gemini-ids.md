---
id: FC-015
query_id: Q024
type: grep
intent: "Gemini ids in the embeddings satellite (google embeddings / document-understanding paths) that may pin 2.5."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-015 — No 2.5 id in embeddings, loaders, tools or integrations src; those satellites already use 3.x ids

## Summary

Quoted Gemini ids in `ai-parrot-embeddings`, `ai-parrot-loaders`, `ai-parrot-tools` and `ai-parrot-integrations` src: `gemini-embedding-001` (embeddings), `gemini-3.1-pro-preview` (video understanding), `gemini-3.1-flash-image` (image understanding), `gemini-3.8-flash` ×2 (computer-use agent). None pins a 2.5 id; the satellites need no change for the retirement.

## Citations

- path: `packages/ai-parrot-embeddings/src/parrot/embeddings/google.py`
  lines: 10-10
  symbol: (embedding model default)
  excerpt: |
    "gemini-embedding-001"

- path: `packages/ai-parrot-loaders/src/parrot_loaders/videounderstanding.py`
  lines: 121-121
  symbol: (loader default)
  excerpt: |
    "gemini-3.1-pro-preview"

- path: `packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py`
  lines: 98-98
  symbol: (loader default)
  excerpt: |
    "gemini-3.1-flash-image"

- path: `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py`
  lines: 76-76, 104-104
  symbol: (computer-use agent default)
  excerpt: |
    "gemini-3.8-flash"

## Notes

- Core `parrot/loaders/abstract.py` (not a satellite) still pins `gemini-2.5-flash-lite` four times — see FC-001.
