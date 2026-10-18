## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.163.0) · Status: completed
> · Transcript: `sdd/state/FEAT-704/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 23 cited paths passed containment and existence checks; evidence for S2 and S5 was re-read in source.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Add a strict semantic authorization boundary (architecture) | CONFIRM | `DataPlanePolicyGuard`/`AuthorizingDataSource` do fail open on `ctx=None` (dataplane_guard.py:52,193); the spec already denied before the guard, and now also gates **catalog exposure** | §2 step 3, M6 `PbacGate`, M7 `visible_members(authorized=)`, AC3, AC19 |
| S2 | Make RLS injection immutable and request-scoped (risk) | CONFIRM + ESCALATE | Verified: `authorizing.py:191` mutates `self._inner.sql`; `handlers/datasets.py:70` shares `entry.source`. The semantic pipeline works on a per-request AST clone and never registers a source; the core defect is outside scope → ledger issue | §2 step 3 (clone), M6, §7 risk, §8 Q6 |
| S3 | Replace string RLS templates with typed predicates and driver bind adapters (api) | CONFIRM (parse at load) / REJECT (driver bind adapters) | Templates are now sqlglot-parsed at policy load and rendered as typed `exp.Literal`s, which is injection-safe per dialect. Per-driver parameter adapters (`$1` / `@name` / `?`) across three sources are out of v1 scope and add no safety over typed literals | M3 `load_policy`, M6 `RlsPushdown` |
| S4 | Specify fail-closed AST push-down semantics (architecture) | CONFIRM | Rewrite each base `exp.Table` preserving aliases/CTEs/joins; table functions, lateral sources, recursive CTEs or unplaceable constructs deny — never fall back to wrapping | M6 `RlsPushdown.apply` docstring, AC5 |
| S5 | Disable subject-independent caches for governed results (risk) | CONFIRM | Already pre-governance-only; verified `UserSession.metadata` is excluded from hashing (permission.py:49), so the subject digest now hashes policy-relevant metadata explicitly | M9 `ResultHandle.subject_digest`, AC8 |
| S6 | Authorize model resources before compilation (architecture) | CONFIRM | Two-phase check: declared manifest authorized pre-compile, compiled tables must be ⊆ manifest post-compile | §2 step 3, M6 `PbacGate.authorize_manifest`, AC19 |
| S7 | Keep credentials out of `SemanticQuery` (api) | CONFIRM | `SemanticQuery` carries only `model`; `extra="forbid"` rejects credential-like fields; credentials resolve server-side (resolved brainstorm question) | §2 Data Models, M2, M9 `ConnectionResolver` |
| S8 | Create a semantic audit ledger contract (architecture) | CONFIRM + ESCALATE | Versioned `SemanticAuditEntry` (`schema_version`) with compiled/governed SQL, policy context, engine, outcome; whether to withhold results on durable-sink failure becomes `audit_required` (default `False`) and a §8 question | M8, M10 kwarg, §8 Q5 |
| S9 | Define authenticated identity transport for mcp-local (risk) | REJECT | The user resolved mcp-local identity as an explicit `static_subject` (logged, audited). A signed per-call identity envelope is a reasonable future hardening but out of v1 scope for a local developer surface; the limitation is recorded as a risk | §7 Known Risks |
| S10 | Add adversarial positive-guard and lineage fixtures (testing) | CONFIRM | `QueryValidator` is negative-only (query_validator.py:165); added the adversarial matrix across the three dialects | §4 `test_positive_guard_adversarial_matrix`, AC18 |
| S11 | Make compiler parity and reentrancy release gates (testing) | CONFIRM | Added concurrent-compile, normalized-AST parity and pg/bq snapshot tests as release gates | §4 (`test_compile_concurrent_to_thread`, `test_dialect_sql_snapshots`), AC18, §8 Q2 |
| S12 | Make free SQL and dataset hand-off later opt-in features (alternative) | CONFIRM (ordering) / REJECT (defer to another spec) | Both tools are already opt-in and off by default (resolved brainstorm question); their tasks are now ordered last and gated on the security suite rather than deferred to a separate spec | Worktree Strategy (ordering inside M10) |

Summary: **10** confirmed (two of them partially, with the rejected part recorded) · **2** rejected (S9; the deferral half of S12) · **2** escalated (S2 → Q6, S8 → Q5).
