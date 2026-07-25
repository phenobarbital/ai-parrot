# F005 — Subagent definition mechanism (queries Q003, Q011)

**Type**: read (file listing + dispatcher prompt builder)
**Citations**:
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` — `load_subagent_definition(name)` loads markdown bodies
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/` — `sdd-worker.md`, `sdd-qa.md`, `sdd-research.md`, `sdd-codereview.md`
- `dispatcher.py:1153-1165` — `_build_codex_prompt` composes: subagent header + body + structured-output instructions

Facts:
- Subagent briefs are plain markdown files shipped in `_subagent_data/`; the dispatcher injects them as the system-style preamble plus the Pydantic output contract.
- Adding a new persona (e.g. `sdd-secondopinion.md`) is a data file + Literal widening, matching the existing pattern (FEAT-323 dual-sourced sdd-worker.md precedent).

**Implication**: the "neutral adversarial brief" from the request maps naturally onto a new `_subagent_data/*.md` body consumed by the existing prompt builder.
