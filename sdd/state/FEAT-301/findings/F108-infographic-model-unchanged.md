---
id: F108
query: Q114
type: code_analysis
confidence: high
---
# F108: infographic.py Model Unchanged Since Run-1

`git log --since=2026-07-10 -- packages/ai-parrot/src/parrot/models/infographic.py`
returned **zero commits**. The model file is untouched since the original proposal.

Current state (confirmed):
- `BlockType` enum: 15 members (title through tab_view)
- `ThemeConfig`: 12 color tokens + font_family
- `ThemeRegistry`: 4 built-in themes (light, dark, corporate, midnight)
- No `I18nText`, no `DocumentMeta`, no `CodePalette`, no `MethodBadgePalette`
- No `frozen=True` on any block model (convention confirmed)
- `_CSS_COLOR_RE` validator on all color fields

The extension surface is clean: all new fields would be Optional with None
defaults, maintaining backward compatibility.
