# F004 — Recipe transformer contract (FEAT-324/528)

- **Query**: Q002/Q008 (wiki_query + wiki_page)
- **Citations**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py`;
  `packages/ai-parrot/src/parrot/tools/infographic_recipes/loader.py`

- `@infographic_transformer(name, requires_columns, description, params_schema)`
  registers a **pure function `(inputs: dict, params: dict) -> dict`** in the
  process-wide `transformer_registry` by import side effect.
- **G1 invariant**: recipes reference transformations **by registered name — never
  stored/executed code**. No dynamic import of user-supplied dotted paths. Any
  linked-surface extension must preserve this: the descriptor carries a name, the
  server resolves it against its in-process registry.
- `TransformerManifest` (requires_columns per input alias, params_schema) powers a
  fail-fast validation gate (`validate_inputs`) and LLM discovery — reusable as-is
  for validating a linked descriptor at build time.
- `load_transformer_module(path)` (loader.py) is the host contract for registering a
  recipe package's transformers without importing the agent (idempotent, lock-guarded).
- `RecipeRunner` (parrot/tools/infographic_recipes/, FEAT-324 M5) runs recipe
  pipelines (data stage → transform steps → envelope); `RecipeRunException.error.stage`
  distinguishes data (502) vs transform (422) failures in the handler.
