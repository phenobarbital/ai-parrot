---
id: FEAT-519
title: Shared Rich console layer for the parrot CLI — fix streamed-response rendering in `parrot agent`
slug: new-cli-infra
type: feature
mode: investigation
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-02
  summary_oneline: Refactor the parrot CLI console (parrot agent <agent_id>) from raw stdout writes to a shared Rich presentation layer
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-519/
created: 2026-09-02
updated: 2026-09-02
---

# FEAT-519 — Shared Rich console layer for the parrot CLI

> **Mode**: investigation
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-519/`](../state/FEAT-519/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-519/source.md`.

> the current CLI console of parrot ("parrot agent {agent_id}") is using direct
> print to stdout but this look&feel and usability in cli console is very poor
> and cheap, idea is refactor the current cli for using a combination of `Rich`
> as output, prompt_toolkit (currently in use) with color format, etc or
> `Textual` for chat area with own scrolling + markdown widget and InquirerPy
> for confirmation, HITL and other iteractions.

**Initial signals** (extracted, not interpreted):
- Verbs: "using direct print", "refactor" → asserts a defect, requests a change
- Named entities: `parrot agent`, Rich, prompt_toolkit, Textual, InquirerPy
- Components / labels: none (inline source)
- Acceptance criteria provided: no
- Self-declared ambiguity: "Rich + prompt_toolkit **or** Textual" — the source
  itself leaves the architecture undecided

---

## 1. Synthesis Summary

