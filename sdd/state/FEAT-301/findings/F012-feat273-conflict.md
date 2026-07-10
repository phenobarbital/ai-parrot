---
id: F012
query: FEAT-273 A2UI implementation spec relationship
type: read
path: sdd/specs/a2ui-implementation.spec.md
---

FEAT-273 (status: approved) is the platform-wide A2UI adoption spec.
- Targets A2UI v1.0 (locked decision D3: "no legacy interop needed").
- Creates centralized `parrot.outputs.a2ui` package with envelope models,
  catalog registry, renderer registry, mandatory lowering pass.
- TASK-1720 (pending) already decomposed for envelope models.
- InfographicToolkit is listed in CR-1 inventory as "Replace" target.

This spec (FEAT-301 draft) targets A2UI v0.9.1 and creates a standalone
A2UIRenderer in `parrot/outputs/formats/a2ui.py`. This conflicts with:
1. Version: v0.9.1 vs v1.0
2. Architecture: standalone renderer vs centralized catalog+registry
3. Envelope models: fresh models vs FEAT-273's shared models in parrot.outputs.a2ui
4. Catalog: standalone parrot-catalog.json vs FEAT-273's @register_component registry

WS-C must be reconciled with FEAT-273 or risk creating parallel A2UI infrastructure.
