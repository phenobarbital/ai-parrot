Step 1 — The ask: build one or more legal "LLM Wikis" on ai-parrot for a Spanish lawyer, where
Spanish + EU legislation and case law live as ArangoDB knowledge graphs with temporal validity,
answers are always citable to primary sources, and CENDOJ acts as a verification gate rather
than a bulk source. The source is not a ticket — it is a self-declared "skeleton" that asks for
its ~20 reuse claims to be checked against the repo before a spec exists.

Step 2 — Mode: enrichment. Additive verbs throughout ("create", "ingest", "add"), no negation,
no defect. Nothing is broken; a capability is being proposed.

Step 3 — Localization: unusual for enrichment, the localization map is a *reuse* map — the
existing seams the feature would attach to. All 13 findings contribute. Everything cited was
verified by direct grep/read this run.

Step 4 — Constraints: the binding ones are (a) GraphIndex isolation is a tenant/database, not
a namespace (F002); (b) the graph vocabulary is declarative YAML so legal collections are
config, not a fork (F003); (c) the tool-call interception seam exists but has no counter
(F007); (d) no temporal machinery anywhere (F011); (e) scheduler requires the server satellite
(F009); (f) parrot.interfaces is a mixins package, wrong home for contracts (F012).

Step 5 — Scope. The design's own §0 was largely right: 9 of ~11 reuse claims hold. Two are
wrong in a way that matters — "KnowledgeRouter" does not exist (F005) and the OQ1 decision
is refuted by TenantContext (F002). One reuse the source did NOT claim is the biggest find:
agents/security_advisor.py already implements the whole grounded/read-only/citation-audited
agent pattern including _audit_citations (F010), which is the LegalAnswer verified gate in
working form.

Step 6 — Confidence. Localization is high: every claim came from a direct citation this run.
Scope confidence is medium: the temporal-validity layer (the design's hardest and most
load-bearing component) is 100% greenfield with zero in-repo precedent, and the multi-graph
model has an unresolved architectural fork. Per rule 4, overall = min(high median claim,
high localization, medium scope) = medium.

Step 7 — Unknowns: five, all genuinely outside the repo (architecture fork the user must pick,
commercial licence, v1 materia, deployment shape, ToS risk ownership).

Step 8 — Next command: sdd-brainstorm, not sdd-spec. Not because confidence is low but because
F002 opens a real architectural fork with three viable answers, and the roadmap is five sprints
wide. Speccing before that fork is chosen would spec the wrong thing.

Step 9 — Self-check: every localization path traces to a finding citation; no invented symbols;
no fabricated line numbers (only ones read this run); research not truncated so medium is a
genuine ceiling, not a budget artifact.
