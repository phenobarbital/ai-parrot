---
id: F011
query_id: Q011
type: grep
intent: A2UI wire models
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F011 — models.py — Action, EventAction, CheckRule, DataBinding, ActionMessage, CreateSurface

## Summary

`Action` = exactly one of `event: EventAction{name, userMessage?, context}` or `functionCall`. `CheckRule{condition: FunctionCall|DataBinding, message}`. `DataBinding.path` must be a valid JSON Pointer. `CreateSurface{surfaceId, catalogId?, components, dataModel}`. Renderer→agent `ActionMessage{name, surfaceId, sourceComponentId, timestamp, context, dataModel?}` (`dataModel` attached when the surface was created with `sendDataModel: true`). `ErrorMessage` can carry `surfaceId`+`path` for data-model-path errors. Also `UpdateComponents`, `UpdateDataModel`, `DeleteSurface`.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 232-270
  symbol: `EventAction / Action`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 272-292
  symbol: `CheckRule`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 155-175
  symbol: `DataBinding`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 446-520
  symbol: `CreateSurface / UpdateComponents / UpdateDataModel / DeleteSurface`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 585-617
  symbol: `ActionMessage`
  excerpt: |
    name: str
    surface_id: str = Field(alias="surfaceId")
    source_component_id: str = Field(alias="sourceComponentId")
    context: dict[str, Any]
    data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 648-690
  symbol: `ErrorMessage`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 446-470
  symbol: `CreateSurface.send_data_model`
  excerpt: |
    send_data_model: bool = Field(default=False, alias="sendDataModel")
    components: list[Component] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")
