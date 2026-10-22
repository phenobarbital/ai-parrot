# TASK-4629: Document the enforcement policy, the wire shapes and the quota

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4627, TASK-4628
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and AC17. Two things in this feature are impossible to infer
from the code and will be rediscovered painfully if they are not written down:
the in-process quota is **per gunicorn worker** (so N workers allow N× the
configured limit), and a voice session in **client-submit mode** must send
`plausibility_ack=true` on the HTTP POST it makes afterwards, or the gate will
refuse answers the user already reconfirmed by voice. The policy matrix and the
`422`/`429` wire shapes also belong in a page a form author can read.

Runs last because it describes what the five preceding tasks actually shipped.

---

## Scope

- Create `docs/formdesigner-llm-validation-enforcement.md` covering: the
  three policies and their per-channel behaviour, the `422` and `429` response
  shapes, the reconfirmation flag, the `LLMValidationConfig` reference, the
  quota knobs on `setup_form_api`, and the two gotchas above.
- Cross-link the existing FEAT-649 page (`docs/audio-form-voice-modes.md`).

**NOT in scope**: code changes of any kind; a tutorial; documenting the
unresolved spec §8 questions (Q2 quota defaults, Q3 voice `on_error`
interaction) as if they were decided.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/formdesigner-llm-validation-enforcement.md` | CREATE | The feature's reference page |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# None — this task writes documentation only. Every symbol named in the page
# must be copied from the task files of TASK-4623..4628 or re-verified in the
# source before it is written down.
```

### Existing Signatures to Use

```markdown
<!-- Sibling pages that fix this repo's docs conventions (verified: `ls docs | grep -i form`) -->
docs/audio-form-voice-modes.md                     <-- FEAT-649's page; mentions plausibility
docs/formdesigner-autonomous-persistence.md        <-- sink/persistence page (naming pattern)
docs/formdesigner-unknown-fields-capture.md        <-- closest analogue: a per-form policy page
docs/formdesigner-conditional-sections.md
docs/formdesigner-relational-fields.md
docs/formdesigner-msteams-renderer.md
docs/formdesigner-audio-renderer.md
```

```python
# Facts the page must state, each verified at spec time (ce663090a):
# - LLMValidationConfig fields:  core/llm_validation.py:28-37 (+ on_implausible from TASK-4623)
# - the gate:                    services/submission_pipeline.py — gate_for() / ImplausibleSubmission (TASK-4624)
# - HTTP 422 shape:              api/handlers.py — submit_data's except branch (TASK-4625)
# - 429 shape + Retry-After:     api/handlers.py (TASK-4627), mirroring the 503 at :1789-1793
# - quota knobs:                 setup_form_api(llm_quota=…) — api/routes.py:214 region (TASK-4627)
# - audio REVIEW flagging:       audio/engine.py:969-979 (unchanged by this feature)
# - voice client-submit mode:    api/audio_ws.py::_do_client_submit — persists nothing
# - public auth exemption:       services/public_forms.py:13-52 (five globs incl. /data and /validate)
```

### Does NOT Exist

- ~~`docs/forms/`~~ — there is no `forms/` subdirectory; formdesigner pages live
  flat in `docs/` with the `formdesigner-` prefix (verified: `ls docs`).
- ~~a Redis quota backend~~ — only the `LLMQuotaBackend` Protocol and the
  in-process implementation exist. Do not document a backend that is not there.
- ~~a per-field policy override~~ — spec Non-Goal; the page must say the policy
  is per-form.
- ~~a "held / pending submission" state~~ — spec Non-Goal; nothing is stored on
  a refusal.
- ~~`on_error` as the implausibility knob~~ — it governs LLM *unavailability*
  (`skip`/`block` → `503`). The page must keep the two knobs clearly apart, as
  conflating them is the original confusion this feature resolves.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/formdesigner-llm-validation-enforcement.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Describe only what shipped.** Before writing any signature, flag name or
  response key, open the merged code and confirm it. A doc that invents a knob
  is worse than a missing doc.
