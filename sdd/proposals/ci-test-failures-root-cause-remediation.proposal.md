---
id: FEAT-568
title: CI test-failure root-cause remediation (test-core, test-wiki-extras, test-tool-optimizations)
slug: ci-test-failures-root-cause-remediation
type: bug-investigation
mode: investigation
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-15
  summary_oneline: Fix CI test failures without sacrificing test validity — 6 verified root causes
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-568/
created: 2026-09-15
updated: 2026-09-15
---

# FEAT-568 — CI test-failure root-cause remediation

> **Mode**: investigation
> **Confidence**: high
> **Source**: `inline` (user request + a GitHub Copilot investigation transcript, treated as an unverified lead)
> **Audit**: [`sdd/state/FEAT-568/`](../state/FEAT-568/)

---

## 0. Origin

The original request, preserved verbatim at `sdd/state/FEAT-568/source.md`.

> "your goal is to fix the CI test failures that we have in the ai-parrot repo,
> but be mindful that we want the tests to be actually valid, and not just fix
> them to get them to pass, that would forfeit the purpose of the test itself,
> so we need to understand why the CI test is failing and identify the best
> path of resolution, while keeping the test valid which it is its purpose"

A GitHub Copilot investigation was supplied as a lead, claiming 4 failure
buckets (a resolver-unsat P0, a `tqdm` import cascade, a `pymupdf` gap, and
FEAT-543 "contract drift"). **None of Copilot's claims were taken at face
value** — every one was independently re-verified against this repository's
current `dev` HEAD, live `gh run` data, and git history, per this command's
anti-hallucination guardrail. One of its four claims (P0) turned out to
already be fixed; the other three were confirmed but their *true* root causes
turned out to be different (and in one case, much larger) than Copilot
described. Two further, real failures were found that Copilot's transcript
never mentioned at all.

**Initial signals**:
- Verbs: "fix", "understand why", "keep the test valid" → investigation of
  existing red CI, explicit anti-regression constraint on test semantics.
- Named entities: `ci.yml`, `async-notify`, `tqdm`, `pymupdf`, FEAT-543 SDD
  worker contract tests.
- Acceptance criteria provided: no explicit checklist; the implicit
  criterion is "the named jobs go green, and every fix is traceable to a
  confirmed root cause, not a relaxed assertion."

---

## 1. Synthesis Summary

