---
id: FEAT-531
title: Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it
slug: wikitoolkit-cli-llm-fallback
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-06
  summary_oneline: Auto-detect Claude Code/Codex CLI and default wikitoolkit/bookstore LLM to it with a visible warning
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-531/
created: 2026-09-06
updated: 2026-09-06
---

# FEAT-531 — Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-531/`](../state/FEAT-531/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-531/source.md`.

> en repositorios recien creados enfrento que el LLM by default para wikitoolkit es Gemini:
> `[WARNING] ... TOC detector failed on page 0: No LLM configured for the bookstore`, sin
> embargo hace ya algun tiempo que tenemos Claude Agent SDK y un cliente LLM de ai-parrot
> usando las credenciales de Claude Code, además, "wikitoolkit build" es basicamente un cli
> command por lo que es más común que lo ejecutemos en una consola con Claude Code o OpenAI
> Codex que con Gemini Google, por lo que propondría un cambio: en la primera ejecución
> detectar con un safe-execution si contamos con acceso a Claude Code y entonces definir que
> ese sea el LLM by default (si hay que definir un modelo LLM, sería haiku, ya que
> wikitoolkit summary es algo determinista).
>
> Follow-up: la filosofia cambia porque ahora busco la facilidad de uso con poca o ninguna
> configuracion, si ya el usuario tiene una consola de Claude Code (o Codex) configurada, no
> tendría por qué generar un API key e inyectarlo en un .env, bastaría con que el comando
> advirtiera con un warning visible que va a usar Claude Code como default en WIKI_MODEL,
> etc. y ya el usuario verá si cambia de LLM.

**Initial signals** (extracted, not interpreted):
- Verbs: "propondría un cambio", "detectar", "definir" → feature proposal, not a bug report.
- Named entities: `wikitoolkit`, `bookstore`, Claude Agent SDK, Claude Code, OpenAI Codex, Gemini, haiku.
- Components: `packages/ai-parrot/src/parrot/knowledge/wiki/`, `packages/ai-parrot/src/parrot/knowledge/bookstore/`.
- Acceptance criteria provided: no (informal proposal) — codified in §3/§5 below.

---

## 1. Synthesis Summary

