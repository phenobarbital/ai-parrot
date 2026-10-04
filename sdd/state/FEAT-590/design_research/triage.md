| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Backward-compatible discriminated union (architecture) | CONFIRM | Matches the user decision; verified `PlanNode` extra=forbid, `nodes: List[PlanNode]`, compile hardcodes `"tool"` | §2 Overview, M3, M4 |
| S2 | Reuse dispatch/storage pipeline (architecture) | CONFIRM | `DelegateToolNode` subclasses `PlanToolNode`, and an `_invoke` hook keeps receipts/`_store` provenance | M5 |
| S3 | Delegate-pool ownership across fresh/resumed/repaired flows (architecture) | CONFIRM | Verified all 3 `build_plan_flow` sites (toolkit.py:337,593,1072); the toolkit owns `aclose` | M8, M7 |
| S4 | ToolSpec from authoritative schema, incl. `ToolDefinition.input_schema` (api) | CONFIRM | Verified `ToolDefinition` (manager.py:31) has `input_schema`, not `args_schema` | M1 |
| S5 | One runtime arg-validation contract (api) | CONFIRM | Uses `validate_args` (abstract.py:719) + unknown-key rejection, and dispatches the original args once via the manager | M5, AC9b |
| S6 | Side-effect policy from host config + re-check at dispatch (risk) | CONFIRM | Host flag already in design; added the runtime `side_effect_denied` re-check | M5, AC9c |
| S7 | Rejection/escalation as persisted outcomes (risk) | CONFIRM | Made "intentionally terminal" explicit; verified partial is not repair-eligible (repair.py:49-60) | M5, §2 |
| S8 | `confidence=None` must not silently bypass a set threshold (risk) | ESCALATE | Contradicts proposal §A.6 ("gate not available"); the exploration doc is authoritative, so the user decides | §8 Q-S8 |
| S9 | Bounded, redacted traces kept out of checkpoints (risk) | CONFIRM | Opt-in sink, `max_field_chars`, `redact` hook, never in context/checkpoint | M1, AC10 |
| S10 | Separate backends; no llama-cpp-python; picklable worker (alternative) | CONFIRM | Already HTTP-only; added the top-level picklable worker for the process executor | M6, M7 |
| S11 | Adversarial boundary tests (testing) | CONFIRM | Added never-dispatch-on-reject, extra-keys, re-check and checkpoint-hygiene tests | §4 |
| S12 | Defer standalone AgentCrew support (alternative) | CONFIRM | Verified crew `ToolNode` calls `tool.execute()` directly; already a Non-Goal | §1 Non-Goals |

Summary: **11** confirmed · **0** rejected · **1** escalated.
