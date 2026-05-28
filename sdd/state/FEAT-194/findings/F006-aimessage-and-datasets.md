---
id: F006
queries: [Q011, Q019, Q022]
confidence: medium
---

# AIMessage carries `artifacts` (loose dicts) — no first-class `datasets` field

`AIMessage` (models/responses.py:72-around 380) is the unified envelope
returned by `bot.ask()`. Relevant fields:

- `input: str` — original prompt
- `output: Any` — primary output (text / structured / DataFrame)
- `response: Optional[str]` — textual response
- `metadata: Dict[str, Any]`
- `artifacts: List[Dict[str, Any]]` — "List of artifacts created during
  processing (e.g. executed SQL queries, generated code snippets)"
  (responses.py:206-208)
- `output_mode: OutputMode` — defaults to `DEFAULT`

`add_artifact(artifact_type, content, **metadata)` (line 271-281) is the
canonical API: `artifacts.append({"type": ..., "content": ..., **metadata})`.

**`AIMessage` does NOT carry a structured `datasets` field.** Datasets are
managed agent-side via `DatasetManager` (`PandasAgent.attach_dm()` —
agent.py:1454-1476). The `DatasetManager` is session-scoped: persisted in
the user's session under `f"{agent_name}_dataset_manager"`, copied from the
agent's defaults on first access, then synced back via `attach_dm()`.

**FEAT-021 (`dataset-support-agenttalk`)** added the *input* side:
`UserObjectsHandler.configure_dataset_manager()`, plus a
`DatasetManagerHandler` for REST CRUD on the session's datasets. The
session-scoped DatasetManager is filtered by PBAC `dataset:query` policy
(agent.py:225-299). Stale `TableSource` DataFrames are evicted between
turns (`evict_table_sources()` — agent.py:1469).

**Gap**: there is no shipped path that returns the datasets that the LLM
generated *during* the turn back to the caller in the AIMessage envelope.
The user's "if the LLM produced several datasets, they must be returned so
they're available" is a genuine missing piece — the renderer would have to
emit them, the bot would have to populate `artifacts` with
`type="dataset"` entries, or the AIMessage model would need an explicit
`datasets` field.

Auto-saved Artifact (handlers/infographic.py:244-304) is the persisted
counterpart — `ArtifactType.INFOGRAPHIC` with the full `model_dump()` of
the response — but datasets are not similarly persisted by the current
infographic handler.

## Citations
- packages/ai-parrot/src/parrot/models/responses.py:72-208 — AIMessage core
  fields including `artifacts`
- packages/ai-parrot/src/parrot/models/responses.py:271-281 — `add_artifact()`
- packages/ai-parrot/src/parrot/handlers/agent.py:1449-1476 — session-scoped
  DatasetManager attachment + eviction
- sdd/specs/dataset-support-agenttalk.spec.md:1-455 — FEAT-021 (input side
  only; no return-envelope work)
