---
id: F003
query_id: Q001
type: read
intent: Determine whether long-horizon, parameterized, authenticated multi-stage browser flows already exist
executed_at: 2026-08-23T09:24:00Z
depth: 1
parent_id: F001
---

# F003 — FEAT-222 ScrapingFlow already delivers parameterized, session-affine multi-stage flows — and it is merged

## Summary

`sdd/specs/scrapingflow-composable-scraping.spec.md` (FEAT-222, status
**approved**) specified exactly the composition layer this proposal needs:
`TemplatePlan` + `ParamSpec` (parameterized plans bound with `bind(**kwargs)`),
`ScrapingFlow` + `FlowNode` (a DAG whose edges are data dependencies and whose
nodes carry a `session` label for BrowserContext affinity), `FlowExecutor`
(topological execution with per-node checkpoints for resumability), and
`SessionManager` (BrowserContext lifecycle, shared auth state across stages).
The spec's motivating example is literally "login → listing → detail-per-item →
checkout" — structurally identical to "login → CRM → new client → save" or
"login → gastos → new expense → attach receipt → save".

All five modules are implemented and committed (10 TASK commits plus a
code-review remediation commit).

## Citations

- path: `sdd/specs/scrapingflow-composable-scraping.spec.md`
  lines: 1-30
  symbol: "FEAT-222 frontmatter + motivation"
  excerpt: |
    **Feature ID**: FEAT-222   **Status**: approved
    Tasks like login → listing → detail-per-item → checkout cannot be modeled
    as a sequence of plans passing data between stages.
    G5: Resumability — failure at stage N does not force restart from stage 0.

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_models.py`
  lines: 19-147
  symbol: `FlowNode`, `ScrapingFlow`, `FlowResult`

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/template_plan.py`
  lines: 72-205
  symbol: `ParamSpec`, `TemplatePlan`, `TemplatePlan.bind`
  excerpt: |
    class TemplatePlan(BaseModel):
        def bind(self, **kwargs: Any) -> ScrapingPlan:   # line 205

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py`
  lines: 1-1
  symbol: `FlowExecutor`

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/session_manager.py`
  lines: 1-1
  symbol: `SessionManager`

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py`
  lines: 1-1
  symbol: `exec_loop`, `exec_conditional`, `substitute_template_vars`

## Notes

Git history confirms merge, newest first:
`4a7dfa3fe` FEAT-222 code-review remediation · `4fe577966` TASK-1453 exports ·
`b34b84e09` TASK-1452 FlowExecutor · `b77764e60` TASK-1451 SessionManager ·
`3bcfc71f0` TASK-1450 PageDriver · `f3156b5cc` TASK-1449 DAG models ·
`6e7c5adda` TASK-1448 TemplatePlan · `2bbb96d7b`/`33041b740`/`4f3377de9`
TASK-1447/1446/1445 advanced_actions extraction.

Two FEAT-222 non-goals are directly relevant here and remain open:
"MCP server exposure of the flow DSL — deferred" and "fan-out concurrency on a
shared authenticated session — known deferred debt (safe in sequential mode)".
Sequential-only is fine for a single-autónomo workload.