- Keep the two knobs apart in every section: `on_error` = LLM unavailable,
  `on_implausible` = answer implausible.
- State the per-worker quota caveat in its own subsection — it is the one claim
  an operator will hold us to.
- Do not document spec §8's open questions as decisions. The default quota
  values (`10` per `60s`) are explicitly provisional — say so.
- Markdown only; no screenshots; code fences for every wire shape.

### References in Codebase

- `docs/formdesigner-unknown-fields-capture.md` — the closest analogue: a
  per-form policy with a wire contract. Follow its structure.
- `docs/audio-form-voice-modes.md` — FEAT-649's page; add the cross-link.

---

## Implementation Blueprint

### Steps (in order)

1. Re-read the five merged task diffs (TASK-4623..4628) — *why*: the page must
   describe the shipped behaviour, not the spec's intent, and the two may have
   diverged through a `FILL IN` decision.
2. Write the page in the declared section order — *why*: it mirrors
   `formdesigner-unknown-fields-capture.md`, so readers of one find their way
   around the other.
3. Add the cross-link in `docs/audio-form-voice-modes.md` only if that page's
   plausibility section is now incomplete without it — *why*: avoid touching a
   FEAT-649 page gratuitously (it is outside this task's declared files; if a
   link is needed, add the file to this task's table first and re-run the graph
   check).

### `docs/formdesigner-llm-validation-enforcement.md` (CREATE)

```markdown
# FormBuilder — LLM answer-plausibility enforcement

> FEAT-728. Builds on FEAT-649's plausibility checker
> (see `audio-form-voice-modes.md`). This page documents what happens to an
> answer the model judged implausible, and the quota that bounds every
> LLM-backed form call.

## The two knobs, kept apart

| Knob | Fires when | Values | Default |
|---|---|---|---|
| `on_error` | the LLM is unavailable / timed out / unparsable | `skip`, `block` | `skip` |
| `on_implausible` | an answer was judged implausible | `annotate`, `review`, `reject` | `annotate` |

<!-- FILL IN: one paragraph on why they are separate — bounded by the "keep the knobs apart"
     constraint; do not imply on_error can reject an answer -->

## Policy matrix

<!-- FILL IN: the table from spec §2 (policy × flagged/ack), stated per channel:
     HTTP/A2UI and voice — bounded by AC17 -->

## What trips the gate

<!-- FILL IN: `plausible == false` OR `confidence < threshold` (strict), over the
     eligible fields only (sensitive / read_only / excluded types never checked)
     — re-verify against the merged `implausible_fields` -->

## Wire shapes

### `422` — refused

<!-- FILL IN: the exact JSON from the merged submit_data branch, plus the A2UI
     envelope description — bounded by AC7/AC9 -->

### Clearing a `review`

<!-- FILL IN: ?plausibility_ack=true and the body form; note it is popped and never
     stored as an answer — bounded by AC8 -->

### `429` — rate limited

<!-- FILL IN: body + Retry-After, and the policy-dependent behaviour (fail closed under
     review/reject, skipped report under annotate) — bounded by AC12 -->

### `503` — LLM unavailable (unchanged)

<!-- FILL IN: one line pointing at on_error; this is FEAT-649 behaviour -->

## Configuring a form

```json
{
  "llm_validation": {
    "enabled": true,
    "threshold": 0.7,
    "on_error": "skip",
    "on_implausible": "review"
  }
}
```

<!-- FILL IN: the full field reference table, and the note that the policy is per-FORM
     while `field.llm_validation` stays the per-field opt-in — bounded by the Non-Goal -->

## Quota

<!-- FILL IN: setup_form_api(llm_quota=LLMQuota(...)) with every knob, the
     {tenant}:{form_uid}:{identity} key, how identity is resolved, and
     LLMQuota(enabled=False) to opt out — bounded by AC14 -->

### Gotcha: the quota is per worker

<!-- FILL IN: N gunicorn workers => up to N× the configured limit; the
     LLMQuotaBackend Protocol is the seam for a shared backend; defaults
     (10/60s) are provisional (spec §8 Q2) — bounded by AC17 -->

### Gotcha: proxies collapse anonymous identities

<!-- FILL IN: request.remote behind a proxy, and why trust_forwarded_for is off by
     default (a client-settable header would mint unlimited identities) -->

## Voice

<!-- FILL IN: REVIEW behaviour is unchanged; reaching Submit acknowledges; `reject`
     surfaces IOFailed(PLAUSIBILITY_REJECTED) — bounded by AC15 -->

### Gotcha: client-submit mode needs the ack

<!-- FILL IN: _do_client_submit persists nothing, so the client POSTs /data itself and
     must send plausibility_ack=true under `review`, or answers the user already
     reconfirmed by voice are refused. The client has `plausibility_summary` to decide
     — bounded by AC17 and spec §7 -->

## Security notes

<!-- FILL IN: public forms expose /validate and /data without auth (five globs in
     services/public_forms.py); the LLM opt-in is ignored for unauthenticated callers
     with reason="unauthenticated_opt_in"; closes ledger issue:44941ecac8cc — AC11/AC18 -->
```

