---
id: F030
query_id: Q030
type: read
intent: Determine which A2UI dialect/version parrot emits
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F030 — Parrot emits A2UI v1.0 (createSurface/updateComponents/updateDataModel), envelope-by-key
## Summary
Parrot's wire is A2UI **v1.0** (not v0.8/v0.9 surfaceUpdate/beginRendering/dataModelUpdate): an envelope `{"version": "v1.0", "<messageKey>": {...}}` with exactly one key among `createSurface`, `updateComponents`, `updateDataModel` (+ `deleteSurface`, `callRendererFunction`, etc.). Components are flat with catalog props at the TOP level (no nested `properties`), children by id, bindings are `{"path": "/json/pointer"}`. `version` is injected only by `serialization.serialize`. A pre-v1.0 legacy dialect (`messageType` + nested `properties` + `{"$bind"}`) is accepted read-only via `compat.py` and never emitted. No code emits v0.8 names (grep for surfaceUpdate/beginRendering/dataModelUpdate in outputs/a2ui returned nothing).
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 1-9
  symbol: `-`
  excerpt: |
    """A2UI v1.0 wire message models.
    ... an **envelope-by-key** shape (``{"version": "v1.0", "<messageKey>": {...}}``, exactly
    one message key), a top-level-props ``Component`` ...
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 446-507
  symbol: `CreateSurface`, `UpdateComponents`, `UpdateDataModel`
  excerpt: |
    surface_id: str = Field(alias="surfaceId")
    catalog_id: str | None = Field(default=None, alias="catalogId")
    send_data_model: bool = Field(default=False, alias="sendDataModel")
    components: list[Component] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")
    metadata: SurfaceMetadata | None = None
    ...
    class UpdateDataModel: surface_id; path: str | None = None; value: Any
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 695-719
  symbol: `A2UIAgentMessage`
  excerpt: |
    version: Literal["v1.0"]
    create_surface: CreateSurface | None = Field(default=None, alias="createSurface")
    update_components: UpdateComponents | None = Field(default=None, alias="updateComponents")
    update_data_model: UpdateDataModel | None = Field(default=None, alias="updateDataModel")
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py`
  lines: 54-58, 104
  symbol: `serialize`
  excerpt: |
    #: The A2UI protocol version this serialization layer emits and validates.
    VERSION_FIELD = "version"
    def serialize(message: Serializable) -> dict[str, Any]:
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/compat.py`
  lines: 1-14
  symbol: `-`
  excerpt: |
    """Read-only compatibility layer: legacy (pre-v1.0) dialect → A2UI v1.0.
    ... No emitter in this codebase uses it
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts`
  lines: 28-39, 63-78
  symbol: `WireComponent`, `CreateSurface`, `A2UIEnvelope`
  excerpt: |
    export interface A2UIEnvelope {
      version: "v1.0";
      createSurface: CreateSurface;
    }
## Implications
- The HTML5 renderer must parse the v1.0 envelope (`createSurface` with inline `components` + `dataModel` + `metadata.extensions.parrot_data_sources`), resolving children by id and `{"path"}` bindings as JSON pointers.
- `updateDataModel{path,value}` is the natural wire message to model a per-widget refresh (replace `/<source>/rows`), even though the bundled lane patches state locally.
- `a2ui-types.ts` is a ready TS mirror of the wire types that a standalone renderer can copy.
