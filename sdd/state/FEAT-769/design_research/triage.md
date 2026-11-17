# Design-research triage — FEAT-769

Model: `gpt-5.6-luna` · codex-cli 0.164.0 · 10 suggestions.
Every `affected_paths` entry passed containment + `test -e`. Two load-bearing
claims (S1, S2) were re-verified **empirically** before adoption, per CLAUDE.md.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Re-scope the multi-model example or add qualified-member authorization (architecture) | CONFIRM | **Verified empirically.** `orders.members` = `[revenue, order_count, region, order_date]`; qualified join members are absent. `RoleCatalog.check_query_rights` (catalog.py:59-73) resolves `allowed` from the ROOT model only, so `dimensions=["customers.email"]` is denied `member_not_granted` **even with `metrics:"*"`/`dimensions:"*"`** — while `engines/native.py` compiles the join (test_native_extensions.py:87-92). | §2 Overview, §3 M6, §7 Risks, §8 Q1 |
| S2 | Provide a policy side-file for every model (architecture) | CONFIRM | `loader.py:111-114` raises `missing_policy` per model name. Reviewer's detail was imprecise — the fixture dir holds only `orders.policy.yaml`; `tests/_models.py:16-23` **writes `customers.policy.yaml` at runtime**. Constraint stands, nuance recorded. | §3 M2, §6 Edit Sites, §7 Gotchas |
| S3 | Make the LLM path opt-in, smoke provider-free (testing) | CONFIRM | `ci.yml:535-536` supplies no LLM credentials; `hooba_agent.py:44-64` is the precedent. | §3 M3, §4, §5 AC6 |
| S4 | Pin the real `ask(permission_context=...)` dispatch (testing) | CONFIRM | Chain verified: `base.py:1083` → `:1439-1440`/`:2095-2096` → `manager.py:2174` → `toolkit.py:178` → `_pre_execute` (toolkit.py:110-116). Tool-list inspection does not prove K2. | §3 M3, §4, §5 AC4 |
| S5 | Build the MCP example through the real server factory (api) | CONFIRM | `create_toolkit_mcp_server` exists and is what `test_mcp_local.py:18` already drives. | §3 M4, §5 AC5 |
| S6 | Treat the documentation fences as an API (risk) | CONFIRM (refined) | Verified more precisely than stated: `_doc_yaml(key="toolkits")`, `_doc_yaml("# orders.yml")`, `_doc_yaml("# orders.policy.yaml")` each assert **exactly one** match, and every ```json block must parse with `mcpServers` equal to exactly one entry (test_mcp_local.py:38-47, 66, 81, 88-90, 97-98). | §3 M7, §7 Risks, §5 AC8 |
| S7 | Validate mask and saved-query fixtures through the real loader (api) | CONFIRM | `MaskRule` (policy.py:36-43) and `SavedQuery` (policy.py:46-52) are `extra="forbid"`; `TimeDimension.require_grain` (models.py:38-43) rejects a grainless time dimension. | §3 M5, §4, §6 |
| S8 | Require observable denial assertions in every example pin (testing) | CONFIRM | Matches the precedent at `test_example_agent.py:199-215`, which breaks the gate and requires `run_demo` to raise. | §4, §5 AC7 |
| S9 | Do not demonstrate RLS removal through `reload()` (risk) | CONFIRM | Independently known as K13 (closed `issue:e3ff9bfb4a83`); `test_rls_ownership.py` pins the fail-safe. | §7 Gotchas |
| S10 | Sequence the deliverable around the join blocker (alternative) | CONFIRM | Directly answers the proposal's unresolved sequencing question; M6 is the only module gated on an unresolved contract. | §3 ordering, §8 Q2, Worktree Strategy |

Summary: **10** confirmed · **0** rejected · **1** escalated to §8 (the M6 re-scope choice arising from S1).

No suggestion was silently dropped. No path failed containment or existence.
