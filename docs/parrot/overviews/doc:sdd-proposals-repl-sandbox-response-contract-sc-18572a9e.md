---
type: Wiki Overview
title: FEAT-252 — Harden the tactical credential-leak fix into the strategic containment
  contract
id: doc:sdd-proposals-repl-sandbox-response-contract-scrubber-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The source is a verified-anchor brainstorm (revision 2) triggered by a production
relates_to:
- concept: mod:parrot.security
  rel: mentions
---

---
id: FEAT-252
title: Harden the tactical credential-leak fix into the strategic containment contract
slug: repl-sandbox-response-contract-scrubber
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-23
  summary_oneline: REPL allowlist sandbox + Gemini final-response contract + deterministic secret scrubber to contain arbitrary-exec credential leakage
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-252/
created: 2026-06-23
updated: 2026-06-23
---

# FEAT-252 — Harden the tactical credential-leak fix into the strategic containment contract

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/brainstorm-repl-sandbox-response-contract-scrubber.md` (revision 2)
> **Audit**: [`sdd/state/FEAT-252/`](../state/FEAT-252/)

---

## 0. Origin

The source is a verified-anchor brainstorm (revision 2) triggered by a production
credential-leak incident.

> A production `JiraSpecialist` agent (model `gemini-3`) running an autonomous
> "process the remaining tickets" loop called the `python_repl` tool, evaluated
> `os.environ.keys()`, and the **`repr` of the resulting `KeysView` serialized the
> entire mapping with values**. That string became the tool result, fed back into
> the model's context, echoed as the final answer, rendered to Telegram, and
> logged in cleartext to CloudWatch. Three stacked failures — in-process REPL with
> full `os.environ`, the Gemini client surfacing raw tool output as the answer, and
> no deterministic redaction at any hop.

**Initial signals** (extracted, not interpreted):
- Verbs: *leaked*, *contain*, *sandbox*, *scrub*, *gate* → security-hardening, negative polarity.
- Named entities: `python_repl`, `os.environ`, Gemini client, `OutputScrubber`, `PythonCodeSanitizer`, `shell_tool`/`CommandSanitizer`.
- Components: tools, clients/google, bots/base, security.
- Acceptance criteria provided: no (brainstorm defines goals + 3 open questions).

**Decisive new finding from research** (not in the source): a **tactical fix is
already committed on dev** in `0f76129b1 "security on llm clients and agents"`
[F010]. FEAT-252 is therefore a *consolidation/hardening* of shipped code, not a
greenfield build — and the source's two ⚠️ VERIFY items are now both closed.

---

## 1. Synthesis Summary

The incident already has a **tactical** fix on `dev` [F010]: `python_repl` gained an
AST **denylist** (`_check_ast_security` + `BLOCKED_IMPORTS/NAMES/ATTRIBUTES`) plus
output redaction [F002], and `redact_text`/`redact_secrets` from a new core module
`security/redaction.py` [F005] were sprinkled across **~14 call sites** in the Gemini
client [F003]. It closes the *known* vector but **diverges from the brainstorm's
strategic design on all three workstreams**: a denylist where an allowlist-first
`PythonCodeSanitizer` was intended (WS1) [F002]; scattered redaction with **no single
`_resolve_final_response` chokepoint** and `default_api` hunting still enabled (WS2)
[F003]; and a flat-marker standalone module rather than a policy-driven `OutputScrubber`
hooked once at the (single, verified, currently un-hooked) `AbstractTool.execute()` seam,
not built on the existing `shell_tool` engine (WS3 + foundation) [F004, F005, F001].
This FEAT consolidates the tactical fix into the strategic contract; the four "how far"
decisions were resolved with the user in §5.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-252/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `tools/pythonrepl.py` | `_check_ast_security` / `BLOCKED_IMPORTS` / `_redact_execution_output` | 106-143, 504-525 | WS1 — shipped **denylist** gate + in-process output redaction | F002 |
| 2 | `clients/google/client.py` | `_handle_multiturn_function_calls` / `_safe_extract_text` / `AIMessageFactory.from_gemini` ×6 | 1580-1652, 2066-2107, 3146/3796/4323/4505/4802/4917 | WS2 — 6 terminal sites + scattered redaction; target of one chokepoint | F003 |
| 3 | `clients/google/client.py` | `_parse_tool_code_blocks` (`default_api`) | 1958-1966 | WS2 — un-gated `default_api`/`tool_code` hunting | F003 |
| 4 | `tools/abstract.py` | `AbstractTool.execute` / `ToolResult` | 47-73, 473-616 | WS3 — **single** result seam for emplacement (a); **not hooked** | F004 |
| 5 | `security/redaction.py` | `redact_text` / `redact_secrets` / `looks_sensitive_key` | 8-70 | WS3 — shipped flat `[REDACTED]` scrubber to evolve | F005 |
| 6 | `bots/base.py` | `_sanitize_tool_data` / `OutputMode.TELEGRAM`,`MSTEAMS` | 1282, 1318-1319 | WS3 — channel egress hop (b); JSON-safety only, no redaction | F006 |
| 7 | `bots/data.py` | forbidden-patterns (system-prompt prose) | 296-300 | WS1/Q4 — prompt-layer forbidden-IO list to promote | F007 |
| 8 | `parrot_tools/shell_tool/security.py` | `CommandSanitizer` / `SecurityPolicy` / `SecurityLevel` / `ValidationResult` | whole file (~42.7 KB) | Foundation — reuse target; must relocate into core | F001 |
| 9 | `parrot/security/` | core security package | package | Foundation — established home for relocated engine + new gates | F009 |
| 10 | `tools/agent.py` | `_inject_context_to_repl` | 404-422 | WS1 — in-process REPL state coupling (keeps subprocess deferred) | F008 |
| 11 | `tools/dataset_manager/tool.py` | `set_repl_locals_getter` / `_repl_locals_getter` | 538, 604-610 | WS1 — `data_analysis` DataFrame state-sharing dependency | F008 |

### 2.2 Constraints Discovered

- **Dependency direction `parrot_tools → core`.** Core cannot import `shell_tool`;
  any shared engine **must** relocate down into `parrot.security`.
  *Implication*: reuse = move `CommandSanitizer`/`SecurityPolicy` into core + re-export.
  *Evidence*: F001, F009

- **Secrets stay in `os.environ`** (Q1 closed; `python-dotenv` + K8S inject).
  *Implication*: the env-access gate (WS1) and the in-bound scrubber (WS3) are
  **load-bearing, not redundant**. *Evidence*: F002, F005

- **`data_analysis` REPL shares in-process namespace** (`globals` injection +
  DataFrame getter). *Implication*: subprocess isolation breaks both paths without a
  state channel — stay in-process. *Evidence*: F008

- **`AbstractTool.execute()` is the single seam** where every tool's raw output
  becomes a `ToolResult`. *Implication*: hooking the scrubber once here covers all
  tools (incl. `python_repl`) for free. *Evidence*: F004

- **A tactical fix is already committed** (`0f76129b1`) with tests.
  *Implication*: FEAT-252 must **not regress** the shipped denylist/redaction while
  consolidating. *Evidence*: F002, F003, F005, F010

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched files |
|--------|------|---------|---------------|
| `0f76129b1` | this FEAT's partial impl | security on llm clients and agents | `pythonrepl.py`, `google/client.py`, `bots/agent.py`, `security/redaction.py`, both test files, brainstorm md |
| `88e7a5a53` | ~60d window | Remove Bokeh/HoloViews/D3 output modes | unrelated |
| `dd7e0666e` | ~60d window | skill registry + pandas agent fixes | unrelated |

> The partial work is **committed on dev**, not in a dangling worktree, and ships
> with `test_pythonrepl_security.py` (38 lines) + `test_google_client.py` edits [F010].

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`PythonExecutionPolicy` + `PythonCodeSanitizer`** — allowlist-first AST gate
  with `general` vs `data_analysis` profiles (deny-by-default). *Evidence*: F002
- **`_resolve_final_response`** — one deterministic Gemini exit gate (provenance /
  echo classification + scrub) all 6 terminal sites funnel through. *Evidence*: F003
- **`OutputScrubber`** — policy-driven, reason-tagged (`***REDACTED:<reason>***`),
  audit-logged, idempotent, allowlist-aware; hooked **once** at
  `AbstractTool.execute()`. *Evidence*: F004, F005
- **Relocated shared engine** — `CommandSanitizer`/`SecurityPolicy`/`SecurityLevel`
  moved into `parrot.security` and re-exported to `parrot_tools`. *Evidence*: F001, F009

### What Changes

- **`pythonrepl.py`** — denylist → allowlist-first gate; promote the `bots/data.py`
  forbidden-IO list (Q4) into deterministic categorical denial. *Evidence*: F002, F007
- **`google/client.py`** — remove the ~14 scattered `redact_*` calls; route all
  terminal text through `_resolve_final_response`; gate `default_api`/`tool_code`;
  return a **typed "no answer produced"** on empty-after-tools (no forced-synthesis
  latency). *Evidence*: F003
- **`security/redaction.py`** — evolve flat `[REDACTED]` into the policy `OutputScrubber`
  built on the relocated engine. *Evidence*: F005, F001
- **`bots/base.py`** — egress (TELEGRAM/MSTEAMS) reuses the scrubber. *Evidence*: F006
- **System prompt** — explicit **closed tool manifest** ("there is no `default_api`").

### What's Untouched (Non-Goals)

- Moving secrets out of `os.environ` (Q1, deferred).
- Subprocess/seccomp isolation of the REPL (deferred; in-process coupling [F008]).
- Credential rotation / log purge (operational).
- Per-tenant data-plane authorization (`AuthorizingDataSource` track).

### Patterns to Follow

- `shell_tool` `SecurityPolicy.restrictive()` / `SecurityLevel` + `ValidationResult`
  verdict shape for the Python gate. *Evidence*: F001
- Single-seam interception at `AbstractTool.execute()`, not per-call-site. *Evidence*: F004

### Integration Risks

- **Allowlist too tight** breaks legitimate pandas/numpy analysis → needs calibration
  over real agent usage. *Evidence*: F002
- **Refactoring 6 `from_gemini` exits into one chokepoint** risks behavioral / latency
  drift in `ask_stream`/streaming. *Evidence*: F003
- **Relocating `shell_tool` primitives** can break `parrot_tools` imports if the
  re-export is incomplete. *Evidence*: F001

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | A tactical fix is already committed on dev (`0f76129b1`) across all the brainstorm's files | F010 | high | `git show --stat` read directly |
| C2 | `python_repl` shipped as a **denylist** (`_check_ast_security` + `BLOCKED_*`), not the allowlist-first `PythonCodeSanitizer` | F002 | high | block lists + walk logic read directly |
| C3 | No `_resolve_final_response` chokepoint; redaction scattered ~14 sites, 6 `from_gemini` terminals | F003 | high | grep absent for method; sites enumerated |
| C4 | `AbstractTool.execute()` is the single in-bound seam (a) and is **not** hooked | F004 | high | `execute()` branches + return read; no scrub call |
| C5 | `security/redaction.py` is flat-marker standalone, not the policy `OutputScrubber`, not on the `shell_tool` engine | F005, F001 | high | full module read |
| C6 | Shared engine **must** relocate into core (`parrot_tools → core` forbids upward import) | F001, F009 | medium | documented convention, not re-verified vs import graph |
| C7 | `bots/data.py` forbidden-IO patterns are prompt-prose only, promotable | F007 | high | prose located in a system-prompt string |
| C8 | In-process isolation is correct near-term (`data_analysis` shares REPL namespace) | F008 | high | `globals` injection + locals getter read |

Distribution: **7** high, **1** medium, **0** low.

> Overall confidence is **medium**, bounded not by the (high-confidence)
> localization but by the four *design-depth* decisions in §5 — now resolved — and
> by C6 (relocation necessity) being the one inferred-from-convention claim.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **WS1 posture — denylist (shipped) vs allowlist-first?** — *Resolved*:
  **Allowlist-first gate.** Build `PythonCodeSanitizer`/`PythonExecutionPolicy`
  (`general` vs `data_analysis` profiles), deny-by-default. *Resolves*: C2
- [x] **WS2 scope — chokepoint + empty-after-tools policy?** — *Resolved*:
  **Single `_resolve_final_response` chokepoint**; consolidate the 6 `from_gemini`
  exits, remove the 14 scattered redact calls, gate `default_api`, and return a
  **typed "no answer produced"** on empty (no forced-synthesis latency). *Resolves*: C3
- [x] **WS3 depth — evolve `redaction.py`?** — *Resolved*: **Policy `OutputScrubber`
  + single seam.** Reason-tagged + audit-logged + allowlist-aware, hooked once at
  `AbstractTool.execute()`. *Resolves*: C4, C5
- [x] **Foundation — reuse the `shell_tool` engine how?** — *Resolved*:
  **Relocate into core.** Move `CommandSanitizer`/`SecurityPolicy`/`SecurityLevel`
  into `parrot.security`, re-export to `parrot_tools`. *Resolves*: C6

### Unresolved (defer to spec / implementation)

- [ ] **Allowlist calibration (WS1)** — exact permitted builtin/import set per profile,
  tight enough to kill arbitrariness, wide enough not to reject genuine analysis.
  *Owner*: tbd · *Blocks*: C2 · needs a pass over real `python_repl` usage.
- [ ] **Echo-detection threshold (WS2)** — similarity metric/cutoff to flag `tool_echo`
  without false-positiving legitimate summaries. *Owner*: tbd · *Blocks*: C3

> 2 unresolved, both implementation-calibration details suited to the spec phase.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-252`** — *Rationale*: localization is high-confidence and the seams
are verified (C1–C5, C7–C8); the four design decisions are resolved (§5) and become
acceptance criteria. The codebase contract is already verified, so `/sdd-brainstorm`
would be redundant. The spec should pin: (a) the allowlist policy + profiles, (b) the
`_resolve_final_response` contract and the typed-empty behavior, (c) the `OutputScrubber`
policy schema + the `AbstractTool.execute()` hook, (d) the engine relocation + re-export,
and (e) a **non-regression** guard over the shipped `0f76129b1` tests.

### Alternatives

- **`/sdd-task FEAT-252`** — only if you accept descoping to the WS3 single-seam +
  `default_api` gate as a fast follow-up (not chosen — the resolved scope is larger).
- **Manual review** — not needed; research complete, not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-252/state.json` |
| Source (raw) | `sdd/state/FEAT-252/source.md` |
| Research plan | `sdd/state/FEAT-252/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-252/findings/F001..F010-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-252/synthesis.json` |

**Budget consumed**: files read 7/40 · grep 4/25 · git 1/10 · depth 0/2 · **truncated: no**.

**Mode determination**: `enrichment` (explicit) → confirmed (source defines workstreams
to build; the bug mechanism was already verified, and research found a partial
implementation to harden).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (`/sdd-proposal`) |
