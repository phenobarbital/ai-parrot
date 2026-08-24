# F008 — Metering claims confirmed; ContextVar capture sites now FOUR
**Query**: R004, R004b, W003 · **Confidence**: high

- `observability/recorders/subscriber.py:100-112`: `UsageRecord` built with NO tenant_id/user_id/session_id/agent_name; `_cumulative_cost_usd` is in-memory per process under a lock (:91-95). Claim holds.
- Wiki confirms `recorders/models.py` self-describes UsageRecord as "the normalized, PII-free record" — the PII-contract amendment (S7 acceptance criterion) targets `observability/README.md` + this model.
- FEAT-228 "read here (construction time...) not at emit time" comments drifted from :479/:558/:606 to **clients/base.py:496, :575, :623, :665** — a FOURTH capture site appeared (post-FEAT-438 rebase). S7's `current_tenant_id`/`current_run_id` capture must cover all four.
