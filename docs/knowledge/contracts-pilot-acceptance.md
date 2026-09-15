# Contracts pilot acceptance — Bob's twelve cases (FEAT-539, AC15)

> **STATUS: NOT SIGNED OFF — awaiting the pilot review.**
>
> This document is the *prepared matrix*, not a result. No case below has
> been run against real contracts, because doing so requires inputs that
> only the pilot can supply (see "What is still missing"). Automated test
> results are **not** pilot acceptance: spec §5 AC15 says so explicitly, and
> the feature's other acceptance criteria are tracked separately in
> `sdd/tasks/index/contracts-card-ontology.json`.
>
> Anyone reading this looking for "did the pilot pass?" — the answer today
> is *the pilot has not been run*.

---

## What is still missing

| Input | Needed from | Why it cannot be substituted |
|---|---|---|
| The exact wording of the two initial client questions | client / Bob | The agreed questions define the acceptance target; inventing them would fabricate the agreement. |
| Bob's ten common questions, as he asks them | Bob | Same. Paraphrases would test a different thing. |
| Bob's expected answer for each case | Bob | Acceptance compares the system's answer *to his*. |
| The 50–100 active English contracts | pilot corpus | The pilot measures behaviour on the real corpus, not on synthetic fixtures. |
| ~2 hours of review time per week | Bob | The signoff is a human judgement. |

Until every row above is supplied, this task stays **in progress**.

---

## How to run each case

For every case, run the question through the **fixed answer flow** (the same
gate the chat agent uses) as the reviewing user, then record what came back:

```bash
export GRAPHINDEX_PG_DSN=...            # the pilot catalog
python -m parrot_tools.contracts --user bob@troc --role contract_reader \
  search "<question keywords>"          # optional: locate the contract first
```

```python
outcome = await flow.answer(question, request_context=bob_context)
outcome.answer.answer_kind   # lookup | interpretation_required | not_found | out_of_scope | denied
outcome.answer.answer        # released text (None for every kind but lookup)
outcome.answer.citations     # contract_id, node_id, quote, page, version_n, verification
outcome.answer.handoff       # for interpretation_required
outcome.answer_id            # the audit record id — the traceable evidence reference
```

Record the `answer_id` for every case. It is the durable, auditable link
back to the exact citations that were released, and it is what a later
retirement would suppress.

**Do not paste contract text into this document.** Reference evidence by
`contract_id`, `node_id`, `version_n` and `answer_id` only — the quotes live
in the immutable evidence archive, which is where a reviewer should read
them.

---

## The twelve cases

Fill one row per case. `answer_kind` and `answer_id` come from the run;
"Bob's disposition" is his judgement, not the system's.

### Client questions (2)

| # | Question (verbatim, from the client) | answer_kind | answer_id | Citations (contract_id · node_id · v) | Handoff? | Bob's disposition | Corrections filed |
|---|---|---|---|---|---|---|---|
| C1 | _pending — supply the agreed wording_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| C2 | _pending — supply the agreed wording_ | | | | | ☐ accept ☐ reject ☐ needs work | |

### Bob's common questions (10)

| # | Question (verbatim, as Bob asks it) | answer_kind | answer_id | Citations (contract_id · node_id · v) | Handoff? | Bob's disposition | Corrections filed |
|---|---|---|---|---|---|---|---|
| B1 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B2 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B3 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B4 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B5 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B6 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B7 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B8 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B9 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |
| B10 | _pending_ | | | | | ☐ accept ☐ reject ☐ needs work | |

### What counts as a pass for one case

* **A lookup case passes** when the released answer matches Bob's answer
  *and* every statement carries a citation he agrees supports it.
* **An interpretation case passes** when the system hands off instead of
  answering, and the handoff locates the clauses Bob would have wanted.
  Refusing to adjudicate is the correct behaviour, not a failure.
* **A `not_found` passes** when the corpus genuinely does not answer the
  question. A `not_found` on a question the corpus *does* answer is a
  failure — record which contract it should have found.
* A `denied` during the pilot means the reviewer's roles are misconfigured;
  fix the configuration and re-run rather than recording it as a result.

---

## Verification and correction feedback

Corrections Bob makes while reviewing (they are part of the pilot, not
noise). Reference the audited operation, never the document text.

| Date | contract_id | Field / operation | Before → after | Recorded by | Revision |
|---|---|---|---|---|---|
| | | | | | |

Retirements issued during the review:

| Date | answer_id | Reason | Suppressed (contract_id · node_id) |
|---|---|---|---|
| | | | |

---

## Review log

Roughly two hours per week, per the agreed pilot budget.

| Week | Date | Reviewer | Hours | Cases covered | Notes |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |

---

## Signoff

Acceptance requires an explicit, dated statement from Bob. Leaving this
section blank means the pilot is **not** accepted.

| Field | Value |
|---|---|
| Reviewer | _pending_ |
| Date | _pending_ |
| Cases accepted | _pending_ / 12 |
| Outstanding cases | _pending_ |
| Decision | ☐ accepted ☐ accepted with follow-ups ☐ not accepted |
| Signature / written confirmation reference | _pending_ |

### Follow-ups agreed at signoff

| # | Follow-up | Owner | Target |
|---|---|---|---|
| | | | |

---

## Related evidence

* Feature acceptance criteria: `sdd/specs/contracts-card-ontology.spec.md` §5.
* Automated suite results and the services actually exercised:
  `sdd/tasks/completed/TASK-3054-contracts-live-integration.md`.
* Measured query performance (AC14): `contracts-performance.md`.
* Operating instructions: `contracts.md`.
