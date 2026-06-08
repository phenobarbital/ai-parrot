# F004 — Config already in core + tool auto-generation
**Type:** grep/read  **Confidence:** high
## Summary
- `WORKDAY_*` settings already in CORE `packages/ai-parrot/src/parrot/conf.py:595+` (tenant, client_id/secret, token_url, wsdl paths, report creds). Source has its own `config.py:WorkdayConfig`/`get_wsdl_path` — overlap to reconcile.
- Tool generation: `parrot.tools.toolkit.AbstractToolkit.get_tools()` (toolkit.py:337,392) iterates `dir(self)`, skips `_`-prefixed, keeps `inspect.iscoroutinefunction` → each PUBLIC ASYNC METHOD becomes a tool (name-based, optional prefix). So the 11 requested methods just need to be public async methods on the toolkit.
## Citations
- packages/ai-parrot/src/parrot/conf.py:595-608 WORKDAY_*
- packages/ai-parrot/src/parrot/tools/toolkit.py:337,386-425 get_tools
