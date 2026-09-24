---
id: F011
query_id: Q011
type: read
intent: Understand the optional extras pattern for new backend dependencies
executed_at: 2026-09-21T22:15:00Z
depth: 0
parent_id: null
---

# F011 — Optional extras pattern for new backends

## Summary

The project uses optional extras in pyproject.toml for backend dependencies (e.g., `ai-parrot[pgvector]`, `ai-parrot-embeddings[milvus,huggingface]`). TASK-1376 and TASK-1337 established the redistribution pattern after the workspace split. `ai-parrot[needle]` and `ai-parrot[llamacpp]` would follow this same pattern — declared as optional dependency groups in the core `ai-parrot` package's pyproject.toml, with the backend implementations lazily loaded behind the extra.

## Citations

- path: `sdd/tasks/completed/TASK-1376-update-host-pyproject.md`
  excerpt: |
    Update host pyproject.toml — extras redistribution

- path: `sdd/tasks/completed/TASK-1337-host-pyproject-redistribute-extras.md`
  excerpt: |
    Redistribute host pyproject extras after the move

## Notes

The `cactus-needle` pip package is Apache-2.0 and would be the `[needle]` extra. For llama.cpp, `llama-cpp-python` is the standard binding. Both are optional — the delegate protocol is backend-agnostic, and ImportError at construction time is the expected failure mode when the extra is not installed. This matches how `ai-parrot-embeddings[huggingface]` works.
