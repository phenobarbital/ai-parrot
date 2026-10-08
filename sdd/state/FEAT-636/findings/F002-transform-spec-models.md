# F002 — `TransformSpec` and the `LinkedSource` discriminated union

- **Query**: Q004/Q007 (read)
- **Citations**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py:178-296`

- `TransformSpec` (models.py:178): **exactly one of** `ops: list[TransformOp]`
  (inline DSL) **or** `ref: TransformRef` (renderer module) — XOR enforced by a
  model_validator. A third member (e.g. a server-side recipe transformer) slots
  into this XOR naturally.
- `LinkedSource` (models.py:264) is a discriminated union on `kind`:
  `LinkedDataSource` (`kind="query_slug"`, models.py:192) |
  `DerivedDataSource` (`kind="derived"`, models.py:226). Adding a new kind is a
  supported extension seam (`LinkedSources._default_kind` already back-fills
  kind-less legacy descriptors).
- Precedent for lane asymmetry: `DerivedDataSource._ops_only` (models.py:257-261)
  **forbids `transform.ref`** because a renderer-side module cannot run in the
  Python executor — "which would break Python ↔ renderer parity". The mirror-image
  constraint applies to this proposal: a Python transformer cannot run in the TS
  renderer, so a source carrying one must fetch through the server.
