---
title: "SDD Expert Consult"
summary: "`parrot sdd experts consult|triage|promote`: ask matching domain experts for advisory findings on an SDD document, triage them, and promote confirmed ones to unreviewed decisions."
---

# SDD Expert Consult

## Purpose

Before a proposal or spec is approved, domain experts can be asked for **advisory** findings. Consultation never
blocks `/sdd-proposal` or `/sdd-spec`; a human decides what each finding means.

## Commands

```bash
parrot sdd experts consult --doc sdd/specs/my.spec.md [--feature FEAT-123] [--root .]
parrot sdd experts triage  CONTRIBUTION FINDING_ID confirm|reject|escalate [--reason TEXT]
parrot sdd experts promote CONTRIBUTION FINDING_ID
```

### consult

1. Reads the document's `projects` and `tags` (the same normalisation `parrot sdd docs taxonomy` uses) and selects the
   [scope grids](../../experts/expert-stages-and-scope-grid.md) whose `match` intersects them. No match prints one
   line and exits 0.
2. Compiles each matched scope with `compile_scope` and runs it through `AgentsFlow`, so every stage runs in its
   declared mode. Gates are stripped for the run (nothing waits) and a mob stage's synthesis step uses a pass-through
   client that makes no model call. A failing stage or expert is logged and skipped.
3. Parses each expert's answer as a JSON array of findings (fenced JSON accepted); unparseable text becomes a single
   `info` finding holding the raw text.
4. Writes one `Contribution` per expert: `sdd/state/<FEAT-ID>/contributions/<expert>.json`, or
   `sdd/state/.contributions/<doc-slug>/<expert>.json` when no `--feature` is given.

`--feature` must look like `FEAT-<number>` (it becomes a directory name); anything else is a usage error. Apart from that,
consult never fails the SDD flow: any error while consulting is logged and reported as one `Expert consult skipped: ...` line
with exit code 0. The document is passed to the experts as escaped data inside a `<document>` wrapper, so text in it cannot close the
wrapper.

Each contribution stores the SHA-256 of the document; any contribution in the directory made for a different digest is
marked `stale: true`.

### Finding

`Finding` has `id`, `severity` (`info|minor|major|critical`), `section`, `statement`, `evidence` (free-text citations),
`status` (`pending|confirm|reject|escalate`) and `reason`. `triage` updates `status` and `reason` in place.

### promote

Only a `confirm`ed finding can be promoted. `promote_finding` stores the finding's **own statement** as an
`origin="inferred"`, `review_status="unreviewed"` decision through `DecisionRepository.save` — no model is involved and
`DecisionService.generate` is deliberately not used, because it infers candidates from a target's evidence and cannot
carry a statement an expert already produced. The id is derived from the expert, document, document digest and
statement, so promoting twice returns the same decision and never overwrites a reviewed one. The project wiki must be
built first (`wikitoolkit build`); the decision then goes through the normal decision review.

## In the SDD commands

`/sdd-proposal` and `/sdd-spec` carry an optional, non-blocking **Consult experts** step (and their twins under
`.agents/skills/` and `.agent/workflows/`). `/sdd-spec` also promotes `sdd/state/.contributions/<doc-slug>/` to
`sdd/state/<FEAT-ID>/contributions/` once the feature id is known, without overwriting an existing directory.

## Related

- [Expert stages and the scope grid](../../experts/expert-stages-and-scope-grid.md)
- [Generic gate host](../../flows/generic-gate-host.md)
