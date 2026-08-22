# F004 — PBAC fail-open confirmed; policy guards now have ONE real consumer
**Query**: R005, G006 + follow-up · **Confidence**: high

- `auth/pbac.py`: docstring (:57-59) states fail-open explicitly; returns `(None, None, None)` at :94, :104, :140 on any failure. No `PARROT_SAAS_MODE` anywhere.
- Drift vs brainstorm finding #3: `RlsRegistry`/`DataPlanePolicyGuard` are no longer 100% unused — `parrot/tools/dataset_manager/sources/authorizing.py:143-144` calls `guard.authorize_source(ctx, resources)` + `guard.rls_predicates(...)` at runtime (dataset tool path only). Still ZERO wiring in HTTP handlers; `rls_registry.py:20` hit is a docstring example.
