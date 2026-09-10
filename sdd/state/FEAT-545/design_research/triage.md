# FEAT-545 — Design Research Triage (TASK-3099 acceptance dry run, re-run after code-review fixes)

Model: `gpt-5.6-luna` (probe rc=0, "OK", 2026-09-10T02:05:21+00:00) · codex-cli 0.153.4
Run: 2026-09-10T02:28:12+00:00 → 2026-09-10T02:32:01+00:00 (rc=0, ~3m49s) · 11 suggestions
Every `affected_paths` entry verified with `test -e` before triage; none were unverifiable,
so no suggestion is REJECTed on that ground alone.

> **Why this is a second run, not the first**: the code-reviewer agent found that the
> ORIGINAL committed `brief.md` (rendered by TASK-3099's ad hoc extraction script) had an
> empty `recommended_option_or_scope` section due to a heading-boundary bug in that script
> (it stopped at the first `###` sub-heading instead of the next `##` same-level heading).
> The bug was fixed and the brief re-rendered (13,659 chars vs. 11,120 originally) and
> re-submitted to `codex`, producing this fresh, more informed set of suggestions. The prior
> run's `sdd/state/FEAT-545/design_research/` output has been superseded by this one.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Extract §3b into one checked helper (architecture) | REJECT | A Python helper for the phase is an explicit spec Non-Goal / "Does NOT Exist" entry (`scripts/sdd/design_research.py` — no Python helper; the phase is bash inside the command, mirroring the Adversarial Cross-Check pattern). | — |
| S2 | Make research staging run-scoped and collision-safe (risk) | CONFIRM | Verified: staging is a deterministic `mkdir -p "sdd/state/.design_research/<feature-name>"` with no per-run uniqueness or atomic promotion. | Follow-up task |
| S3 | Resolve the foreground-versus-background contract (risk) | ESCALATE | The prose/code mismatch itself was fixed in this same pass (§3b.3 now reads "synchronous — NOT a background job"), but the residual concern — a 600s synchronous wait inside `sdd-planner`'s unattended run, and whether a non-zero `codex` exit could be mistaken for a fatal `/sdd-spec` failure — is an operational/architecture decision beyond this task. | Human decision needed |
| S4 | Reject paths outside the repository root (risk) | CONFIRM | Verified: schema types `affected_paths` as plain strings; validation is a bare `test -e` with no containment/traversal check. | Follow-up task |
| S5 | Require line or symbol evidence, not paths alone (api) | ESCALATE | Legitimate hardening (aligning with the repo's `verified: path:NN` convention), but changing the schema's required fields is a contract change beyond this dry-run task's authority — AC-6 fixes the current schema shape. | Human decision needed |
| S6 | Persist a replayable Codex execution record (architecture) | CONFIRM | Verified: `codex.log` today is raw stdout/stderr redirection only; no structured record of CLI version, model, timeout, or exit status is persisted alongside it. | Follow-up task |
| S7 | Validate triage completeness mechanically (testing) | ESCALATE | Valid, but building a triage schema/validator is new infrastructure beyond this feature's stated test scope (unit tests over templates + this manual dry run). | Human decision needed |
| S8 | Use patch-shaped blueprints for file edits (architecture) | CONFIRM | Verified: a task-template MODIFY block only says "insert below `<anchor>`" with no occurrence-count or disambiguation rule for repeated anchor text — could duplicate an insertion. | Follow-up task |
| S9 | Enforce blueprint completeness against the file table (testing) | ESCALATE | Re-opens the spec's own §8 "lint vs. written rule" question (already defaulted to written-rule-only) at a broader scope; a human policy call, not resolved unilaterally here. | Human decision needed |
| S10 | Frame the recommended option as a hypothesis to challenge (alternative) | ESCALATE | A sharp, legitimate point: the brief includes the exploration doc's "Recommended Option" verbatim, which is arguably itself a "preferred conclusion" under the Adversarial rules' own wording. Spec's position is that this is the *human-approved* proposal's recommendation, not Claude's about-to-be-drafted reasoning — a defensible distinction, but a genuine design tension worth a human call, not resolved unilaterally here. | Human decision needed |
| S11 | Validate the probe's actual result and configuration (risk) | CONFIRM | Verified: §3b.1's probe only checks the `codex exec` exit code, never that `probe.txt` actually contains `OK` or which model/config was actually honored. | Follow-up task |

Summary: **5** confirmed · **1** rejected · **5** escalated.

## Fixes already applied in this same pass (not merely triaged — actually fixed)
These three were caught by the code-reviewer agent (not by this codex run) and fixed directly
in `.claude/commands/sdd-spec.md` / `.agent/workflows/sdd-spec.md` / `sdd/templates/design_research.prompt.md`
before this re-run, because they were CRITICAL (the phase could crash instead of skip):
1. §3b.2 lacked a `SKIP_REASON` guard — added `if [ -z "$SKIP_REASON" ]; then ... fi`.
2. `$REPO_ROOT` was referenced (§3b.3's `--cd "$REPO_ROOT"`) but never assigned — added
   `REPO_ROOT="$(pwd)"` in §3b.1.
3. The brief renderer did a naive whole-document `str.replace()`, which corrupted the
   template's own header comment (it repeated the `{{name}}` syntax as documentation) —
   reworded the header to spell placeholder names without literal braces, and switched the
   renderer to read each value from a per-name file instead of undefined Python variables.
The twin-parity test (`tests/sdd_scripts/test_command_twin_parity.py`) was also tightened
(S8 of the FIRST run, `triage` superseded by this file) to assert the exact expected
`AGENTS.md`/`CLAUDE.md` substitution instead of dropping the whole tolerated line.
