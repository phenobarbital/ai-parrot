---
id: FEAT-762
title: Operational screencast logs for the E2E `browser` exploration flow
slug: e2e-browser-screencast-logs
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-27
  summary_oneline: Give e2e-ui-tester a Playwright-backed .webm screencast as an operational log, alongside its existing on-anomaly screenshot
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-server, ai-parrot-tools]
tags: [e2e, playwright, obscura, observability, exploration]
research_state: sdd/state/FEAT-762/
created: 2026-10-27
updated: 2026-10-27
---

# FEAT-762 — Operational screencast logs for the E2E `browser` exploration flow

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline` — a conversational exploration of FEAT-581's E2E module
> **Audit**: [`sdd/state/FEAT-762/`](../state/FEAT-762/)

---

## 0. Origin

> Give the `e2e-ui-tester` exploration flow (and/or a future deterministic
> UI scenario) the ability to record a Playwright-backed screencast
> (.webm) of the browser session against the Obscura CDP endpoint, saved
> as an operational log artifact (not gate evidence) alongside the
> existing screenshot-on-anomaly behavior.

Full source, with the prior conversational context that seeded this
research, is at `sdd/state/FEAT-762/source.md`.

**Initial signals** (extracted, not interpreted):
- Named entities: `e2e-ui-tester`, Obscura, Playwright, `record_video_dir`,
  `artifacts/logs/e2e/<run-id>/`.
- Verbs: "add", "give the ability to record" → enrichment (net-new
  capability), not a bug fix.
- Explicit non-goal already stated by the requester: must not become gate
  evidence (`parrot e2e run`/`verify`).
- Acceptance criteria provided: no — open questions deferred to this
  proposal's research (resolved in §5 below).

---

## 1. Synthesis Summary

Today, `e2e-ui-tester` attaches to the `browser` e2e target's raw Obscura
CDP endpoint via an optional, generic DevTools-MCP tool and captures only a
single PNG screenshot "on any unexpected finding." A completely separate
module, `PlaywrightDriver` (`parrot_tools.scraping.drivers`), already
supports exactly the capability requested — `PlaywrightConfig.record_video_
dir` plus an `engine="obscura"` CDP-attach mode — but its own CDP-connect
logic only honors that option when it creates a *fresh* browser context,
silently ignoring it when it reuses an existing one. The natural landing
spot for the resulting `.webm` is `artifacts/logs/e2e/<run-id>/`, which is
already the real per-run log convention and is already excluded from the
deterministic gate's evidence hash — so this capability is safe to add as
a pure exploration-side operational log, with zero risk to `parrot e2e
run`/`verify`. The one real unknown — whether a real Obscura v0.2.2 binary
actually supports Playwright's underlying video mechanism — has never been
exercised anywhere in this repo, which is why this proposal (per the user's
decision, §5) scopes the first implementation task as a gated,
opt-in real-binary spike rather than an unconditional build.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-762/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-server/src/parrot/e2e/targets/browser.py` | `_BrowserAdapter` | 58-60, 316-323 | spawns `obscura serve`, hands back a raw CDP endpoint; never touches Playwright | F001 |
| 2 | `.claude/agents/e2e-ui-tester.md` | exploration protocol / report contract | 27-29, 48-60, 111-162 | the agent that would gain the screencast capability; today captures only a one-off screenshot | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py` | `PlaywrightConfig.record_video_dir` / `engine` / `cdp_endpoint_url` | 95, 101-102 | existing config surface that already supports CDP-attach video recording | F003 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | `PlaywrightDriver.start` / `_start_obscura_cdp` / `_build_context_kwargs` | 107-112, 586-618, 636-663 | the exact branch deciding whether `record_video_dir` engages or is silently dropped | F004 |
| 5 | `packages/ai-parrot-server/src/parrot/e2e/supervisor.py` | `E2ESupervisor._log_path` | 889-903 | defines the real `artifacts/logs/e2e/<run-id>/<target-id>.log` convention a sibling `.webm` would follow | F005 |
| 6 | `sdd/specs/agentic-e2e-testing.spec.md` | "Evidence Identity and Gate Evaluation" | 221-222, 299-304 | confirms `artifacts/logs/e2e/` is excluded from the deterministic source-identity hash and current evidence schema | F006 |
| 7 | `docs/obscura-headless-browser.md` | Compatibility matrix | 161-170, 191-201, 229-250 | shows video/screencast was never added to the verified-capability matrix for real Obscura | F007 |

### 2.2 Constraints Discovered

- **`record_video_dir` only engages on a freshly created CDP context.** In
  `engine="obscura"` mode, `PlaywrightDriver._start_obscura_cdp` reuses
  `browser.contexts[0]` (and skips `_build_context_kwargs()` entirely —
  `record_video_dir` ignored) whenever the endpoint already has a context;
  it only calls `_build_context_kwargs()` + `new_context()` when there are
  none. *Implication*: the implementation must force/verify a fresh
  context rather than assume one. *Evidence*: F004

- **No real-binary verification exists for this capability.** The
  Obscura/Playwright compatibility matrix tracks every other
  Playwright-exclusive feature (HAR, PDF, tracing, storage state) but has
  no row for video, and a sibling CDP feature (`get_page_source`) already
  has a documented real-binary gap. *Implication*: this must be verified
  with an opt-in, cleanly-skipping test before being trusted — exactly the
  pattern this repo already uses elsewhere. *Evidence*: F007

- **`artifacts/logs/e2e/` is outside the deterministic gate's blast
  radius.** It's excluded from the before/after source-identity hash and
  is not part of the current `E2EVerdict` evidence schema. *Implication*:
  this feature can be built purely on the exploration side with zero risk
  to `parrot e2e run`/`verify`. *Evidence*: F006

- **No retention policy exists for that directory today.** `artifacts/` is
  gitignored, but nothing rotates or caps `artifacts/logs/e2e/`.
  *Implication*: an always-on recording policy would need its own
  retention story — which is why the user explicitly scoped retention out
  for this feature (§5). *Evidence*: F008

### 2.3 Recent History (Relevant)

Not queried in this pass — the relevant history (TASK-057 adding
`record_video_dir`, TASK-2876 adding Obscura CDP-attach mode) is already
captured as cited task documents in F003, not as a `git log` sweep. No
contradicting recent activity was found.

---

## 3. Probable Scope *(mode = enrichment)*

### What's New

- A screencast-recording path inside the `e2e-ui-tester` exploration flow:
  connect a `PlaywrightDriver(PlaywrightConfig(engine="obscura",
  cdp_endpoint_url=<the `browser` target's `ready()` endpoint>,
  record_video_dir=<artifacts/logs/e2e/<run-id>/>))` session, instead of
  (or alongside) today's generic DevTools-MCP attach, so the context
  Playwright creates actually carries the video option. *Evidence*: F001,
  F003, F004
- A `screencast_ref` entry (or reuse of the existing `evidence_refs` array)
  in `e2e-exploration.json` pointing at the recorded `.webm`. *Evidence*:
  F002
- An opt-in, real-Obscura-binary verification test following the existing
  `test_fixture_site_integration.py` pattern (skips cleanly without a real
  binary, never fails the suite) — this is the spec's **first task**, per
  the user's decision in §5. *Evidence*: F007

### What Changes

- **`.claude/agents/e2e-ui-tester.md`::Exploration process / Report
  contract** — add the screencast step (hybrid trigger, see §5) and the
  new evidence reference; the existing on-anomaly screenshot step is kept
  unchanged alongside it. *Evidence*: F002

### What's Untouched (Non-Goals)

- `parrot.e2e.runner` / `parrot.e2e.models.E2EVerdict` — the deterministic
  gate's evidence schema and source-identity hash stay exactly as they
  are. No video field is added to gate evidence. *Evidence*: F006
- `parrot.e2e.targets.browser._BrowserAdapter` — keeps only spawning
  `obscura serve` and handing back a CDP endpoint; it never becomes
  Playwright-aware itself. *Evidence*: F001
- `e2e-api-tester` — no browser surface, out of scope.
- The `ui` target's own HTTP-only readiness check.
- Retention/cleanup of `artifacts/logs/e2e/` — explicitly deferred (§5,
  U3) to a separate housekeeping feature or manual cleanup.

### Patterns to Follow

- The repo's existing opt-in real-binary verification pattern (skip
  cleanly without the dependency, never fail the suite). *Evidence*: F007
- The existing `artifacts/logs/e2e/<run-id>/<target-id>`-shaped file
  placement, sibling to the existing screenshot path. *Evidence*: F005, F002

### Integration Risks

- **Obscura may not support Playwright's video mechanism at all**:
  impact — the feature looks implemented but produces no usable evidence,
  misleading a reviewer. *Mitigation*: the gated real-binary spike (§5,
  U1) is the spec's first task, before any other work proceeds.
  *Evidence*: F007
- **A reused CDP context silently drops the recording** even when Obscura
  itself would otherwise support it: impact — same silent-no-op failure
  mode. *Mitigation*: assert/log context freshness at connect time and
  fail loud rather than recording nothing unnoticed. *Evidence*: F004
- **Unbounded disk growth** under the always-on half of the hybrid trigger
  (§5, U2): impact — disk pressure on a dev machine or CI runner over many
  runs. *Mitigation*: explicitly out of scope per the user (§5, U3) —
  documented here as an accepted, deferred risk, not silently ignored.
  *Evidence*: F008

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The `browser` e2e target only spawns `obscura serve`/exposes a raw CDP endpoint; it never touches Playwright itself. | F001 | high | direct read of `browser.py`'s docstring and argv construction |
| C2 | `e2e-ui-tester` today only captures a one-off PNG screenshot via an optional DevTools MCP tool, not a continuous recording. | F002 | high | direct read of the agent definition's tools list and protocol text |
| C3 | `PlaywrightConfig` already has `record_video_dir` and an `engine="obscura"` CDP-attach mode. | F003 | high | direct read of the dataclass fields |
| C4 | `record_video_dir` only takes effect in Obscura/CDP mode when the endpoint has zero pre-existing browser contexts at connect time; otherwise it is silently ignored. | F004 | high | direct read of `_start_obscura_cdp`'s branching logic, not inferred from a task doc |
| C5 | The `browser` target's `minimal`/owned profile spawns a fresh, isolated obscura process per run, favorable to C4's fresh-context branch. | F001, F004 | medium | combines two findings by inference; no runtime observation confirms it in practice |
| C6 | `artifacts/logs/e2e/<run-id>/<target-id>.log` is the real per-run log convention, distinct from the private `sdd/state/e2e/<run-id>/` run directory. | F005 | high | direct read of both path-building functions |
| C7 | `artifacts/logs/e2e/` is already excluded from the deterministic gate's source-identity hash. | F006 | high | direct quote from the spec's evidence-identity exclusion list |
| C8 | The deterministic evidence schema (`E2EVerdict`) does not currently include video as an evidence type. | F006 | high | direct quote enumerating the evidence types the spec names |
| C9 | No existing test or doc has verified that a real Obscura v0.2.2 binary supports Playwright's video-recording mechanism. | F007 | medium | absence-based inference (missing matrix row + a sibling CDP feature's known real-binary gap) |
| C10 | No retention, rotation, or size-cap policy exists for `artifacts/logs/e2e/` anywhere in the repo today. | F008 | high | no contradicting mechanism found in `state.py`, `supervisor.py`, `cli.py`, or the spec |

Distribution: **8** high, **2** medium, **0** low.

`overall_confidence: medium` — held there specifically by C9: the central
technical premise (Obscura actually supporting Playwright-style video
capture) is unverified anywhere in this repo, so scope confidence cannot
exceed medium regardless of how solidly every other claim is grounded.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should the implementation be gated behind a real-Obscura-binary
  spike before building the full feature?** — *Resolved*: Yes — make it
  the spec's first task/acceptance gate, following the existing opt-in,
  cleanly-skipping test pattern. *Resolves claims*: C9

- [x] **Always-on vs. on-anomaly-only screencast trigger?** — *Resolved*:
  Hybrid — always-on for a future, bounded deterministic UI scenario;
  on-anomaly-only (mirroring today's screenshot trigger) for ad hoc
  `e2e-ui-tester` exploration. *Resolves claims*: C10 (trigger half)

- [x] **Is retention/cleanup of `artifacts/logs/e2e/` in scope here?** —
  *Resolved*: No — out of scope. Document the disk-growth risk only;
  defer to a separate housekeeping feature or manual cleanup, same as
  today's screenshots/logs. *Resolves claims*: C10 (retention half)

### Unresolved (defer to spec / implementation)

None — all three unknowns raised by this research were resolved during
the proposal phase.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-762`** — *Rationale*: localization is high-confidence
and the change is additive/narrowly scoped to the exploration flow (no
deterministic-gate changes); the one real architectural fork — whether
Obscura actually supports video capture — is exactly the kind of risk this
codebase already handles by making the real-binary check an opt-in,
cleanly-skipping spec task rather than a blocking brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-762`** — only if the spike (once run) shows
  Obscura does *not* support Playwright's video mechanism and an
  alternative architecture (e.g. raw CDP frame capture) needs exploring.
- **`/sdd-task FEAT-762`** — not recommended; the real-binary spike plus
  the agent-protocol change plus the evidence-schema addition is more than
  a single trivial task.
- **Manual review** — not needed; research was not truncated and no
  contradictions surfaced.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-762/state.json` |
| Source (raw) | `sdd/state/FEAT-762/source.md` |
| Research plan | `sdd/state/FEAT-762/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-762/findings/F001-*.md` … `F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-762/synthesis.json` |

**Budget consumed**: research was done directly (wiki_query/wiki_page +
targeted reads/greps) rather than through the automated planner/forked
lanes; no hard budget profile was enforced, truncation: **no**.

**Mode determination**: `auto` → resolved to `enrichment` (the ask is
"give the ability to...", a net-new capability, not an investigation of a
defect).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` (run directly by the coordinating agent, not the automated planner/forked-lane pipeline) |
| Operator | jesuslarag@gmail.com (Jesus Lara) |
| FEAT-ID reservation | `scripts/sdd/reserve_ids.py --kind feature --count 1 --base-branch dev --label e2e-browser-screencast-logs` → FEAT-762 |
