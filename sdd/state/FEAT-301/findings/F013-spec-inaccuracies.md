---
id: F013
query: Spec claim verification — inaccuracies found
type: synthesis
---

1. "frozen=True where the file uses it" → NO block models use frozen. File convention: plain BaseModel.
2. "extract_infographic_data (line 51)" → actually line 49.
3. "existing light/dark/corporate themes" → 4 themes: light/dark/corporate/midnight.
4. "environment='default'" in A2UIRenderer.render() → BaseRenderer default is 'terminal'.
5. INFOGRAPHIC_SYSTEM_PROMPT "all blocks" → only 12 of 15 documented (accordion/checklist/tab_view missing).
6. markdown_it, markupsafe "verified" → undeclared transitive dependencies.
7. A2UI v0.9.1 → conflicts with FEAT-273's locked decision to target v1.0.
8. `render()` signature in spec §6 shows `environment='default'` → actual signature uses 'terminal'.
