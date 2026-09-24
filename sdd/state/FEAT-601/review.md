# FEAT-601 proposal review

Reviewed against checkout `ab9f97a82` on 2026-09-24. These are recommendations, not recorded owner approvals. The proposal and brainstorm remain unchanged; all questions other than U1–U5 carry into the spec unchanged.

## Assessment

Option B is supported by the current code: a domain card, dedicated graph publisher, narrow toolkit, and centralized answer service are appropriate reuse patterns. The proposal correctly identifies whole-catalog reconciliation, the URL/Path mismatch, domain-manager configuration, and the actual contracts release service. Copy the architectural boundaries, not all domain semantics.

Four corrections are needed before implementation:

1. **High — unsafe tip reassignment.** The brainstorm defines `step_key` from procedure slug and order. That is not stable when a step is inserted or renumbered. An exact key match could attach a tip to a different action. A cryptographic content hash also cannot have a meaningful similarity threshold. Use exact normalized-content hashes for equality; any fuzzy score must compare content, not hashes.
2. **High — verification is not completeness or entailment.** `contracts/verifier.py:156–206` preserves claim text when at least one attached citation survives. It checks source validity, not that the claim follows from the quote or that all required actions survived. Dropping an unsupported required action is unacceptable for a procedure presented as complete.
3. **High — channel entrypoints need an explicit adapter.** `contracts/agent.py:330–355` refuses `ask`, `ask_stream`, and `invoke`. Existing Slack (`wrapper.py:539`), WhatsApp (`wrapper.py:212`), and Telegram (`wrapper.py:1505`) call `ask`. Copying the refusal without a gated adapter would break delivery.
4. **High if certification is enabled — ontology rules are OR.** `ontology/authorization.py:70–115` grants access on the first matching rule. The dispatch supports five fixed rule types and no generic `certified_for` check. A certification edge plus a role rule does not implement role AND certification.

## U1 — additive URL delivery (option a, refined)

Add validated HTTP(S) URL fields to **both** `AIMessage` and `AgentResponse`, including response synchronization/serialization. Carry those fields separately through `ParsedResponse`; preserve its existing local Path collections. Use `image_urls` for figures and `media_urls` for directly deliverable media. Vendor video page links with timestamps remain links, not downloadable video attachments.

Evidence: `models/responses.py:87`, `:1109`, `:1176`; `integrations/parser.py:83`, `:520`. Current paths are coerced to Path and filtered by `exists()`. Widening them creates a broader compatibility burden.

Teams/Slack render remote figures; Telegram gets a bounded temporary-file download and its existing local upload path. WhatsApp already forwards `chart.public_url` to `send_image` (`whatsapp/wrapper.py:303`), so test the same direct-URL route for figures before introducing downloads there. This is an existing code precedent, not proof of a successful provider round-trip.

Generate signed URLs after authorization/release from stored media IDs; do not store expiring URLs as canonical evidence. Downloads must restrict destinations to configured asset storage, validate redirects, enforce size/time limits, and clean up temporary files. Channel limits must preserve figure-to-step labels and provide links for overflow instead of silently losing required figures.

Acceptance: existing local attachments unchanged; URL serialization round-trip through both response models; all duplicate sender paths covered; actual round-trips on supported channels; expired/unavailable media handled explicitly. The spike validates this decision rather than leaving the response contract undecided.

## U2 — extract the small shared foundation first (option b, narrowed)

Move `Evidence`, `Extracted`, `FieldProvenance`, `trim_quote`, their constants, and provenance type aliases into `knowledge/common/provenance.py`. Promote the generic whitespace/quote/extraction validation helpers into a shared validation module. Preserve old imports through aliases/re-exports, including private helper aliases where compatibility requires them. Manuals import the shared module directly.

Evidence: `contracts/models.py:88–111`, `:160–162`, `:205–311`; `contracts/carding.py:456–483`. These primitives are domain-neutral and have small dependencies. This is the second concrete consumer, so a bounded preparatory change is justified.

Do **not** combine this extraction with changing `Citation`/`EvidenceRef` to `doc_id`, generalizing archives, or moving contract versions/answers. Those have domain-specific semantics and a larger migration surface. Create manual-specific equivalents. Preserve the existing confidence-cap and quote-validation behavior; it does not itself establish that a procedure is safe to release.

Acceptance: old/new imports resolve to the same classes; existing contract model/carding tests pass; serialized payloads and validation behavior remain compatible; importing the shared foundation requires no tools satellite or database backend.

