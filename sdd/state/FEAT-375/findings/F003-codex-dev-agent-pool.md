# F003 — Codex already usable for development tasks via DevAgentPool (queries Q001, Q006)

**Type**: wiki page + grep
**Citations**:
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:39-40,143-146` — `build_dispatcher(spec)`: `spec.agent == "codex"` → `CodexCodeDispatcher` + `CodexCodeDispatchProfile(model=DEV_LOOP_CODEX_MODEL, default "gpt-5.5")`
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py:364,377,432` — backend enum includes "codex" among `claude-code, codex, gemini, nvidia, grok, zai, moonshot`
- wiki: `sdd/specs/dev-loop-multiple-dev-agents.spec.md` (FEAT-323) — `DEV_LOOP_DEV_AGENTS` / `DEV_LOOP_DEV_ISOLATION` / `DEV_LOOP_DEV_POOL_MAX` env config; `DevAgentPool` round-robin dispatch, retry, aggregation (agent_pool.py)

**Implication**: "use codex to run development tasks" already works — set `DEV_LOOP_DEV_AGENTS='[{"agent":"codex",...}]'` and DevelopmentNode's pool dispatches sdd-worker briefs through the Codex CLI.
