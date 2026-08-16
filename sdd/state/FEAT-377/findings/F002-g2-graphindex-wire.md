---
id: F002
query: "G2 — GraphIndex ↔ dev_loop coupling"
type: code_review
verdict: CONFIRMED
---

## G2: Zero coupling between dev_loop and GraphIndex

**Verdict: CONFIRMED**

### Evidence

1. **Zero Python-level coupling** — grep for `knowledge|graphindex|GraphIndex|
   wikitoolkit|graph_memory|GraphMemory` across all `.py` in `dev_loop/` =
   zero hits. No node imports or references knowledge-graph modules.

2. **Zero graph mentions in dispatched prompts** — grep across
   `_subagent_data/*.md` = zero hits. All five bundled prompts (research,
   worker, qa, codereview, secondopinion) have no wiki/graph instructions.

3. **Prompt drift** — `.claude/agents/sdd-research.md` (interactive) has
   13 lines of wiki-first triage instructions (step 0 + cardinal rule).
   `_subagent_data/sdd-research.md` (dispatched by dev_loop) has none of
   these. Wiki instructions were added to interactive but never propagated
   to the package-shipped copy that `load_subagent_definition()` reads.

4. **research.py** — constructs dispatch profile, collects logs, builds
   Jira tickets. Never queries GraphIndex, never injects wiki context,
   never passes graph tools in `allowed_tools`.

5. **close.py / failure_handler.py** — terminal nodes post Jira comments
   and transition tickets. Neither writes anything back to GraphIndex.

### Four connection seams identified

1. Sync wiki-first block to `_subagent_data/sdd-research.md` + add to
   other subagents (hours)
2. Research-node graph context injection via `GraphContextBuilder.build()` (M)
3. Write run outcomes back as graph memory at close/failure (M)
4. Ground code-review findings via `GroundingEvaluator.ground_claim` (M)
