# FEAT-448 — Adversarial Review

**Date**: 2026-08-22
**Reviewer**: Codex CLI (`codex exec review --base dev`), triaged by Claude Code
**Verdict**: **all seven findings CONFIRMED and fixed.** 2 × P1, 5 × P2.
**Raw output**: `artifacts/reviews/FEAT-448-codex.txt` (fieldsync repo)
**Regression tests**: `tests/formdesigner/test_feat448_codex_findings.py` — 40
cases, of which **31 fail against the pre-fix implementation** (verified by
reverting the five source files and re-running).

Codex received the diff and the base branch only. Each finding was checked
against the code before being accepted; none was adopted on the reviewer's word.

> **Note on how this review happened at all.** The sdd-worker's own adversarial
> pass died with `Request timed out`, so the feature reached "complete" having
> never been reviewed. The gate did not fail — it never ran, which is the more
> dangerous of the two, because the run reports success either way.

---

## The seven findings share one root cause

Every one is the catalog travelling in a single direction:

- a type could be **rendered and not read back** (F1, F3);
- a shape could be **published narrower than the validator accepts** (F4, F5, F6);
- a control could be **advertised as native while submitting nothing** (F2);
- a validator could be **laxer than its own advertised contract** (F7).

That is the same defect FEAT-448 exists to close, reappearing inside the fix.
Worth saying plainly, because it is what makes TASK-2338's ratchet the load-
bearing part of this feature rather than its paperwork.

---

## F1 · [P1] JSON Schema round-trip lost the new types · **CONFIRM**

`JsonSchemaExtractor._infer_field_type` read only `format`, and only `place`
had been added to `_FORMAT_MAP` — so `search` came back as `TEXT`,
`tree_select` as `ARRAY`, `credit_card` as `GROUP`.

**Fixed differently from the suggestion.** Codex offered "add matching
`_FORMAT_MAP` entries, or honour `x-field-type`". The first fixes today's twelve
and is forgotten by the thirteenth. The renderer has been stamping
`x-field-type` on **every** property all along (`renderers/jsonschema.py:422`)
and nothing ever read it — so the extractor now reads it first and falls back to
the old inference. Every type round-trips, including ones not yet invented, and
an unrecognised marker degrades to `TEXT` with a warning instead of raising
(a schema from a newer parrot must still parse here).

## F2 · [P1] `PLACE`'s HTML could not submit a value · **CONFIRM**

The renderer advertises `PLACE` as native, but named its three selects
`<field>_country` / `_state` / `_city`. Nothing submits `<field>`, so a plain
form POST carried no value at all: a **required** `place` failed validation and
an optional one was silently discarded.

Fixed with bracketed names — `<field>[country]` — the standard HTML idiom for a
composite value, needing no script.

**Where it came from matters.** The `SIGNATURE` renderer has the identical
defect: a canvas plus empty `_svg`/`_png` hidden inputs and no script to fill
them. The new code was written by following it. That is the ratchet rule
exactly — a grandfathered violation is never a template — and the comment in
the fix says so, so the next person copies the right neighbour. Repairing
`SIGNATURE` is out of scope here.

## F3 · [P2] YAML silently downgraded every new type · **CONFIRM**

`_LEGACY_FIELD_TYPE_MAP` is hand-written and defaults unknown values to `TEXT`,
so `field_type: search` produced a text field. Only `place` had been added.

Fixed by deriving the base map from the enum
(`{**{ft.value: ft for ft in FieldType}, **_LEGACY_FIELD_TYPE_MAP}`), leaving
the literals as what they alone can express — **aliases** (hyphenated and legacy
spellings). A new type is now reachable from YAML the moment it exists.

## F4 · [P2] `TREE_SELECT` published only the array · **CONFIRM**
## F5 · [P2] `IMAGE_DROPZONE` published only the single object · **CONFIRM**
## F6 · [P2] `AI_CAPTURE` published `object` for an unconstrained value · **CONFIRM**

One cause: `_TYPE_MAP` holds a single JSON Schema `type` keyword per FieldType
and cannot express a union.

The first pass papered over it **in code comments** — *"object covers the common
single-file case"*, *"'object' is the common case, not a contract"* — while
publishing the narrow shape as the contract. A comment does not reach the
client. TASK-2338 exists so the client asserts against this catalog, so a
published shape narrower than the validator's means **our own contract rejects
submissions our own server accepts**.

Fixed with `_UNION_SHAPES`, consulted before `_TYPE_MAP` and replacing the
fragment whole: `oneOf` for the two unions, and the **empty schema** — JSON
Schema for "anything" — for `ai_capture`, whose shape is explicitly not ours to
define (spec §4 Non-Goals).

`test_value_shape_present_for_every_field_type` asserted `"type" in
value_shape`, which was right for scalars and wrong for both new cases. It now
accepts `type` **or** `oneOf`, and the empty schema only for an allow-list of
one — an unconstrained contract has to be argued for, once, per type, rather
than spreading.

The strongest new test is the pairing: for every value the validator accepts,
the published shape must admit it. That assertion is the feature's whole thesis
in one function.

## F7 · [P2] `credit_card` was laxer than its own contract · **CONFIRM**

The published shape requires `brand`, `last4`, `name`, `expiry`; the validator
checked only `last4`, so `{"last4": "4242"}` was accepted and stored.

Fixed. The reject-not-sanitize rule for `cvv` and the full PAN is untouched, and
a test asserts the added check did not weaken it — including that **no error
message echoes the offending value**, since an error quoting a PAN has moved it
into the logs.

---

## Also corrected in this pass, not a Codex finding

The sdd-worker's post-run hook ran `black` across all 21 files the run touched —
~1000 lines, including 455 in `adaptive_card.py`, 345 in `html5.py`, 230 in
`pdf.py`. Black **is** configured (`pyproject`, line-length 120) but the tree is
not black-clean: those files fail `black --check` on `dev` too. So it was not
restoring a standard, it was reformatting files that never followed one, on a
feature branch, with four other parrot branches in flight against the same
renderers.

Reverted; black re-applied only to the six files this feature created.
Reformatting the package is a legitimate task and not a rider on this one.

---

## Test evidence

```
packages/parrot-formdesigner/tests    37 failed, 2129 passed, 20 skipped, 81 errors
baseline (dev)                        37 failed, 1904 passed, 20 skipped, 81 errors
new failures: 0        net new passing: +225
```

The 118 pre-existing failures/errors are identical in both sets, name by name.

```
tests/formdesigner/test_feat448_codex_findings.py   40 passed
                                                    31 fail against pre-fix code
```

Run with `PYTHONPATH="$PWD/packages/parrot-formdesigner/src"` — the venv has
`parrot_formdesigner` installed editable against the MAIN checkout, so a plain
`pytest` inside the worktree tests the wrong tree.