The requester hit `wikitoolkit`/`bookstore`'s degraded (no-LLM) mode on a freshly created
repo and read it as "defaults to Gemini." Research shows that's not quite what's happening:
neither subsystem defaults to any provider — `bookstore/_llm.py::resolve_adapter` and three
resolution points in `wiki/cli.py` all require an explicit env var and otherwise degrade
silently by design. The real, and more useful, ask (confirmed in a follow-up from the
requester) is a deliberate philosophy shift toward zero-friction usability: when
`PARROT_BOOKSTORE_LLM` / `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL` / `WIKI_EXTRACT_LLM` are
unset, auto-detect an available coding-agent CLI (Claude Code first, Codex second) via a
cheap, non-invasive check, and default to it — visibly, with an unmissable warning and an
opt-out — rather than either failing or asking for a separate provider API key. This is
cheaper to build than it first looks: `ClaudeAgentClient` and `OpenAICodexClient` are already
registered `LLMFactory` providers (`claude-code`, `codex-code`, …), so the work is a small
shared detection helper plus four call-site changes, not new client code.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted at
> `sdd/state/FEAT-531/findings/`. Each cites the finding ID(s) that justify its inclusion.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py` | `resolve_adapter` | 35-75 | single shared LLM-resolution seam for bookstore CLI + MCP server | F001, F003 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | `_NullAdapter` | 59-78 | degraded-mode stand-in; raises the exact error the requester saw | F004 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | `_extract_into_graph` | 2712-2723 | resolves `WIKI_EXTRACT_LLM`, skips (not error) when unset | F005 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | `_resolve_model_id` | 3409-3428 | generic "flag or env, else `ClickException`" resolver | F005 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | `_build_triage_adapters` | 3431-3462 | builds light+heavy `PageIndexLLMAdapter` pair; same-provider constraint | F005 |
| 6 | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py` | `ClaudeAgentClient` | 1-16 | already-registered client wrapping `claude-agent-sdk` / the `claude` CLI | F002, F008 |
| 7 | `packages/ai-parrot-client-anthropic/pyproject.toml` | `entry-points.parrot.clients` | 26-32 | registers `ClaudeAgentClient` under `claude-agent` / `claude-code` | F002 |
| 8 | `packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py` | `OpenAICodexClient` | 46-81, 656-660 | symmetric client wrapping the `codex` CLI | F007, F008 |
| 9 | `packages/ai-parrot-client-openai/pyproject.toml` | `entry-points.parrot.clients` | 37-41 | registers `OpenAICodexClient` under `codex-agent` / `openai-codex` / `codex-code` | F007 |
| 10 | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/models.py` | `ClaudeModel.HAIKU_4_5` | 12-24 | `"claude-haiku-4-5-20251001"` — the cheap/deterministic model already available | F002 |
| 11 | `packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py` | `_AGENTS` | 45-49 | names the 3 canonical CLI ids (codex/claude/gemini) for a different purpose (wiki hooks) | F006 |

### 2.2 Constraints Discovered

- **Degraded mode is intentional, not a bug.** `_llm.py`'s docstring states explicitly:
  "When nothing is configured the bookstore runs degraded (BM25/catalog only) — that is a
  supported mode, not an error." *Implication*: this proposal is a genuine, deliberate
  philosophy change and should be described as one, not framed as "fixing a wrong default."
  *Evidence*: F003

- **Light/heavy models must share a provider.** `_build_triage_adapters`'s docstring: "mixing
  providers there would send one provider's client a model id meant for a different
  provider." *Implication*: the auto-default must pick one provider and apply it to both the
  heavy and lightweight model env vars together, never mix Claude for one and Codex for the
  other. *Evidence*: F005

- **Both target clients already guard real work behind a lazy, exception-safe import.**
  `ClaudeAgentClient`'s module docstring: "The `claude_agent_sdk` import is strictly lazy...
  safe even when the optional extra is not installed." `OpenAICodexClient._import_sdk()`
  mirrors this. *Implication*: detection can safely reuse `try: import <sdk>` +
  `shutil.which(<cli_bin>)`, with zero subprocess/network calls during the probe itself.
  *Evidence*: F002, F007, F008

- **No cheap Codex model id was found in this pass.** Only `OpenAICodexClient.default_model
  = "gpt-5.1-codex"` surfaced; no Haiku-equivalent "mini" tier. *Implication*: resolved in
  §5 — ship with `default_model` as-is per the requester's decision. *Evidence*: F007

### 2.3 Recent History (Relevant)

Not queried — this proposal is enrichment-mode, and the four resolution points involved are
long-standing, stable seams (no evidence of recent churn was needed to establish scope).

---

## 3. Probable Scope

### What's New

- **`parrot/clients/detection.py`** (proposed path, core package) — a provider-agnostic
  `detect_coding_agent_llm() -> Optional[str]` helper. Checks, in order: `claude` (via
  `shutil.which("claude")` + lazy `claude_agent_sdk` import), then `codex` (via
  `shutil.which("codex")` + lazy Codex SDK import). Returns an `LLMFactory` spec string
  (`"claude-code:claude-haiku-4-5-20251001"` or `"codex-code:gpt-5.1-codex"`) or `None`.
  Never sends a real request — detection is import/PATH-only, matching the pattern already
  used inside both clients (F008).

### What Changes

- **`packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`::`resolve_adapter`** — when
  `PARROT_BOOKSTORE_LLM` is unset (and `PARROT_NO_AUTO_LLM` is not set), fall back to
  `detect_coding_agent_llm()` before returning degraded `(None, None, None)`; on a hit, log a
  visible warning naming the auto-selected spec and how to override it (`PARROT_BOOKSTORE_LLM`).
  *Evidence*: F001, F003
- **`packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`** — the three resolution points
  (`_extract_into_graph`, `_resolve_model_id`, `_build_triage_adapters` call sites) fall back
  to the same helper instead of erroring/skipping when `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL`
  / `WIKI_EXTRACT_LLM` are unset, with the same visible-warning contract.
  *Evidence*: F005

### What's Untouched (Non-Goals)

- `ClaudeAgentClient` and `OpenAICodexClient` themselves — no client-level changes; this is
  purely a defaulting/detection layer above `LLMFactory.create()`.
- The explicit-config path — any of `PARROT_BOOKSTORE_LLM` / `WIKI_MODEL` /
  `WIKI_LIGHTWEIGHT_MODEL` / `WIKI_EXTRACT_LLM` set by the user always wins over
  auto-detection, unchanged.
- Gemini/Google support — remains fully available as an explicit choice; it is simply never
  auto-selected.
- Detecting a `gemini` CLI as an auto-default candidate — out of scope per the source request
  (Claude Code / Codex only).

### Patterns to Follow

- Lazy heavy imports under stdout→stderr redirect, matching `_llm.py`'s existing "safe to
  import from the MCP server" constraint. *Evidence*: F001, F003
- The `try: import <sdk>; except ImportError` idiom already used inside both target clients.
  *Evidence*: F008
- Never fail startup on detection/resolution failure — degrade gracefully with a warning,
  matching the existing `except Exception: return None, None, None` pattern. *Evidence*: F003

### Integration Risks

- **Silent-feeling behavior change on any machine with `claude`/`codex` on `PATH`.** Mitigated
  by the mandatory visible warning and the `PARROT_NO_AUTO_LLM` opt-out (resolved in §5).
  *Evidence*: F003, F004
- **Provider precedence ambiguity when both CLIs are present.** Resolved in §5 (Claude Code
  always wins by default). *Evidence*: none (policy decision, not a code finding)

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | No code path in bookstore or wikitoolkit currently defaults to Gemini or any provider; unset env vars mean fully degraded/no-LLM mode by design | F003, F004 | high | direct read of source + docstring stating this is intentional |
| C2 | `ClaudeAgentClient` is already a fully registered `LLMFactory` provider under `claude-code`, zero new client code required | F002 | high | entry point + class read directly |
| C3 | `OpenAICodexClient` is already a fully registered `LLMFactory` provider under `codex-code`/`openai-codex`, zero new client code required | F007 | high | entry point + class attributes read directly |
| C4 | `ClaudeModel.HAIKU_4_5` (`claude-haiku-4-5-20251001`) is the correct, already-existing cheap/deterministic model id for the Claude Code default | F002 | high | enum value read directly |
| C5 | A safe, non-invasive detection check ("shutil.which + lazy SDK import") mirrors what both clients already do internally, with no subprocess/network call | F008 | high | both clients' own lazy-import code confirms the idiom is already established here |
| C6 | The fix touches exactly two existing files plus one new shared helper module | F001, F005 | medium | confirmed for all resolution points this pass's greps found; a 4th call site elsewhere in `wiki/cli.py`'s ~4300 lines can't be fully ruled out |
| C7 | No existing reusable CLI-availability-detection utility exists elsewhere in the repo | F006 | medium | `coding_agents.py` was the strongest match and doesn't probe availability; search wasn't exhaustive |
| C8 | No cheap/"mini" Codex model id is documented in this codebase today | F007 | low | only `default_model` was inspected; resolved as a policy decision in §5 rather than further researched |

Distribution: **5** high, **2** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **When both `claude` and `codex` CLIs are detected, which wins by default?** —
  *Resolved*: Claude Code always wins by default.
  *Resolves claims*: C6 (precedence policy)

- [x] **What should the opt-out mechanism be, and what scope should it cover?** —
  *Resolved*: one global env var, `PARROT_NO_AUTO_LLM=1`, disabling auto-detection for both
  bookstore and wikitoolkit at once.
  *Resolves claims*: C6 (opt-out policy)

- [x] **What model id should the Codex fallback use, given no cheap tier was found?** —
  *Resolved*: use `OpenAICodexClient.default_model` (`"gpt-5.1-codex"`) as-is; ship Codex
  detection in this same feature, not deferred.
  *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

- [ ] **Exact warning message text/format** (log level, whether it also appears as `click.echo`
  in the wikitoolkit CLI vs. only `logger.warning` in bookstore, and the precise override
  instructions shown). *Owner*: spec author. *Blocks*: none (implementation detail, not a
  scope fork).
- [ ] **Whether a 4th LLM-resolution call site exists elsewhere in `wiki/cli.py`** beyond the
  three found (C6, medium confidence) — worth a targeted re-grep at spec time before task
  decomposition, to avoid an incomplete rollout.

> Two unresolved items remain, both implementation-detail-level — well under the 5-item
> escalation threshold, and neither is an architectural fork.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-531`** — *Rationale*: localization is high-confidence across both
subsystems and both required clients already exist and are registered; the resolved
unknowns (precedence, opt-out naming, Codex model id) are now settled inputs to the spec, and
the two remaining open items are implementation details a spec's Codebase Contract section
can close, not an architectural fork that would need a brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-531`** — not recommended; there is no real architectural fork here
  (both target clients and the detection idiom are already established), so a brainstorm
  would mostly restate this proposal's §3.
- **`/sdd-task FEAT-531`** — possible if the team wants to skip a formal spec given the small,
  well-bounded footprint (2 files + 1 new helper), but a spec is still recommended to pin
  down the exact warning text and the same-provider light/heavy pairing contract before
  tasks are cut.
- **Manual review** — not applicable; research was not truncated and no contradictions
  surfaced.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-531/state.json` |
| Source (raw) | `sdd/state/FEAT-531/source.md` |
| Research plan | `sdd/state/FEAT-531/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-531/findings/F001-*.md` … `F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-531/synthesis.json` |

**Budget consumed** (`default` profile):
- Files read: 9 / 40
- Grep calls: 9 / 25
- Git calls: 0 / 10
- Wall time: ~660s / 300s cap *(research ran across an earlier exploratory pass in the same
  conversation, reconstructed into this budget profile after the fact — see note below)*
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source describes a desired new
capability, not a failure to diagnose).

> Note on audit fidelity: this proposal's research was conducted conversationally before the
> formal `/sdd-proposal` state machine was invoked, then reconstructed into the standard
> `research_plan.json` / `findings/` / `synthesis.json` artifacts for persistence and audit.
> All citations were re-verified against the actual files at proposal-render time.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Code (jesuslarag@gmail.com) |
