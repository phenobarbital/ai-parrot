---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [contracts, ontology, pilot, e2e, acceptance]
parent: FEAT-539
---

# Contracts Pilot Signoff & End-to-End Validation

## Origin

Follow-up from FEAT-539 (contracts-card-ontology). All code tasks were merged
to `dev` via PRs #1347 and #1349 (2026-09-09). TASK-3056 (pilot signoff) was
force-closed because it depends on external operational inputs that have not
materialized. This proposal decouples the acceptance workflow from the
implementation.

## Problem

The contracts card & ontology feature (FEAT-539) is code-complete but lacks:

1. **Pilot acceptance** — Bob's twelve-case review (two initial client
   questions + ten common questions) against 50–100 active English contracts
   has not been conducted. No case has been run, no disposition recorded, no
   signoff obtained.
2. **End-to-end validation** — No E2E test coverage exists for the contracts
   card pipeline (ontology loading → GraphIndex ingestion → card rendering →
   lookup citation). The feature shipped with `e2e.policy: optional` and no
   E2E plan.

## Proposal

A new feature that delivers two workstreams:

### W1 — Pilot Acceptance Framework

- Create a twelve-case review matrix template (sourced from Bob, not
  invented).
- Build a lightweight CLI/script to run each case against the contracts
  adapters and record: lookup citations, handoffs, reviewer feedback,
  disposition.
- Record reviewer/date/evidence references without committing sensitive
  contract text.
- Track signoff as an explicit gate artifact in `sdd/state/`.

### W2 — End-to-End Test Coverage

- Define an E2E plan (`e2e-plan.md`) covering:
  - Ontology loading from DOCX/PDF contracts.
  - GraphIndex ingestion of contracts nodes.
  - Card rendering with the contracts card adapter.
  - Lookup citation accuracy for known-answer cases.
- Implement pytest-based E2E scenarios using the `parrot e2e` fixture
  framework.
- Wire the E2E gate (`e2e.policy: required`) so future changes to the
  contracts pipeline are gated.

## Impact

- **AC15** (spec §4–5) from FEAT-539 is satisfied only when W1 completes.
- W2 prevents regressions in the contracts pipeline going forward.
- `docs/knowledge/contracts-pilot-acceptance.md` was moved to the GitHub
  wiki by FEAT-801; the follow-up should update the wiki page rather than
  recreate the file.

## Open Questions

1. When will Bob's twelve cases and the pilot corpus be available?
2. Should the E2E tests use real contract fixtures or synthetic ones?
3. What is the target timeline for pilot completion?

## Recommendation

Spec this as a single feature with two task groups (W1, W2). W2 can proceed
independently with synthetic fixtures while W1 waits for operational inputs.
Gate the feature on both workstreams completing.
