# F009 — Dashboard model: sharing flag + module scope + a natural feature-flag seam

**Query:** Q009 (grep + read, navigator-api)
**Citations:** `navigator-api/resources/dashboards/models.py` :: `Dashboard`
  (table `<NAVIGATOR_SCHEMA>.dashboards`); handlers at `resources/dashboards/handlers.py`
**Confidence:** high (direct source read)

## Confirms the entity model of brainstorm §1

```python
dashboard_id: UUID = Column(primary_key=True)   # scheduling scope key (metadata.dashboard_id)
name / description / slug
shared: bool = Column(default=False)            # sharing already a first-class flag
published: bool
module_id: int ; program_id: int                # module scope EXISTS
allow_widgets: bool ; widget_location: jsonb    # widget layout
dashboard_type: str
params: jsonb ; attributes: jsonb ; conditions: jsonb
user_id: int ; created_by: int                  # ownership for permissions
```

- `dashboard_id` as the scheduling scope key (§4.1.C) is **confirmed viable**.
- `shared: bool` confirms §3.4 — sharing is a modeled property, not ad-hoc.
- `module_id` gives the "module-level sharing extension" (§3.4) a real anchor: modules
  already exist as a scope, so the extension is a scoping change, not a new concept.
- `user_id` / `created_by` supply the permission hooks the thin NavAPI wrapper needs.

## Feature-flag seam for the user's coexistence requirement

The user's constraint — *keep `v1-html` supported, add `v2-a2ui` alongside, no
replacement* — has two ready-made slots on this model, requiring **no migration**:

- `dashboard_type: str` — an existing discriminator column, or
- `attributes: jsonb` / `params: jsonb` — schemaless, ideal for
  `{"artifact_type": "v1-html" | "v2-a2ui", "notifications": {...}}`

Recommended: `attributes.artifact_type`, defaulting to `v1-html` when absent, so every
existing dashboard keeps working untouched and the refresh function dispatches on it.
Combined with `RenderedArtifact` (F007) as the common output type, this makes the
coexistence requirement a dispatch detail rather than an architectural fork.

## Remaining unknown

No widget/iframe entity appears in this module — `Dashboard` carries only
`allow_widgets` + `widget_location`. The **widget → artifact URL resolution** (brainstorm
§4.1.A step 1) is therefore NOT yet located; widgets live in another table/module.
Carried into Open Questions.
