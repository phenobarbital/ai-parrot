---
id: F106
query: Q109
type: code_analysis
confidence: high
---
# F106: Undeclared Dependencies (Still)

**File**: `packages/ai-parrot-visualizations/pyproject.toml`

The following are imported in `infographic_html.py` but NOT declared:
- `markdown-it-py` (imported as `markdown_it`, line 15)
- `markupsafe` (line 16)
- `orjson` (line 13)

All are available as transitives via `ai-parrot` core, but best practice
is to declare them explicitly. This finding is unchanged from run-1 (F011).

`nh3` is correctly handled as optional (try/except, lines 20-25).

**Action**: Declare `markdown-it-py>=3.0`, `markupsafe>=2.1`, `orjson>=3.9`
in `ai-parrot-visualizations/pyproject.toml` `dependencies` list.
