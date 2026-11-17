# Design-research triage — FEAT-732 formdesigner-validation-audit-trail

Model: `gpt-5.6-luna` · Status: completed · 11 suggestions
All `affected_paths` passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Route all committed channels through SubmissionPipeline (architecture) | CONFIRM (as a scope boundary) | Verified Telegram / ui.handlers / MS Teams presets call FormValidator directly and persist nothing; re-routing is a separate feature, so the boundary is declared and tested instead of claimed | §1 NG1, §7 R1, §5 AC20 |
| S2 | Separate deterministic-trace configuration model (api) | CONFIRM | Folding it into LLMValidationConfig would let `enabled: false` disable deterministic auditing — the exact coupling this feature breaks | §2 D, M1 |
| S3 | Make ValidationResult the sole trace handoff (architecture) | CONFIRM | Removes the pipeline's second source of truth; matches the fixed explicit-collector constraint | §2 A, M3 |
| S4 | Stable check identifiers, not helper names or error text (api) | CONFIRM | Error strings are localised, helper names get refactored; drove the CheckId enum + pass/fail/skip + SkipReason | §2 B, Data Models, §7 R7 |
| S5 | Version both the fingerprint and the validator ruleset (risk) | CONFIRM | form.version is an author-controlled free string; a validator bugfix changes outcomes with no schema change | §2 C, §5 AC7 |
| S6 | Centralize canonical fingerprint with the validation traversal (architecture) | CONFIRM | Verified the traversals differ (validators.py:267-270 vs iter_fields_recursive; comment at :340-356) and plausibility.py:95 uses the other one | §2 C, M2, §7 R2, AC6 |
| S7 | Cap the serialized trace deterministically before persistence (risk) | CONFIRM | Verified submissions.py:331 dumps context unbounded, so a post-merge cap caps nothing | §2 E, M2 cap_trace, AC8/AC9 |
| S8 | Resolve effective LLM identity from the response (api) | CONFIRM | Matches the fixed decision and adds what it did not cover: an `ok` with no effective model routes through on_error | §2 F, M4, AC12 |
| S9 | Dedicated authenticated submission-audit read contract (architecture) | CONFIRM | Verified api/routes.py registers no submission GET; get_submission already exists; projection must exclude answers | §2 G, M6, AC16 |
| S10 | Do not rely on RBAC shadow checks for audit authorization (risk) | CONFIRM + ESCALATE | Fail-open paths confirmed at handlers.py:2239/2254/2271 → separate fail-closed gate adopted. Resource-scoping depth is a product decision | §2 G, §7 R3/R4, AC17; scoping → §8 Q1 |
| S11 | Contract tests for trace completeness and cross-channel parity (testing) | CONFIRM | Its branch list is more complete than the draft test table and was folded in wholesale | §4 Unit + Integration Tests |

Summary: 11 confirmed · 0 rejected · 1 escalated (S10's scoping depth → §8 Q1).

Provenance note: this run had no exploration document. The neutral brief was
rendered from the reporter's verbatim problem statement plus the four product
decisions and the verified code anchors — no draft, reasoning or preferred
conclusion of the spec author was included.
