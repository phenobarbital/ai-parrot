---
id: F102
query: Q104, Q105
type: code_analysis
confidence: high
---
# F102: SectionDescriptor + InfographicAuthoringMixin Impact

**Files**:
- `packages/ai-parrot/src/parrot/tools/infographic_sections.py` (SectionDescriptor)
- `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`

## SectionDescriptor
`SectionSpec.shape` is typed `Literal["records", "scalar", "mapping", "table"]`.
This is **block-type-agnostic** — it describes the data shape feeding a template
section, not the block type the section produces. New block types do NOT require
changes to `SectionSpec` or `SectionDescriptor`.

## InfographicAuthoringMixin
The mixin delegates to `InfographicToolkit.render_data_template()` and
`render_template()`. It is **block-unaware** — it passes data to the toolkit
which resolves templates. New block types only require:
1. The block models exist in `infographic.py`
2. Templates that use those blocks are registered
3. The HTML renderer can render them

The mixin + SectionDescriptor layer is **transparent to new block types**.
No changes required there.

## Recipe Pipeline (FEAT-324)
`RecipeRunner` is also block-agnostic. It fetches data, runs transformers,
assembles a data-model, and delegates rendering to the renderer registry.
The pipeline cares about `$bind` pointers and data-model keys, not block types.
New blocks that use `$bind` (e.g. a `code` block with data-bound content)
work automatically. No RecipeRunner changes needed.
