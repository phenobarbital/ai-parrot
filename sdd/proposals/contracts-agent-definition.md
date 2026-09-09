# Contract Intelligence Agent — base definition (Sept 2026)

Origin: client email requesting a working session on whether AI can help authorized employees find contract answers (SOC 2 requirements, upcoming renewals, key obligations) **without replacing Bob**, the contract owner; judgment questions must keep going through him. Brochure delivered as `contract-intelligence-agent.pptx` (11 slides, non-technical, English, neutral branding). Illustrative savings figures in the deck are assumptions to validate with Bob.

## Product definition (what the brochure promises)

- **Index, don't move**: contracts stay in SharePoint / OneDrive / shared drives / mailboxes; the agent builds one read-only index over all of them. The email's "is there a central repository?" stops being a blocker.
- **Answer only what's on the page**: every answer cites contract + section + page; `not_found` instead of guessing.
- **Bob stays the judge**: question triage → `lookup` (answered with citation) vs `interpretation_required` (routed to Bob with a hand-off brief: question, located clauses, summary) vs `out_of_scope` / `not_found`.
- **Contract card** per document with per-field provenance (page/node + origin `llm|manual|verified`) and `verified_by` (Bob). Verified vs. AI-extracted always labelled.
- **Contract map**: MSA → SOW → amendment, counterparties, obligations (SOC 2, insurance, DPA…).
- **Scheduled watchers**: renewal radar (daily; tracks notice deadline for auto-renew, 30/60/90), obligations calendar (weekly), new & changed contracts (every few hours → carding → Bob's verification queue).
- **Guardrails**: access by role/department/management chain with default deny, evaluated before retrieval; runs in the client's tenant; full audit log; human oversight (Bob approves cards, can correct/retire answers).
- **Pilot**: 6 weeks, 50–100 active contracts from the main repository, the two questions from the email + Bob's 10 most common; success = agent answers match Bob's, with citations. Needs: contract locations & counts (incl. scans), authorization rule, ~2 h/week of Bob.

## Mapping to ai-parrot (verified in `main`)

| Need | Existing piece | Gap to build |
|---|---|---|
| Ingestion | `parrot_tools/o365/{sharepoint,onedrive,mail}.py`, `parrot_loaders` (pdf, pdfmark, docx), PageIndex tree | SharePoint delta loop; OCR path for scanned PDFs |
| Card | `knowledge/bookstore` (`BookCard`, `carding.py` structured-output draft, `card_origin`, `source_sha256`) | `ContractCard` (parties, signatories, effective/expiration, term/auto-renew/notice, governing law, parent, obligations, status, `field_provenance`, `verified_by`) + contract carding prompt; generalize card family |
| Relations | bookstore `relations.py` (deterministic + LLM-judged, judgement log, `--force`) | `same_counterparty`, `amends`, `supersedes`, `governed_by`, `same_type`; LLM: `conflicts_with`, `references_obligation` |
| Graph / intents | `knowledge/ontology` (YAML domains; `legal.ontology.yaml` with `modifica`/`deroga` + `article_in_force` bitemporal pattern; `AuthorizationSpec` default-deny) | `contracts.ontology.yaml`: Contract, Party, Person (link to base `Employee`), Obligation, ComplianceRequirement; patterns `expiring_within`, `requires_compliance`, `contract_in_force` |
| Temporal | graphindex Postgres plane (FEAT-520: `graph_as_of`, `graph_concept_history`, `graph_diff`) | use for amendments/renewals as versions |
| Scheduler | `ai-parrot-server` `@schedule`, `schedule_daily_report`, `schedule_weekly_report`, `navigator.agents_scheduler`, `send_result`/`callbacks` | `renewals_report`, `ingest_delta`, `obligations_digest` methods on the agent |
| Answer contract | structured outputs | `ContractAnswer(answer_kind, answer, citations, provenance, handoff)` |
| Persistence | bookstore `library.db` (SQLite, single-user) | Postgres-backed catalog (pattern: `graphindex/persist_postgres.py`) — decide before writing the card |
| Review UI | admin UI (Svelte 5) in progress | verification queue for Bob |