## U3 — independent ownership plus origin stamps (option c)

Put technician tips and their attachment/authorship edges in explicitly non-owned collections. Manual publication/reconciliation/retraction must never delete them. Add origin and authenticated-author metadata for auditability. Origin stamps document ownership; collection boundaries enforce it.

Evidence: `contracts/graph_loader.py:471–491`, `:505–548`, `:656–675`. The current loader reconciles entire owned collections and has no origin guard. Keep a separate, explicit tip-link maintenance operation with retryable, idempotent behavior.

Replace positional identity with an immutable step identity separate from display order. Match within the same tenant/manual/procedure lineage: unique persistent source identity when available, then unique exact normalized-content equality. Fuzzy text matching can propose curator candidates; do not automatically carry tips across changed torque, quantities, prerequisites, or warnings based on a 0.9 score. Ambiguous/removed steps retain their tips as orphaned or pending review, with their original source revision and attachment history. Retrieval must exclude unresolved links and inactive targets from current step advice.

Use collection names that are exclusive to technician content, including authorship edges; a generic shared `authored_by` collection would weaken the ownership boundary. Publication should report link-maintenance failure instead of claiming a fully successful revision transition.

Acceptance: inserted, renumbered, reworded, duplicated, and deleted steps; changed numeric instructions; repeated publication; concurrent tip creation; failed relinking and retry; retraction without tip loss; no cross-manual reassignment. These checks do not decide the separate tips-moderation question.

## U4 — deterministic assembly behind an answer service (option a)

Use an authorized retrieval → canonical procedure assembly → evidence/completeness verification → audit → release pipeline. Assemble ordered steps, prerequisites, hazards, media references, and citations from the selected, coherent source revision. The LLM may draft optional introductory prose or select enumerated IDs, but cannot replace operational instructions, omit warnings, change values, or generate canonical citations.

Evidence: `contracts/service.py:146–212` supplies the service boundary and `:214–232` buffers streaming; `contracts/verifier.py:156–206` needs procedure-specific replacement semantics. A missing required action or unsupported critical field blocks release as a complete executable procedure; it must not merely disappear from the response. An explicitly requested single-step answer still carries that step's applicable prerequisites and hazards.

Implement a ProceduresAgent transport adapter so ordinary `ask()` reaches the service and returns an `AIMessage` containing only released content. Support the other public entrypoints through that gate or reject them explicitly. No raw producer output may escape through chat, MCP, HTTP, streaming, or memory history. Keep per-request trusted identity isolated.

Acceptance: invalid/mismatched revisions, fabricated media/citations, missing/reordered required steps, omitted warnings, modified numeric values, failed audit writes, streaming, standard channel calls, and concurrent callers. `structured_output=ProcedureAnswer` alone is not a release control.

## U5 — tenant-wide reading in v1, action-specific writes (option a, conditional)

Recommend tenant-wide procedure access for authenticated technicians in v1, provided the client confirms that certification is not an access requirement. Require a trusted, matching tenant identity. Apply the same policy to catalog search, graph reads, PageIndex fallback, raw sections, media signing/download, tips, and guided resume—not only YAML traversals.

Distinguish actions: technicians read, run their own guided tasks, and add attributed tips; curators verify/publish procedures and manage privileged corrections. Confirmation is additional to authorization. Keep visibility/moderation of newly created tips as the existing separate open question.

Evidence: `contracts/retrieval.py:143–175`, `:283–318` and `contracts/toolkit.py:86–130` demonstrate trusted context and tool gates. Tighten the manuals tenant gate: the contracts check only rejects a mismatched tenant when a tenant is supplied. Do not accept caller/model-supplied role, tenant, or author claims.

Do not reserve an unenforced certification relation as if it provided security. If certification is required, implement an explicit role AND equipment-policy check before protected reads and apply its authorized equipment set to every fallback and child resource. Certification expiry/revocation semantics then become necessary scope. The current checker does not express this just by adding YAML rules.

Acceptance: missing identity/tenant, foreign tenant, insufficient role, unauthorized writes, forged attribution, alternate retrieval paths, media access, and cross-user guided resume. Client policy is the only remaining external input among these five recommendations.

## Scope and evidence limits

No feature code or proposal decisions were changed. No live channel, extraction-quality, alignment, or database-publication spike was run. The original four spikes remain necessary. Keep the remaining brainstorm questions unchanged in spec §8; this review does not choose storage backend, vision provider, card granularity, guided-state ownership, moderation, or v2 scope.
