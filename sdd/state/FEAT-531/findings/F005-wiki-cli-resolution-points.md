---
id: F005
query_id: Q007
type: grep
intent: Find wikitoolkit's own model-resolution points (WIKI_MODEL / WIKI_LIGHTWEIGHT_MODEL / WIKI_EXTRACT_LLM) in wiki/cli.py
executed_at: 2026-09-06T03:11:40Z
duration_ms: 300
parent_id: null
depth: 0
---

# F005 — `wikitoolkit` (wiki/cli.py) has three independent LLM-resolution points, same pattern

## Summary

`wiki/cli.py` never defaults a provider either. Three separate spots require an explicit env
var or CLI flag and raise/skip otherwise: `_extract_into_graph` (`WIKI_EXTRACT_LLM`,
lines ~2712-2723), `_resolve_model_id` (generic "flag or env, else `ClickException`", lines
~3409-3428), and `_build_triage_adapters` (lines ~3431-3462, builds the lightweight+heavy
`PageIndexLLMAdapter` pair via `LLMFactory.create`). All three are candidate injection points
for the same shared "auto-detect and default" helper.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 2712-2715
  symbol: `_extract_into_graph`
  excerpt: |
    spec = _env_setting("WIKI_EXTRACT_LLM")
    if not spec:
        click.echo("[extract skipped: set WIKI_EXTRACT_LLM (e.g. 'anthropic:claude-haiku-4-5') to enable]")
        return None
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 3409-3428
  symbol: `_resolve_model_id`
  excerpt: |
    value = cli_value or _env_setting(env_name)
    if not value:
        raise click.ClickException(f"No model configured — pass the flag or set ${env_name} ...")
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 3431-3462
  symbol: `_build_triage_adapters`
  excerpt: |
    light_client = LLMFactory.create(lightweight_model)
    heavy_client = light_client if model == lightweight_model else LLMFactory.create(model)

## Notes

`_build_triage_adapters`'s docstring flags a same-provider constraint: `PageIndexToolkit`
pairs the heavy adapter's client with the *light* model id internally, so a default that mixes
providers between light/heavy would break — the auto-default must pick one provider for both,
matching the existing `_llm.py` docstring's same constraint for bookstore.