**Why this shape**: the section order walks a reader from "which knob do I
want" to "what will my client see" to "what will bite me in production", which
is the order the support questions arrive in. The three gotcha subsections are
the reason this page exists at all — do not fold them into prose.

### FILL IN checklist

- [ ] Every `<!-- FILL IN -->` block above — written from the **merged** code, not from the spec; bounded by AC17
- [ ] The field-reference table — re-verified against `core/llm_validation.py` after TASK-4623 merged
- [ ] The `422`/`429` JSON — copied from the merged handlers, not retyped from the spec
- [ ] Decide whether `docs/audio-form-voice-modes.md` needs the cross-link; if yes, add it to this task's Files table first and re-run `check_task_graph`

---

## Acceptance Criteria

- [ ] `docs/formdesigner-llm-validation-enforcement.md` exists and documents: the policy matrix per channel, what trips the gate, the `422`/`429`/`503` wire shapes, the reconfirmation flag, the `LLMValidationConfig` reference, and the `setup_form_api` quota knobs (spec AC17).
- [ ] The per-worker quota caveat and the voice client-submit ack requirement each have their own subsection (spec AC17).
- [ ] `on_error` and `on_implausible` are never conflated.
- [ ] Every signature, flag and response key in the page matches the merged code (no invented knobs; no Redis backend; no per-field policy; no pending-submission state).
- [ ] The default quota values are described as provisional (spec §8 Q2).
- [ ] No code file is modified by this task.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`

---

## Test Specification

Documentation task — no new tests. The Validation Command above re-runs the
feature's HTTP suite so the page is written against green code; if it fails, the
page would be documenting something unfinished. The enforcement and quota suites
(`test_plausibility_enforcement.py`, `test_llm_quota_http.py`) are created by
TASK-4624/4627 and are already in the spec's Validation Contract, so the merge
tier runs them for this task too — do not list a file this task cannot run on a
fresh checkout.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§2, §7 Known Risks, §8 open questions)
3. **Check dependencies** — `TASK-4627` and `TASK-4628` must both be `"done"`;
   read their merged diffs before writing (`git log -p --oneline -6`).
4. **Verify the Codebase Contract** — confirm every fact listed under
   "Existing Signatures to Use" in the merged code, not in the spec.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index
6. **Implement** — complete every `<!-- FILL IN -->` block
7. **Verify** the Validation Commands pass (they guard that the page describes green code)
8. **Commit the doc** — stage only the file this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4629 formbuilder-llm-validation-enforcement verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Delivered by seat minimax (nova, minimax.minimax-m2.5), 1 attempt, 212s. Docs-only; no code validation applicable. Worker review: policies, wire shapes, ack flag and quota parameters checked against the merged code; no defects.
