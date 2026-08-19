---
id: F107
query: Q100, Q101, Q112
type: architecture
confidence: high
---
# F107: WS-C Fully Resolved by FEAT-273

The original spec's WS-C (A2UI Output) proposed:
- Standalone `A2UIRenderer` class
- `parrot-catalog.json` schema file
- `OutputMode.A2UI` enum member
- A2UI v0.9.1 envelope serialization

**All of this is now implemented by FEAT-273** (completed 2026-07-11):
- `OutputMode.A2UI` exists (TASK-1738)
- Catalog registry with `@register_component` (TASK-1721)
- `InfographicComponent` in catalog (TASK-1726)
- `infographic_response_to_envelope()` adapter (TASK-1739)
- `build_infographic()` typed builder (TASK-1739)
- SSR-HTML, PDF, Adaptive Cards, ECharts, Folium renderers
- Delivery bridges (Slack, Teams, deep-links)
- LLM producer with catalog-validate-retry loop (TASK-1737)

**WS-C is 100% out of scope for FEAT-301.** The only A2UI-related work
in FEAT-301 is optionally extending `_Converter.walk()` in the adapter
to handle new block types with better fidelity than the Card fallback.