The premise is half true, and the half that is false matters. `parrot agent` is
**not** a `print()`-based console: it already renders through Rich end to end —
banner, errors, `--list` tables, Markdown output, tool-call panels, token usage —
and `packages/ai-parrot/src/parrot/cli` contains **zero** `print()` calls. The
actual defect is one function: `ResponseRenderer.render_stream_chunk` writes raw
`sys.stdout.write(text)`, and because `REPLConfig.streaming` defaults to `True`,
that raw path is what every user sees by default while the good Markdown renderer
is reachable only via `--no-stream`. The in-code reason is a real conflict between
`rich.live.Live` and `prompt_toolkit.patch_stdout()` — but the sibling command
`parrot devloop` already solved that exact conflict in the same package with a
modal pause/resume discipline, so this is a **homologation** feature, not a
greenfield TUI adoption. Rich, prompt_toolkit and questionary are already core
dependencies; `InquirerPy` would duplicate questionary (which already powers
`parrot agent`'s own picker) and `Textual` appears in no `pyproject.toml` in the
repository — both were rejected in Q&A in favour of extracting a shared Rich
console layer.

---

## 2. Codebase Findings

> All entries are grounded in the research findings persisted at
> `sdd/state/FEAT-519/findings/`. Each cites the finding ID(s) that justify its
> inclusion. **No fabricated paths or symbols.**
>
> ⚠️ **Line numbers are against post-`7c2790044` HEAD.** `dev` advanced by two
> commits *during* this research run; every reference below was re-verified
> after the move (F011).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/cli/renderer.py` | `ResponseRenderer.render_stream_chunk` | 248-260 | **ROOT CAUSE** — the only raw stdout write on the interactive display path | F003 |
| 2 | `packages/ai-parrot/src/parrot/cli/renderer.py` | `ResponseRenderer.render_stream_start` | 233-246 | documents why `Live` was abandoned; the constraint to overturn | F004 |
| 3 | `packages/ai-parrot/src/parrot/cli/renderer.py` | `ResponseRenderer.render_stream_end` | 262-280 | discards `_stream_buffer` without ever re-rendering it as Markdown | F003 |
| 4 | `packages/ai-parrot/src/parrot/cli/renderer.py` | `_BlockingSafeFile` | 22-56 | **WORKAROUND #2** (landed mid-research) — retries writes that `BlockingIOError` because `patch_stdout()` makes the fd non-blocking | F011 |
| 5 | `packages/ai-parrot/src/parrot/cli/repl.py` | `_mute_stream_loggers` / `_restore_stream_loggers` | 27-58, 247, 279 | **WORKAROUND #3** (landed mid-research) — silences console log handlers during a stream so log lines stop interleaving with tokens | F011 |
| 6 | `packages/ai-parrot/src/parrot/cli/repl.py` | `REPLConfig.streaming` | 82-85 | defaults `True`, making the degraded path the default UX | F003 |
| 7 | `packages/ai-parrot/src/parrot/cli/repl.py` | `AgentREPL.run` | 131-198 | monolithic loop; owns `patch_stdout()`, exposes no post-turn hook | F003, F004, F008 |
| 8 | `packages/ai-parrot/src/parrot/cli/devloop/renderer.py` | `RunView.pause` / `.resume` / `.run_live` | 82-107 | **REFERENCE** — the working `Live`-under-`patch_stdout` pattern to homologate | F005 |
| 9 | `packages/ai-parrot/src/parrot/cli/devloop/console.py` | `DevLoopConsole._handle_gates` | 903-969 | **REFERENCE** — modal pause/prompt/resume call sequence | F005 |
| 10 | `packages/ai-parrot/src/parrot/cli/loaders.py` | `StandaloneAgentLoader.select_agent` | 103-120 | `questionary.select()` already serves `parrot agent`'s picker — InquirerPy would duplicate it | F006 |
| 11 | `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py` | `_wrap_with_event_drain` | 205-230 | **BLAST RADIUS** — second consumer, monkeypatches around the missing post-turn hook | F008 |
| 12 | `packages/ai-parrot/tests/cli/test_integration.py` | `TestResponseRenderer` / `TestAgentREPLStream` / `TestCLICommandAgent` | 29-491 | regression net the refactor must keep green | F009 |
| 13 | `packages/ai-parrot/src/parrot/cli/wizard.py` | generic Pydantic wizard engine | — | specified as generic and reusable (devloop spec G2) — reuse candidate | F010 |

### 2.2 Constraints Discovered

- **The `Live` / `patch_stdout` conflict is real.** `rich.live.Live` emits
  cursor-control ANSI (`\x1b[2K`, `\x1b[?25l`) that `patch_stdout()`'s
  `StdoutProxy` mangles into literal `?[2K`. Every `Console` in the CLI already
  works around it with `file=sys.__stdout__, force_terminal=True`.
  *Implication*: any solution must own the terminal cooperatively, not naively.
  *Evidence*: F004

- **…and it is already solved in-repo.** `devloop` runs `Live` and
  `prompt_async()` together by pausing the Live region around every prompt —
  its docstring states the rule: *"one writer at a time"*.
  *Implication*: the constraint recorded in `renderer.py` is unsolved in the
  agent REPL only, not unsolvable. *Evidence*: F005

- **Three stacked workarounds now compensate for one unaddressed seam**, two of
  which landed on 2026-09-02 *while this research ran*, and neither touched
  `render_stream_chunk`: the `sys.__stdout__` proxy bypass, `_BlockingSafeFile`
  write-retry, and `_mute_stream_loggers` log suppression.
  *Implication*: the surface is accreting point fixes because there is no
  presentation seam to fix properly. *Evidence*: F011, F004

- **Log lines interleaving with streamed tokens** is an additional symptom, not
  named in the original request, already being worked around in code.
  *Implication*: it must be an acceptance criterion, not an afterthought.
  *Evidence*: F011

- **Rich, prompt_toolkit and questionary are already core dependencies**
  (`rich>=13.0`, `prompt_toolkit>=3.0`, `questionary>=2.1.1`); Rich spans 30
  files across 4 distributions. `Textual` appears in **zero** `.toml` files.
  *Implication*: a Rich-based refactor extends convention; Textual would
  introduce a stack. *Evidence*: F006, F007

- **`AgentREPL` / `ResponseRenderer` / `REPLConfig` are a de-facto public API**,
  imported cross-package by `ai-parrot-integrations`' agentd CLI.
  *Implication*: constructor signatures cannot change silently; a coordinated
  cross-package change is required. *Evidence*: F008

- **`AgentREPL.run()` exposes no post-turn hook**, forcing agentd to shadow
  `send`/`send_stream` at the instance level — its own docstring says so.
  *Implication*: a real hook retires the monkeypatch. *Evidence*: F008

- **`RunView` is coupled to dev-loop `SessionHost` semantics** (`replay_since`,
  gate handlers) and cannot be instantiated by the agent REPL as-is.
  *Implication*: homologate the *pattern*; do not import the class.
  *Evidence*: F005

- **The FEAT-168 suite is mock-based** and covers the renderer, both send paths,
  slash commands and the Click command; devloop has its own console/renderer
  suite that models how to test a `Live` console.
  *Implication*: a green-test bar exists and a testing template exists.
  *Evidence*: F009

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `7c2790044` | 2026-09-02 22:32 | Jesus | fixing the usage of LLMs in CLI console | `cli/renderer.py` (+42, `_BlockingSafeFile`), `cli/agent_repl.py` (+11, bot cleanup), `clients/*` |
| `3b5e4fed5` | 2026-09-02 21:30 | Jesus | fix over REPL of CLI agents | `cli/repl.py` (+42, log muting) |
| `99ad3ddf3` | — | — | fix: FirefliesObsidianAgent tool registration, REPL quit/exit handling, streaming renderer | `cli/` |
| `d92fdac86` | — | — | feat(devloop-cli-homologation): TASK-1970 — console kind picker, wizard path | `cli/devloop/` |
| `ecd2d205d` | — | — | feat(agent-cli-daemon): TASK-2216 — CLI commands + LazyGroup registration | `cli/__init__.py` |

The dominant recent theme is **devloop console work** — investment has been
flowing into the sibling console, which is why it has outgrown `parrot agent`.
*Evidence*: F009, F011

---

## 3. Hypothesis

### Hypothesis 1 — The degraded look & feel is the raw streaming write, not the styling · Confidence: **high**

**Supporting evidence**: F001, F002, F003, F004, F005
**Contradicting evidence**: —
**Reasoning**: The batch path already renders Markdown, panels and tables
(`renderer.py:89-122`). `REPLConfig.streaming` defaults to `True`, and the one
raw `sys.stdout.write` sits exactly on that default path, discarding Markdown,
syntax highlighting and wrapping. `_stream_buffer` even accumulates the full text
— then throws it away at `render_stream_end` (line 280) without re-rendering.

**Suggested next probe**:
```bash
source .venv/bin/activate
parrot agent <agent_id> --no-stream   # markdown, panels, tables — the good path
parrot agent <agent_id>               # raw tokens — the default path
```

### Hypothesis 2 — The structural cause is a missing presentation seam · Confidence: **high**

**Supporting evidence**: F004, F008, F011
**Contradicting evidence**: —
**Reasoning**: `AgentREPL.run()` is a monolithic loop with no rendering-strategy
seam and no post-turn hook, so neither the agent console nor agentd can vary
presentation without monkeypatching — agentd's docstring names this outright.
Three unshared `Console` instances (`agent_repl.py:25`, `repl.py:128`,
`renderer.py:80`) mean theme, width and record settings have no single
configuration point. F011 is the clinching evidence: two more workarounds
accreted on this seam *during the research run itself* rather than a fix at the
source.

### Hypothesis 3 — ~~A full Textual TUI would dissolve the conflict outright~~ · **REJECTED (U1)** · Confidence: low

**Reasoning for rejection**: Textual would genuinely dissolve the
`Live`/`patch_stdout` conflict by owning the screen, but it is a new dependency
(absent from every `pyproject.toml`), a rewrite of the input layer, incompatible
with piping/non-TTY use, and would fork the agent console away from devloop's
Rich conventions rather than homologating with them. The conflict it would solve
is already solved in-repo by cheaper means. Rejected by the user at U1.
*Evidence*: F005, F006, F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `parrot agent` already uses Rich; zero `print()` in `parrot/cli` | F001, F002, F003 | high | direct read of all four modules + repo-wide grep returning no matches |
| C2 | `render_stream_chunk`'s raw `sys.stdout.write` is the root cause of the degraded default UX | F003 | high | direct read; only raw display write in the tree |
| C3 | `streaming=True` is the default, so the degraded path **is** the default | F003 | high | direct read of `REPLConfig` field default |
| C4 | The `Live`-vs-`patch_stdout` conflict is real and documented in-code | F004 | high | two in-repo docstrings state the failure mode explicitly |
| C5 | `devloop` already solved that conflict with pause/resume, same package | F005 | high | direct read of `RunView.pause/resume` and its call sites |
| C6 | `questionary` is already core **and** already used by `parrot agent`'s picker | F006 | high | pyproject dep + three call sites incl. `loaders.py` |
| C7 | `Textual` is in no `pyproject.toml` in the repo | F006 | high | exhaustive grep over `*.toml` returned zero matches |
| C8 | Rich is established across 30 files in 4 distributions | F007 | high | repo-wide import grep |
| C9 | agentd is a 2nd consumer whose monkeypatch could be retired by a proper hook | F008 | high | direct read; the workaround's own docstring names the missing hook |
| C10 | A FEAT-168 mock-based suite covers the REPL and must stay green | F009 | high | direct read of test classes |
| C11 | Three workarounds now compensate for one seam; two landed during this run | F011 | high | git log + diff of both commits |
| C12 | Extracting a shared console seam is the right fix, not patching one function | F004, F008, F011 | high | upgraded from medium by C11 |
| C13 | `cli/wizard.py` is reusable by the agent console | F010 | medium | spec'd as generic (devloop G2), but reuse outside devloop not yet demonstrated |

Distribution: **12** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Inline Rich + pause/resume, or a full-screen Textual app?**
  *Resolved*: Inline Rich + pause/resume. Keep prompt_toolkit and adopt devloop's
  modal "one writer at a time" Live discipline so streamed tokens render as
  Markdown in a Live region that pauses around every prompt. No new dependencies;
  converges with devloop; piping/non-TTY preserved; the three stacked workarounds
  become removable. **Textual is explicitly NOT adopted.**
  *Resolves claims*: C4, C5, C7, C12

- [x] **U2 — InquirerPy, or the questionary already in core?**
  *Resolved*: Keep `questionary` (already core `>=2.1.1`, already powers
  `parrot agent`'s own picker at `loaders.py:103-120`). **InquirerPy is
  explicitly NOT adopted.**
  *Resolves claims*: C6

- [x] **U3 — How wide should the refactor go?**
  *Resolved*: Extract a shared console/presentation layer used by `parrot agent`,
  `parrot devloop` and `parrot attach` — single `Console`, one `Live` discipline,
  pluggable renderer. Cross-package refactor, accepted.
  *Resolves claims*: C9, C12

- [x] **U4 — Give `AgentREPL` a real post-turn hook?**
  *Resolved*: Yes — add the hook and retire agentd's `send`/`send_stream`
  instance-level monkeypatch.
  *Resolves claims*: C9

### Unresolved (defer to spec / implementation)

- [ ] **Does `cli/wizard.py` actually generalise to the agent console, or is it
  devloop-shaped in practice?** — *Owner*: tbd
  *Blocks claims*: C13
  *Plausible answers*: a) reuse as-is · b) reuse after widening its field types ·
  c) leave it devloop-only and share only the console layer

- [ ] **Should `parrot/human/channels/cli.py` and `cli_companion.py` (an existing
  Rich-based HITL surface not named in the request) migrate onto the shared
  layer in this feature or a follow-up?** — *Owner*: tbd
  *Plausible answers*: a) this feature · b) follow-up · c) leave independent

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-519`** — *Rationale*: all four unknowns are resolved,
localization is high-confidence (C1-C5, C9-C12) and verified against
post-commit HEAD, and the architectural fork the source left open is now decided
in favour of inline Rich + pause/resume. Nothing remains that options analysis
would settle.

Suggested module shape for the spec (from §2.1 + U3/U4):

1. **Shared console layer** — one `Console` factory + `Live` pause/resume
   discipline, homologating `devloop/renderer.py:82-107`.
2. **Streaming renderer** — replace `render_stream_chunk`'s raw write with a
   Live-region Markdown painter; retire `_BlockingSafeFile` and
   `_mute_stream_loggers` as the seam makes them unnecessary.
3. **`AgentREPL` seam** — pluggable renderer + a real post-turn hook.
4. **agentd migration** — adopt the hook, delete `_wrap_with_event_drain`.
5. **devloop convergence** — move `RunView` onto the shared layer without
   regressing its behaviour.
6. **Tests** — keep `packages/ai-parrot/tests/cli/test_integration.py` green; extend using
   `packages/ai-parrot/tests/cli/devloop/test_renderer.py` as the template for Live assertions;
   add a regression test that streamed output contains rendered Markdown and
   that log records do not interleave with tokens.

### Alternatives

- **`/sdd-brainstorm FEAT-519`** — no longer warranted; the fork it would
  explore (Rich vs Textual) was decided at U1.
- **`/sdd-task FEAT-519`** — not suitable: this is a cross-package refactor
  touching a de-facto public API, not a single localized fix.
- **Manual review** — not needed; research completed within budget, untruncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-519/state.json` |
| Raw source | `sdd/state/FEAT-519/source.md` |
| Research plan | `sdd/state/FEAT-519/research_plan.json` |
| Findings (11) | `sdd/state/FEAT-519/findings/F001…F011` |
| Synthesis | `sdd/state/FEAT-519/synthesis.json` |

**Budget**: profile `default` — consumed 17 file reads / 14 greps / 4 git calls,
depth 1. **Not truncated.** Wiki orientation (`wikitoolkit query`/`related`,
budget-free) located the CLI package and the devloop precedent before any grep.

**Caveat**: `dev` advanced by two commits (`3b5e4fed5`, `7c2790044`) mid-run.
All line references were re-verified against the resulting HEAD; F011 records
what changed and why it strengthens rather than invalidates the diagnosis.
