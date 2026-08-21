# TASK-2311: Packaging, ops docs, and the mandatory Spanish-FP follow-up

**Feature**: FEAT-439 — ONNX Backend for the Prompt-Injection Guardrail
**Spec**: `sdd/specs/onnx-injection-guardrail-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2307, TASK-2308, TASK-2309
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (minus the benchmark re-run, which is TASK-2306). Three
closing obligations: (1) `huggingface_hub` becomes an explicit dependency
of the `security` extra (the warm-up and cache probing rely on it;
transitive-only today); (2) operators get real documentation for the new
env vars, warm-up, air-gapped provisioning, and the v1→v2 behaviour
change; (3) the **mandatory follow-up feature for the v2 Spanish
false-positive regression is filed and referenced from the spec** — an
explicit acceptance criterion (spec §5): v2 was approved only WITH this
ticket.

## Scope

- **Packaging**: add `huggingface_hub` to the `security` extra in
  `packages/ai-parrot/pyproject.toml` with a version bound compatible
  with the installed resolution — NOTE the constraint at pyproject
  line ~391: whisperx pins `huggingface-hub<1.0`; the bound chosen here
  must not conflict with the audio extra (spec §8 open question — resolve
  it here and record the reasoning in a comment next to the dep, matching
  the extra's existing comment style at lines 512-534).
  Verify: `uv pip install -e packages/ai-parrot[security]` resolves (or
  at minimum `uv pip compile`-level dry-run/resolution check).
- **Ops documentation** (`docs/` — follow existing docs layout, e.g. a
  `docs/guardrails/` or `docs/security/` page; check what exists and fit
  in): the three env vars (`PARROT_INJECTION_ONNX_DIR`,
  `PARROT_INJECTION_ORT_INTRA_OP_THREADS`,
  `PARROT_INJECTION_ORT_INTER_OP_THREADS` with defaults 2/1), the
  engine-resolution precedence and its log lines, `warmup_injection_model()`
  for long-lived hosts, air-gapped provisioning (how to populate
  `PARROT_INJECTION_ONNX_DIR`), and the v1→v2 behaviour change with a
  link to `benchmarks/injection_guardrail_latency/results-v2/delta-v1-to-v2.md`
  (attacks better, Spanish benign FPs worse — operators of
  Spanish-language deployments must be told plainly).
- **Follow-up feature filed**: create
  `sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md` (light
  proposal: problem = Spanish benign FPs 18.8%→43.8% at threshold 0.98,
  candidate directions = threshold retune / corpus expansion /
  multilingual eval, evidence links to `results-v2/`). If the team's
  Jira flow is preferred, ALSO create the Jira ticket via the existing
  toolkit/flow — but the committed proposal doc is the non-negotiable
  minimum.
- **Spec back-reference**: edit
  `sdd/specs/onnx-injection-guardrail-backend.spec.md` §5 to check the
  "follow-up feature filed" criterion with the proposal path (and Jira
  key if created).

**NOT in scope**: implementing the mitigation itself; benchmark work
(TASK-2306); any code change in `parrot/` modules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `huggingface_hub` in `security` extra + rationale comment |
| `docs/…` (fit existing layout) | CREATE/MODIFY | Ops page for the guardrail backend |
| `sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md` | CREATE | Follow-up feature (light proposal, frontmatter `type: feature`, `base_branch: dev`) |
| `sdd/specs/onnx-injection-guardrail-backend.spec.md` | MODIFY | Tick the filed-follow-up acceptance criterion with the reference |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verify each anchor with `read`/`grep` before editing.

### pyproject anchors

```toml
# packages/ai-parrot/pyproject.toml
# security extra: lines 512-534 —
#   "pytector==0.2.0" (line 516), "onnxruntime>=1.16" (line 534),
#   with explanatory comments in between (match that comment style)
# line ~391: whisperx 3.8.5 pins torchvision~=0.23.0 AND huggingface-hub<1.0
# line ~627-635: optimum[onnxruntime]>=2.0 deliberately NOT in security
```

### Evidence anchors for docs + proposal

- `benchmarks/injection_guardrail_latency/results-v2/report.md` — v2
  figures @256 (torch p50 120.71 / onnx p50 35.16 ms; parity 0 flips)
- `benchmarks/injection_guardrail_latency/results-v2/delta-v1-to-v2.md`
  — 21 flips (21.9%); Spanish benign FPs 18.8%→43.8%; recall 0.70→0.92;
  clean_framework 12/12→11/12; Spanish bucket n=16
- `benchmarks/injection_guardrail_latency/results-v2-512/` — TASK-2306's
  shipping-config figures (quote THESE as the headline in docs if
  available; else the 256 figures, labeled as such)

### SDD anchors

- Proposal frontmatter + light-proposal shape: see any recent
  `sdd/proposals/*.proposal.md` and the frontmatter block of
  `sdd/proposals/onnx-injection-guardrail-backend.brainstorm.md`
  (lines 1-7).
- Spec §5 criterion to tick: "Follow-up feature filed for the v2 Spanish
  benign false-positive regression…".

### Does NOT Exist

- ~~`huggingface_hub` anywhere in `security` extra~~ — not declared;
  this task adds it.
- ~~A docs page for guardrails ops~~ — check `docs/` first; create
  following the existing structure, do not assume a `docs/guardrails/`
  tree exists.
- ~~A FEAT id for the follow-up~~ — do NOT reserve one here; proposals
  don't get FEAT ids until their own `/sdd-spec` run (reserve_ids is for
  spec/task creation, and this proposal will get its number when it is
  spec'd).

---

## Implementation Notes

### Key Constraints
- `source .venv/bin/activate` before any `uv`/`python` command.
- Version-bound decision for `huggingface_hub`: check the installed
  version (`uv pip list | grep hugging`) and the transformers/whisperx
  constraints; prefer the loosest bound that is truthful (e.g.
  `huggingface_hub>=0.x,<1.0` if the audio extra must coexist). Record
  why in the comment.
- Docs tone: operator-facing, concrete commands, no marketing.
- Proposal doc: light shape (problem, evidence, candidate directions,
  open questions) — NOT a full brainstorm with options analysis.

### References in Codebase
- `docs/migration/feat-201-ai-parrot-embeddings.md` — example of an
  existing operator-facing doc's tone/structure.

---

## Acceptance Criteria

- [ ] `huggingface_hub` declared in the `security` extra with a bound
      that resolves alongside the audio extra's `huggingface-hub<1.0`
      pin; rationale comment present.
- [ ] Dependency resolution verified (install or dry-run) with the venv
      active.
- [ ] Ops doc covers: 3 env vars + defaults, resolution precedence +
      log lines, warm-up usage, air-gapped provisioning, v1→v2 change
      with delta link and the Spanish-FP caveat stated plainly.
- [ ] `sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md`
      committed with frontmatter and evidence links.
- [ ] Spec §5's follow-up criterion ticked with the reference.
- [ ] No changes outside the four listed files (plus a docs index/nav
      file if the docs layout requires registering the new page).

---

## Test Specification

No pytest for this task. Verification is:
1. `uv pip install -e packages/ai-parrot[security]` (venv active)
   resolves without conflict.
2. `grep -n "huggingface_hub" packages/ai-parrot/pyproject.toml` shows
   the new declaration in the security extra.
3. The proposal file parses via
   `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; print(parse(Path('sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md')))"`.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2307, 2308, 2309 in `sdd/tasks/completed/`
   (TASK-2306's 512 figures should also exist by now — use them in docs
   if present)
3. **Verify the Codebase Contract** before editing
4. **Update status** in `sdd/tasks/index/onnx-injection-guardrail-backend.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-08-21
**Notes**:
- **Packaging**: added `huggingface_hub>=0.24,<1.0` to the `security`
  extra of `packages/ai-parrot/pyproject.toml`, with a rationale comment
  matching the extra's existing comment style (lines 512-534). Bound
  chosen to stay compatible with the `audio` extra's whisperx 3.8.5 pin
  (`huggingface-hub<1.0.0`, pyproject:~391) while comfortably covering
  the installed `0.36.2`. Verified with `uv pip install --dry-run -e
  packages/ai-parrot[security]` (246 packages resolved, no conflicts) AND
  together with the `audio` extra (`uv pip install --dry-run -e
  "packages/ai-parrot[security,audio]"` — 247 packages, no conflicts).
- **Ops documentation**: created `docs/security/onnx-injection-guardrail.md`
  (docs/security/ already holds `pbac-guardrails.md` — matched its tone
  and structure rather than inventing a new docs subtree). Covers: why
  this exists (measured latency table), the 4-step resolution precedence
  and its logging contract, all 3 env vars with defaults, warm-up usage
  (`await warmup_injection_model()`, noting there's no generic warm-up
  hook to attach to), air-gapped provisioning via the exporter +
  `PARROT_INJECTION_ONNX_DIR`, the v1→v2 behaviour change with the
  Spanish-FP regression stated plainly (18.8%→43.8%) and linked to both
  `results-v2/delta-v1-to-v2.md` and the new follow-up proposal, and a
  known-limitations section (event-loop blocking, RSS, truncation
  divergence, threshold not retuned). No docs nav/index file exists that
  references `pbac-guardrails.md` either (checked via repo-wide grep), so
  no registration file needed touching.
- **Follow-up feature filed**:
  `sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md` — light
  proposal (problem/evidence/candidate-directions/open-questions shape,
  NOT a full brainstorm with options analysis), frontmatter
  `type: feature, base_branch: dev`, deliberately **no FEAT id** (per the
  task's explicit instruction — reserved only when this proposal itself
  gets spec'd via `/sdd-spec`). Parses cleanly via `scripts.sdd.sdd_meta.parse`.
- **Spec back-reference**: ticked the "Follow-up feature filed" criterion
  in `sdd/specs/onnx-injection-guardrail-backend.spec.md` §5, referencing
  the proposal path and noting the deliberate no-FEAT-id-yet state.
- No changes outside the four listed files.

**Deviations from spec**: none.