Three CI jobs are currently red on `dev` (`gh run view` on the latest push,
head `3ba22952c`): `Test wikitoolkit with wiki-languages + wiki-structural
extras`, `Test tool-optimizations FEAT-543 (Python 3.11)`, and `Test
ai-parrot (Python 3.12)` (3.11 was cancelled by the workflow, not failed).
Six independent, individually-confirmed root causes explain all of them: an
already-fixed resolver issue (§2.1 #1), a genuine core-code bug (unconditional
`tqdm` import, #2), a large CI-configuration gap left behind by the FEAT-523
LLM-client satellite split (#3), a packaging-vs-spec contradiction around
`pymupdf` (#4), a documentation regression in `.claude/agents/sdd-worker.md`
that dropped a FEAT-543 capability (#5), and two ordinary cases of test
staleness from later, unrelated features (#6). Every fix direction below
either corrects genuinely wrong/regressed production code or docs, or
updates a test to track a legitimate, already-shipped change — none proposes
weakening an assertion to paper over a real defect.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-568/findings/`. Every path/symbol
> below traces to a finding ID.

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|------|--------|------|----------|
| 1 | `pyproject.toml` | `[tool.uv].environments` | already restricts the lock to `linux, non-aarch64` — the P0 fix | F001 |
| 2 | `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | line 44 (`from tqdm.asyncio import ...`) / line 4159 (`self.use_tqdm`) | unconditional import of an already-optional-at-runtime feature | F002 |
| 3 | `.github/workflows/ci.yml` | `test-core` job | syncs bare `ai-parrot`, then sweeps root `tests/` including 15 client-satellite test files it never installs | F003 |
| 4 | `packages/ai-parrot/pyproject.toml` | `bookstore` extra | `pymupdf`/`pymupdf4llm` only ship here, contradicting FEAT-451's "already a core dependency" claim | F004 |
| 5 | `.claude/agents/sdd-worker.md` | Fallback: Sequential Loop, steps b)/c) | missing `### b2) Delegated implementation` required by FEAT-543 | F005 |
| 6 | `tests/knowledge/wiki/test_store_migration_v2.py` | `test_open_v1_db_migrates_to_v2` | hardcodes stale `SCHEMA_VERSION == "2"` (live value is `"3"`, FEAT-557) | F006 |
| 7 | `tests/test_infographic_html.py` | `BASE_CSS` import | tests a symbol removed by FEAT-493's `DesignSystem.stylesheet()` | F006 |

### 2.2 Constraints Discovered

- **The graceful-degradation pattern already exists in this exact workflow.**
  `test-wiki-extras` + `test-wiki-luau-fallback` (FEAT-498/FEAT-532) prove
  that the repo's own convention for "optional extra absent" is: one job
  runs without the extra and must degrade cleanly (skip, never crash), a
  second job installs the extra and asserts — with an explicit grep-for-
  `SKIPPED` gate — that the feature was genuinely exercised, not silently
  skipped. *Implication*: the fix for the LLM-client satellite gap (#3)
  should extend this pattern, not invent a new one. *Evidence*: F003.
- **`async-notify`'s aarch64 gap is permanent, not transient.** The
  `[tool.uv].environments` comment states async-notify has *never* published
  a linux/aarch64 wheel for any version. *Implication*: do not attempt to
  "fix" this by loosening the environment restriction later — it is the fix.
  *Evidence*: F001.
- **`TargetedWriterToolkit` (FEAT-543) is live, not superseded by FEAT-549.**
  It has ~30 passing unit tests, a benchmark harness, and is still fully
  documented in the Claude-command/Codex-skill twins of `sdd-start`. FEAT-549's
  Orchestrator Loop dispatches whole separate `sdd-coder` sub-agents per task
  — a different layer — so restoring FEAT-543's step inside `sdd-worker.md`
  does not conflict with FEAT-549's architecture. *Evidence*: F005.
- **FEAT-451's own spec text is the strongest signal on the `pymupdf`
  question**: it says the package is "already a core dependency" — meaning
  Option A (promote it) restores what was *already designed*, not a new
  design decision. *Evidence*: F004.

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched files |
|--------|------|---------|----------------|
| `6e10be590` | 2026-09-15 (today) | fix: resolve dependency graph gaps blocking uv sync in CI | `pyproject.toml` (`[tool.uv].environments`) |
| `26de90a91` | recent (FEAT-549) | feat(sdd-worker-subagents): TASK-3124 — sdd-worker.md Orchestrator Loop | `.claude/agents/sdd-worker.md` (dropped the b2 section) |
| `461b74c2e` | 2026-09-10 | feat(tool-optimizations): TASK-3090 — SDD delegation workflow | `.claude/agents/sdd-worker.md` (originally added the b2 section) |
| `cceff6174` | FEAT-523 tail | fix(pep-420-llm-clients): stage missed google/gemma4/hf deletion from core | `packages/ai-parrot/src/parrot/clients/google/` (emptied) |
| (FEAT-557 series) | recent | wikitoolkit-sqlite-optimizations (SCHEMA_VERSION 2→3) | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` |
| (FEAT-493 TASK-2712) | earlier | design-system layout refactor | `packages/ai-parrot-visualizations/.../infographic_html.py` (removed `BASE_CSS`) |

---

## 3. Hypothesis

### Hypothesis 1 — The P0 resolver-unsat issue Copilot found is already fixed · Confidence: high

**Supporting evidence**: F001
**Contradicting evidence**: —
**Reasoning**: `pyproject.toml`'s `[tool.uv].environments` was changed today
(commit `6e10be590`) to exclude `aarch64` from the lock, with a comment
naming the exact `async-notify` gap Copilot's transcript describes. The
latest live CI run on `dev` (after this session's `git pull --ff-only`) shows
`Lint & Registry Check`, both `ai-parrot-tools` legs, both `ai-parrot-loaders`
legs, and both `navrules` legs green — none of the jobs Copilot listed as
blocked by the resolver are failing anymore.

**Action**: none. Verify it stays green; do not touch `[tool.uv].environments`
again.

### Hypothesis 2 — `test-core`'s mass failures are two independent bugs, not one · Confidence: high

**Supporting evidence**: F002, F003
**Contradicting evidence**: —
**Reasoning**: Copilot attributed the entire "278 failed / 318 errors"
cascade to a single `tqdm` import. Direct log analysis shows `tqdm` really is
one real, confirmed core bug (`crew.py:44`, unconditional import of a feature
whose *use* — `crew.py:4159` — is already gated by `self.use_tqdm`) —
but it explains only ~112 of ~319 errors. The dominant contributor (~512
occurrences, more than the total error count because pytest counts
per-test-case) is that `ci.yml`'s `test-core` job was never updated after
FEAT-523 split 15 LLM-client packages (`ai-parrot-client-{amazon,anthropic,
gemma4,google,grok,groq,hf,local,meta,moonshot,nvidia,openai,openrouter,vllm,
zai}`) out of core — root `tests/clients/*` still imports
`parrot.clients.<provider>` and hard-fails to collect. The same pattern, at
lower volume, affects `apscheduler` (`ai-parrot-server[scheduler]`), the
third-party `mcp` SDK, `parrot.integrations.oauth2`, `googleapiclient`, and
`folium`.

**Action**:
1. Guard the `tqdm.asyncio` import in `crew.py` (try/except at import time,
   or move it inside the `if self.use_tqdm:` branch) — a pure source fix,
   zero test changes.
2. Add `pytest.importorskip(...)` (or an equivalent marker) to every test
   module that needs an optional satellite (`parrot.clients.<provider>`,
   `apscheduler`-backed scheduler tests, `mcp`, oauth2, `googleapiclient`) so
   `test-core`'s bare-core sweep degrades cleanly — no assertion changes.
3. Add a new CI job (or jobs) that syncs the LLM-client satellites (+
   `ai-parrot-server[scheduler]`, `ai-parrot-integrations`) and runs
   `tests/clients/` for real, with a Luau-style "confirm nothing was silently
   skipped" gate — mirroring `test-wiki-extras`/`test-wiki-luau-fallback`.

### Hypothesis 3 — `pymupdf` is a packaging-vs-spec contradiction, needing one decision · Confidence: medium-high

**Supporting evidence**: F004
**Contradicting evidence**: —
**Reasoning**: FEAT-451's own spec text says `pymupdf`/`pymupdf4llm` are
"already a core dependency", but `pyproject.toml` only exposes them via the
`bookstore` extra. `test-wiki-extras` installs `wiki-languages` +
`wiki-structural` — neither includes `pymupdf` — so every PDF-ingestion test
fails to collect. This is not ambiguous about *whether* there's a bug; it's
ambiguous about *which side* is authoritative.

**Action** (routes to an open question, §5): either (A) promote
`pymupdf`/`pymupdf4llm` to `ai-parrot`'s unconditional `[project.dependencies]`
— restoring what the spec already asserts — or (B) correct the spec's claim,
add a graceful-degradation guard to `DocumentAcquirer`'s PDF path, and add
`pytest.importorskip("pymupdf")` to the PDF-specific tests.

### Hypothesis 4 — `test-tool-optimizations`'s 4 failures are a doc regression, not contract drift · Confidence: high

**Supporting evidence**: F005
**Contradicting evidence**: —
**Reasoning**: Copilot characterized this as "SDD worker docs/instructions
vs. expected test contract" drift and suggested "reconcile ... prefer
updating the changed source-of-truth side." Git history shows exactly which
side changed and when: TASK-3090 (FEAT-543) added the `### b2) Delegated
implementation` section to `.claude/agents/sdd-worker.md` on 2026-09-10;
TASK-3124 (FEAT-549's Orchestrator Loop rewrite) deleted it without
replacement while restructuring the file. The same assertions, run against
`.claude/commands/sdd-start.md` and `.agents/skills/sdd-start/SKILL.md`
(same test file, different parametrize ID), still pass — those two docs were
never touched by the FEAT-549 rewrite. This is one file regressing out of
sync with its two siblings, not a genuine policy conflict between FEAT-543
and FEAT-549.

**Action**: reinsert the `### b2) Delegated implementation` section (and its
checklist line) into `.claude/agents/sdd-worker.md`'s "Fallback: Sequential
Loop", between steps b) and c) — content-equivalent to TASK-3090's original
addition. Zero test changes; this restores dropped capability.

### Hypothesis 5 — Two further failures are ordinary test staleness from unrelated, already-shipped features · Confidence: high

**Supporting evidence**: F006
**Contradicting evidence**: —
**Reasoning**: `test_store_migration_v2.py` hardcodes an expected
`SCHEMA_VERSION == "2"`; FEAT-557 bumped the live constant to `"3"` and this
regression test was never updated. `test_infographic_html.py` imports
`BASE_CSS`, a symbol FEAT-493 (TASK-2712) explicitly documents as replaced by
`DesignSystem.stylesheet(..., layout="report")`. Both are "test lagging a
real, intentional change" — the correct-and-valid fix is on the test side,
not the source side, because the source changes were deliberate and
documented.

**Action**: update `test_store_migration_v2.py` to assert against the live
`SCHEMA_VERSION` import (already imported in the file) and extend it to
exercise the 2→3 step FEAT-557 introduced, not just relabel the literal.
Rewrite `test_infographic_html.py`'s `BASE_CSS`-based assertions against
`DesignSystem.stylesheet(theme_cfg, layout="report")` — a real rewrite, not a
one-line patch; scope as its own task. A handful of further import errors in
the same sweep (`DatabaseAgentToolkit`, `DatabaseAgent`, `flows` from
`parrot.bots`, `FAISSStore`) look like the same pattern but were not
individually root-caused in this pass (see F006c) — flagged for spec-time
triage rather than assumed.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The async-notify/aarch64 resolver-unsat P0 is already fixed on `dev` | F001 | high | direct read of the fixing commit + live green CI confirmation |
| C2 | `crew.py`'s `tqdm` import is a genuine bug (use is already optional, import isn't) | F002 | high | direct read of both call sites + dependency grep |
| C3 | `test-core`'s largest failure volume is an FEAT-523 CI-wiring gap, not a test bug | F003 | high | directory + git history + CI log tally cross-check |
| C4 | `pymupdf` placement contradicts FEAT-451's spec | F004 | high | direct spec quote vs. direct pyproject.toml read |
| C5 | Which side (spec vs. packaging) should change for C4 | F004 | medium | a real design choice, not just a bug; needs a human/spec-time decision |
| C6 | `sdd-worker.md`'s missing b2 section is a regression, not intentional | F005 | high | git diff shows exact add/remove commits + sibling docs still pass |
| C7 | `test_store_migration_v2.py` / `test_infographic_html.py` are stale tests, not source bugs | F006 | high | source docstrings explicitly document the replacing API |
| C8 | The remaining stale-symbol errors (F006c) share the same pattern | F006 | medium | confirmed present in logs; root commit not individually traced |

Distribution: **6** high, **1** medium-high (rolled into C5), **1** medium.

Overall confidence is **high**: the only meaningfully open item is *which*
of two valid remediations to apply for `pymupdf` (C5), and that is
correctly deferred to `/sdd-spec` rather than guessed here.

---

## 5. Open Questions

### Unresolved (defer to spec)

- [ ] **Should `pymupdf`/`pymupdf4llm` become unconditional core dependencies
  of `ai-parrot` (restoring FEAT-451's own stated assumption), or should wiki
  PDF ingestion degrade gracefully and the spec's claim be corrected instead?**
  *Owner*: tbd · *Blocks*: C5, H3
  *Plausible answers*: a) promote to `[project.dependencies]` (matches spec
  text) · b) keep optional, add graceful-degradation + `importorskip` guard,
  correct the spec.

- [ ] **Should the new CI coverage for the 15 `ai-parrot-client-*` satellites
  be one combined job (sync all + run `tests/clients/`), or per-provider jobs
  matching the existing `test-tools`/`test-loaders` granularity?**
  *Owner*: tbd · *Blocks*: H2 (action 3)
  *Plausible answers*: a) one combined job (cheaper, matches wiki-extras
  precedent) · b) per-provider jobs (finer-grained signal, much more CI
  minutes for 15 packages).

- [ ] **Should the F006c stale-symbol drift bugs (`DatabaseAgentToolkit`,
  `DatabaseAgent`, `flows` from `parrot.bots`, `FAISSStore`) get their own
  triage/task within this same spec, or a separate follow-up feature?**
  *Owner*: tbd · *Blocks*: C8
  *Plausible answers*: a) fold into this spec (keeps "make CI green" complete
  in one pass) · b) split off (keeps this spec's scope to the confirmed,
  fully-root-caused issues only).

> Per the guardrail, unresolved entries are capped at 3 here — the other
> three hypotheses (H1, H2's first two actions, H4, H5's primary fixes) have
> no open question: they have a single, unambiguous correct action.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-568`** — *Rationale*: every root cause is independently
localized at high confidence, each is a small, well-bounded fix (one
lazy-import guard, one new CI job + several `importorskip` guards, one
dependency-placement decision, one doc restoration, two stale-test
corrections), and the only genuine unknowns (§5) are narrow implementation
choices well-suited to being resolved during spec drafting — not an
architectural fork requiring `/sdd-brainstorm`.

### Alternatives

- **`/sdd-brainstorm FEAT-568`** — not recommended; there is no competing
  architecture to explore, only a set of confirmed, independent fixes.
- **`/sdd-task FEAT-568`** — not recommended as a skip-ahead; six
  independent fixes across three CI jobs and multiple packages benefit from
  a spec's Codebase Contract and acceptance-criteria structure before
  decomposition into tasks.
- **Manual review** — not needed; research was not truncated and no findings
  contradict each other.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-568/` (no `state.json` — this run predates the FEAT-568 state-schema template; see note below) |
| Source (raw) | `sdd/state/FEAT-568/source.md` |
| Research plan | `sdd/state/FEAT-568/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-568/findings/F001-*.md` … `F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-568/synthesis.json` |

**Budget consumed** (informal — `default` profile, not machine-tracked
this run): ~20 file reads, ~15 greps, ~10 git/gh calls, well within the
`default` budget (40/25/10). Truncated: **no**.

**Note on tooling gaps found while running this command**: `sdd/templates/`
does not currently contain `state.schema.json` or `research_plan.schema.json`,
which `/sdd-proposal`'s own spec references for `state.json` initialization
and research-plan validation. This run proceeded pragmatically (a plain
`research_plan.json` without schema validation, no `state.json` state-machine
file) rather than blocking on that gap, since it is a process-tooling issue
orthogonal to the CI investigation requested. Worth its own small follow-up
if `/sdd-proposal` continues to be used.

**Mode determination**: `auto` → resolved to `investigation` (the request is
explicitly about diagnosing and fixing existing failures, not adding new
capability).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` (interactive session) |
| Operator | Claude Sonnet 5, on behalf of amartinez@trocglobal.com |
| Verification method | Direct `gh run`/`gh api` log inspection against live `dev` CI + `git log`/`git show`/`grep`/`read` against the current worktree — not the Copilot transcript, which was treated as an unverified lead only |
