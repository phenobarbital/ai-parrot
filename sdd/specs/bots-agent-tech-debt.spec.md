---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [agents, lifecycle, idempotency, configure, speech, tech-debt]
---

# Feature Specification: Configure-Override Idempotency & `speech_report` Hardening

**Feature ID**: FEAT-726
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

This spec drains one ledger fix group (`fixgroup:62ef5080d7a8`) — three issues
that all land in `parrot/bots/`:

| Issue | Severity | Summary |
|---|---|---|
| `issue:81fa838a18c1` | major | `configure()` overrides re-run their own work on a repeat `configure()` |
| `issue:b032fa211abd` | minor | `speech_report` narrator pick raises bare `StopIteration` on empty `self.speakers` |
| `issue:b858ae4ad636` | low | no `speech_report`-level test for the `google_tts` + verbatim zero-LLM-calls path |

**The major issue.** FEAT-721 made `AbstractBot.configure()` idempotent per
instance: it increments `self._configure_count` (`abstract.py:1603`) and returns
early when the count is above 1 *and* the resolved app is unchanged
(`abstract.py:1604`). That guard protects only the **base** pipeline. Every
subclass override does its own work around `await super().configure(app)` and is
unguarded, so the base no-ops while the subclass body runs a second time.

Verified at base `7878c0f1e`, the overrides split into two distinct shapes, and
they need two *different* fixes:

*Work AFTER `super().configure()`* — runs even though the base just no-opped:

| Site | Repeat-call effect |
|---|---|
| `bots/agent.py:191-193` | re-wires tool namespaces, **re-starts the task-memory runtime**, re-adopts task memory |
| `bots/fireflies_insights.py:153-160` | re-loads the skill registry, re-reads wiki config, re-`mkdir`s the inbox |
| `agents/obsidian.py:276-285` | **re-registers `ObsidianToolkit` tools**, re-inits Fireflies MCP, re-backfills the meeting registry |
| `bots/chrome.py:351-362` | **re-adds the Chrome DevTools MCP server** |
| `bots/flows/agents/orchestrator.py:113-115` | **re-registers every specialist agent** |
| `bots/flows/agents/a2a_orchestrator.py:275-280` | **re-registers `ListAvailableA2AAgentsTool`** (name-collision risk) and re-connects endpoints |
| `bots/a2a_agent.py:19` | **`setup_a2a(self.app, self.url)` re-registers A2A routes** on the same app — and this override is wired as an aiohttp middleware (`a2a_agent.py:14`), so repeat entry is the normal case, not the exception |
| `parrot_tools/computer/agent.py:135-139` | re-attaches the computer-use safety handler |
| `bots/document.py:253` | emits a duplicate "configured" log line |

*Work BEFORE `super().configure()`* — the base's own guard cannot help it,
because the body already ran by the time `super()` decides to no-op:

| Site | Repeat-call effect |
|---|---|
| `bots/chatbot.py:134-158` | a second `from_database()` DB round-trip, or a second `from_manual_config()` |
| `bots/voice.py:398-400` | **`setup_a2a(app, url)` re-registers aiohttp routes** on the same app |
| `bots/database/agent.py` (pre-`:331`) | re-starts toolkit pools and re-runs prefix/collision validation |
| `bots/data.py:881-889` | already naturally idempotent — gated on `not self.dataframes` |

*Assessed and deliberately left unguarded* — the full inventory is
`git grep -n 'async def configure' -- packages/ai-parrot/src packages/ai-parrot-tools/src`
filtered to `AbstractBot` descendants. These four are the sites that need **no**
change; they are listed so a later reader does not "complete" the fix by
guarding them:

| Site | Why no guard |
|---|---|
| `bots/data.py:876-889` | pre-super work is self-gating (`if self._queries and not self.dataframes`, `:881`); `_sync_dataframes_from_dm()` is a pure re-sync |
| `bots/mixins/narrative.py:51-52` | pure cooperative passthrough — `await super().configure(*args, **kwargs)` and nothing else |
| `bots/mixins/infographic_authoring.py:109-118` | pre-super `set_bot()` is **verified** idempotent: `_inject_prompt_guidance` returns early on the sentinel `"## Infographic Generation Mode" in tmpl` (`tools/infographic_toolkit.py:437-447`) |
| `bots/mixins/identity.py:49` | not code — an `async def configure` inside the `IdentityMixin` class **docstring**'s usage example |

**The prescribed pattern in the docs is wrong.** Both
`docs/agent-configure-lifecycle.md` §6 and the `configure()` docstring
(`abstract.py:1587-1588`) tell overrides to write
`if self.configure_count > 1: return`. That misfires on the one path FEAT-721
explicitly kept alive: when an app arrives where none was bound before (CLI
first, server later), the base **does** run its full pipeline, with
`_configure_count == 2`. An override guarded on `configure_count > 1` would then
skip its own setup on a configure that genuinely ran — silently trading a
double-run bug for a missing-setup bug. The override cannot re-derive the base's
decision (it depends on `resolved_app is previous_app`, resolved inside the
base), so the base must **publish** that decision.

### Goals

- Give overrides a correct, one-line signal for both shapes: whether the
  `super().configure()` that just returned actually ran its pipeline, and whether
  a `configure(app)` call is *about* to be a no-op.
- Guard every post-super override site so no repeat `configure()` re-registers a
  toolkit, re-adds an MCP server, re-registers an agent/tool, or re-starts a
  runtime.
- Guard the pre-super sites whose repeat-run is harmful; record the one that is
  already idempotent as deliberately unguarded.
- Replace the wrong `configure_count > 1` recipe in the docs and docstring with
  the correct one.
- Raise a clear error instead of a bare `StopIteration` when `self.speakers` is
  empty, and close the `google_tts` verbatim coverage gap.

### Non-Goals (explicitly out of scope)

- Concurrency safety. `docs/agent-configure-lifecycle.md` §7 already states the
  contract is per-instance, not per-process; two coroutines racing
  `configure()` on one instance is still out of scope.
- Changing `AbstractBot.configure()`'s existing no-op *condition*. This feature
  publishes the decision; it does not redefine it.
- Re-designing `post_configure()` re-entrancy. FEAT-721 settled that (adopt via
  `find_registered_toolkit`); this feature does not revisit it.
- `parrot/clients/base.py` is not touched.
- Any agent under `agents/` at the repo root (gitignored host agents).

---

## 2. Architectural Design

### Overview

`AbstractBot` gains two published signals plus one private helper that both the
signals and `configure()` itself share, so the no-op condition is expressed
exactly once:

1. `_resolve_configure_app(app)` — the app-resolution currently inlined at
   `abstract.py:1600-1602`, extracted verbatim so it can be reused.
2. `configure_skipped` (property) — `True` when the most recent `configure()`
   entry early-returned as an idempotent no-op; `False` once an entry runs the
   pipeline. This is the signal for **post-super** work.
3. `configure_is_noop(app=None)` — `True` when a `configure(app)` call made right
   now would early-return. This is the signal for **pre-super** work, and it is
   deliberately a plain `def`: it must be callable before any `await`.

The two canonical override patterns become:

```python
# post-super work
async def configure(self, app=None) -> None:
    await super().configure(app)
    if self.configure_skipped:
        return
    ...                       # own setup

# pre-super work
async def configure(self, app=None) -> None:
    if self.configure_is_noop(app):
        await super().configure(app)   # keep the counter + INFO log
        return
    ...                       # own setup
    await super().configure(app)
```

Both are correct on all three paths: a repeat call with an unchanged app skips;
an app arriving where none was bound runs; `reconfigure()` (which resets the
counter to 0) runs.

### Component Diagram

```
AbstractBot.configure(app)
        │
        ├─→ _resolve_configure_app(app) ──┐  (shared resolution)
        │                                 │
        ├─→ _configure_count += 1         │
        ├─→ no-op? ───── yes ──→ _configure_skipped = True ──→ return
        │                 no  ──→ _configure_skipped = False ──→ pipeline → post_configure()
        │                                 │
   configure_skipped ◄──────────────┘     └──→ configure_is_noop(app)
        ▲                                                   ▲
        │ read by post-super overrides          read by pre-super overrides
        │ (agent, fireflies, obsidian,          (chatbot, voice, database/agent)
        │  chrome, orchestrator×2, a2a_agent,
        │  computer/agent, document)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.configure` | modifies | sets `_configure_skipped` on both branches; delegates app resolution |
| `AbstractBot.reconfigure` | unchanged | already resets `_configure_count`; the pipeline then sets `_configure_skipped = False` |
| `AbstractBot.__init__` | modifies | initializes `_configure_skipped` beside `_configure_count` (`abstract.py:370`) |
| `BasicAgent.configure` and 8 sibling overrides | modifies | add the post-super guard |
| `Chatbot.configure`, `VoiceBot.configure`, `DatabaseAgent.configure` | modifies | add the pre-super guard |
| `BasicAgent.speech_report` | modifies | explicit error instead of bare `StopIteration` |
| `docs/agent-configure-lifecycle.md` | modifies | §6 rewritten; new §8 for the pre-super shape |

### Data Models

No new Pydantic models. State is two private attributes on `AbstractBot`:
`_configure_count: int` (exists, `abstract.py:370`) and
`_configure_skipped: bool` (new, initialized `False`).

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    @property
    def configure_skipped(self) -> bool:
        """Whether the most recent configure() entry was an idempotent no-op.

        False before the first configure() and after any entry that ran the
        pipeline (including a genuine reconfiguration and reconfigure()).
        Overrides that do work AFTER ``await super().configure(app)`` read this
        and return early when it is True.
        """

    def configure_is_noop(self, app=None) -> bool:
        """Whether configure(app) would early-return as an idempotent no-op.

        Synchronous on purpose: overrides that do work BEFORE
        ``await super().configure(app)`` must consult it first. Resolves ``app``
        exactly as configure() does, so the two can never disagree.
        """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: configure signals on `AbstractBot` | yes | signatures above; `_configure_skipped` set `True` immediately before the `return` at `abstract.py:1609`, `False` immediately after the guard; `_resolve_configure_app` extracted verbatim from `:1600-1602` | — |
| M2: post-super guards | yes | mechanical: insert `if self.configure_skipped:\n    return` directly after the existing `await super().configure(...)` in 9 named files | — |
| M3: pre-super guards | no | each site needs a judgement call on what counts as its "own setup" boundary | per-site boundary is a design decision |
| M4: `speech_report` narrator guard | yes | exact exception type and message fixed below | — |
| M5: `google_tts` verbatim test | yes | mirrors `test_speech_report_verbatim_supertonic_zero_llm_calls` | — |
| M6: docs | yes | §6 replacement text fixed below | — |

### Module 1: Configure signals on `AbstractBot`
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: Publish the base's no-op decision, as a property for
  post-super overrides and a sync predicate for pre-super ones; express the
  no-op condition exactly once.
- **Depends on**: nothing in this spec (root of the graph)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies :370, :1600-1609, :1887)
  class AbstractBot:
      _configure_skipped: bool          # new, init False beside _configure_count (:370)

      def _resolve_configure_app(self, app):
          """Resolve ``app`` to a web.Application or None, as configure() does.

          Extracted verbatim from configure() (:1600-1602) so configure(),
          configure_is_noop() can never diverge.
          """

      @property
      def configure_skipped(self) -> bool:
          """Whether the most recent configure() entry was an idempotent no-op."""

      def configure_is_noop(self, app=None) -> bool:
          """Whether configure(app) would early-return right now."""
  ```
  `configure()` keeps its current behaviour and additionally sets
  `self._configure_skipped = True` on the early-return branch and `False` on the
  branch that runs the pipeline. `reconfigure()` is **not** modified.

### Module 2: Post-super guards
- **Path**: 9 files (see §6 Edit Sites, action MODIFY)
- **Responsibility**: Stop each override's post-super work from running on a
  configure that the base no-opped.
- **Depends on**: Module 1 (`configure_skipped`)
- **Interface Skeleton**:
  ```python
  # e.g. packages/ai-parrot/src/parrot/bots/agent.py  (modifies :188-193)
  async def configure(self, app=None) -> None:
      await super().configure(app)
      if self.configure_skipped:
          return
      ...  # unchanged body
  ```
  Applied identically in `bots/agent.py`, `bots/fireflies_insights.py`,
  `agents/obsidian.py`, `bots/chrome.py`, `bots/document.py`,
  `bots/flows/agents/orchestrator.py`,
  `bots/flows/agents/a2a_orchestrator.py`, `bots/a2a_agent.py`,
  `parrot_tools/computer/agent.py`.

  `bots/a2a_agent.py` is the one site where the override's signature is
  `configure(self)` with no `app` parameter (`a2a_agent.py:16`) — the guard is
  identical, but do not add an `app` parameter while touching it.

### Module 3: Pre-super guards
- **Path**: `packages/ai-parrot/src/parrot/bots/chatbot.py`,
  `packages/ai-parrot/src/parrot/bots/voice.py`,
  `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**: Skip pre-super setup on a call that is about to be a no-op,
  while still entering `super().configure(app)` so the counter and INFO log stay
  truthful.
- **Depends on**: Module 1 (`configure_is_noop`)
- **Interface Skeleton**:
  ```python
  # e.g. packages/ai-parrot/src/parrot/bots/voice.py  (modifies :394-401)
  async def configure(self, app=None) -> None:
      if self.configure_is_noop(app):
          await super().configure(app)
          return
      ...  # unchanged body, including setup_a2a
      await super().configure(app)
  ```
  `bots/data.py` and the two cooperative mixins are deliberately **left
  unguarded** — see §1's "Assessed and deliberately left unguarded" table for
  each one's evidence. Module 6 records them as intentional exemptions so a
  later reader does not "fix" them. This task changes exactly three files.

### Module 4: `speech_report` narrator guard
- **Path**: `packages/ai-parrot/src/parrot/bots/agent.py`
- **Responsibility**: Replace the bare `StopIteration` at `agent.py:765` with an
  explicit, actionable error.
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/agent.py  (modifies :765)
  # in BasicAgent.speech_report, non-gemini/non-script branch, mode != "verbatim":
  if not self.speakers:
      raise ValueError(
          f"{type(self).__name__}.speakers is empty; script mode needs at least "
          "one speaker definition to pick a narrator. Set `speakers` on the "
          "agent class or use speech_mode='verbatim'."
      )
  speaker_data = dict(next(iter(self.speakers.values())))
  ```
  The sibling multi-speaker path (`agent.py:832-838`) already raises on
  `num_speakers < 1` but would build an empty `speakers` list from an empty
  `self.speakers`; it gets the same `not self.speakers` check so both script
  paths fail with the same message instead of one failing silently.

### Module 5: `google_tts` verbatim coverage
- **Path**: `packages/ai-parrot/tests/test_basic_agent_new.py`
- **Responsibility**: Assert that `speech_report()` with `tts_backend="google_tts"`
  in verbatim mode makes **zero** LLM calls, through `speech_report` itself and
  not only the backend unit.
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/test_basic_agent_new.py  (appends after :351 test)
  async def test_speech_report_verbatim_google_tts_zero_llm_calls(mock_agent_deps, tmp_path):
      """verbatim + google_tts routes straight to TTS: no create_conversation_script."""
  ```
  Mirrors `test_speech_report_verbatim_supertonic_zero_llm_calls`
  (`test_basic_agent_new.py:351`), reusing the same `mock_agent_deps` fixture.

### Module 6: Lifecycle documentation
- **Path**: `docs/agent-configure-lifecycle.md`
- **Responsibility**: Replace the incorrect `configure_count > 1` recipe; document
  the pre-super shape and the assessed exemptions.
- **Depends on**: Modules 1-3 (documents their final names)
- **Interface Skeleton**: §6 "Work after `super().configure()`" rewritten around
  `configure_skipped`, with a note on why `configure_count > 1` is wrong (it
  misfires on the CLI-then-server path). A new §8 documents the pre-super
  `configure_is_noop(app)` shape and reproduces §1's "Assessed and deliberately
  left unguarded" table (`bots/data.py`, `mixins/narrative.py`,
  `mixins/infographic_authoring.py`) with each one's reason, so the exemptions
  are discoverable from the docs and not only from this spec. The `configure()`
  docstring at `abstract.py:1587-1588` is corrected by Module 1 to match.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_configure_skipped_false_before_first_configure` | M1 | property is `False` on a fresh instance |
| `test_configure_skipped_false_after_first_configure` | M1 | first configure runs the pipeline |
| `test_configure_skipped_true_on_repeat_same_app` | M1 | repeat call with an unchanged app sets it `True` |
| `test_configure_skipped_false_when_app_arrives_later` | M1 | CLI-then-server path: pipeline ran, so `False` — the case `configure_count > 1` gets wrong |
| `test_configure_skipped_false_after_reconfigure` | M1 | `reconfigure()` resets the counter, so the pipeline runs |
| `test_configure_is_noop_matches_configure_decision` | M1 | predicate agrees with the branch `configure()` actually takes, for all three paths |
| `test_configure_is_noop_is_sync` | M1 | callable without `await` (not a coroutine function) |
| `test_post_super_work_skipped_on_repeat_configure` | M2 | a stub subclass's post-super body runs once across two configures |
| `test_post_super_work_runs_when_app_arrives_later` | M2 | the same body **does** run on a genuine reconfiguration |
| `test_pre_super_work_skipped_on_repeat_configure` | M3 | a stub subclass's pre-super body runs once across two configures |
| `test_voice_setup_a2a_called_once_across_two_configures` | M3 | `setup_a2a` is not re-invoked on the same app |
| `test_chatbot_from_database_not_reloaded_on_repeat_configure` | M3 | no second DB round-trip |
| `test_speech_report_empty_speakers_raises_value_error` | M4 | `ValueError` naming `speakers`, not `StopIteration` |
| `test_speech_report_verbatim_google_tts_zero_llm_calls` | M5 | zero `create_conversation_script` calls |

### Integration Tests

| Test | Description |
|---|---|
| `test_double_configure_registers_no_duplicate_tools` | two `configure()` calls on an orchestrator-shaped bot leave one `ListAvailableA2AAgentsTool` registered and raise no `ToolNameCollisionError` |
| `test_reconfigure_still_reruns_override_work` | `reconfigure()` re-runs both override shapes end to end |

### Validation Contract

tests:
- packages/ai-parrot/tests/bots/test_double_configure.py
- packages/ai-parrot/tests/bots/test_configure_override_guards.py
- packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py
- packages/ai-parrot/tests/bots/test_fireflies_insights.py
- packages/ai-parrot/tests/test_basic_agent_new.py
- packages/ai-parrot/tests/tools/test_toolkit_reregistration.py
- packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py
markers: none

### Test Data / Fixtures

```python
# Reuse, do not re-invent:
#   packages/ai-parrot/tests/bots/test_double_configure.py — _stub_bot / _app helpers (FEAT-721)
#   packages/ai-parrot/tests/test_basic_agent_new.py        — mock_agent_deps fixture
```

New `test_configure_override_guards.py` holds the M1/M2/M3 stub-subclass tests;
the google_tts test is appended to `test_basic_agent_new.py` beside its
supertonic twin.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `AbstractBot.configure_skipped` and `AbstractBot.configure_is_noop(app)`
      exist with the §2 contracts; `configure_is_noop` is a plain `def`.
- [ ] `configure()` sets `_configure_skipped` on **both** branches, and the app
      resolution is expressed once, in `_resolve_configure_app`.
- [ ] All 9 post-super override sites in §6 return early on
      `configure_skipped`; `grep` finds no post-super site left unguarded.
      The owning classes are `BasicAgent`, `FirefliesInsightsAgent`,
      `FirefliesObsidianAgent`, `WebAgent`, `DocumentAgent`,
      `OrchestratorAgent`, `A2AOrchestratorAgent`, `A2AAgent`, `ComputerAgent`.
- [ ] `chatbot.py` (`Chatbot`), `voice.py` (`VoiceBot`) and `database/agent.py`
      (`DatabaseAgent`) consult `configure_is_noop(app)` before their pre-super
      work and still enter `super().configure(app)` on the no-op path.
- [ ] A second `configure()` with an unchanged app registers no duplicate
      toolkit/tool/MCP server/agent and starts no second runtime.
- [ ] The CLI-then-server path (app arriving where none was bound) still runs
      every override's own work — the regression `configure_count > 1` would
      have introduced.
- [ ] `reconfigure()` still re-runs both override shapes.
- [ ] `speech_report` raises `ValueError` naming `speakers` on an empty
      `self.speakers`, in both script paths; no bare `StopIteration` escapes.
- [ ] `test_speech_report_verbatim_google_tts_zero_llm_calls` passes and asserts
      zero LLM calls.
- [ ] `docs/agent-configure-lifecycle.md` no longer prescribes
      `if self.configure_count > 1: return`; it documents `configure_skipped`,
      the pre-super `configure_is_noop` shape, and all three assessed
      exemptions (`bots/data.py`, `mixins/narrative.py`,
      `mixins/infographic_authoring.py`) with their reasons.
- [ ] The override inventory is complete: re-running
      `git grep -n 'async def configure' -- packages/ai-parrot/src packages/ai-parrot-tools/src`
      and filtering to `AbstractBot` descendants yields exactly the 9 guarded
      post-super sites, the 3 guarded pre-super sites, and the 4 recorded
      exemptions — no unclassified site remains.
- [ ] The `configure()` docstring at `abstract.py:1587-1588` matches the docs.
- [ ] Validation Contract tests pass; `ruff check` clean on every touched file.
- [ ] No breaking change: `configure_count` and `reconfigure()` keep their
      current public behaviour.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against base commit `7878c0f1e` (2026-10-22).

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot          # verified: packages/ai-parrot/src/parrot/bots/abstract.py
from parrot.bots.agent import BasicAgent              # verified: packages/ai-parrot/src/parrot/bots/agent.py
from parrot.bots.chatbot import Chatbot               # verified: packages/ai-parrot/src/parrot/bots/chatbot.py
from parrot.tools.manager import ToolManager          # verified: packages/ai-parrot/src/parrot/tools/manager.py
from aiohttp import web                               # verified: used by abstract.py configure()
```

### Existing Class Signatures

MRO chain (verified): `AbstractBot` (`bots/abstract.py:201`) → `BaseBot`
(`bots/base.py:91`, **does not override `configure`**) → `Chatbot`
(`bots/chatbot.py:33`) → `BasicAgent` (`bots/agent.py`) → `Agent`
(`bots/agent.py:1562`, **does not override `configure`**). So both new members
are inherited by every site below.

Owning classes of the override sites: `BasicAgent` (`agent.py`),
`FirefliesInsightsAgent` (`fireflies_insights.py`), `FirefliesObsidianAgent`
(`agents/obsidian.py` — **not** `ObsidianAgent`), `WebAgent` (`chrome.py` —
**not** `ChromeAgent`), `DocumentAgent`, `OrchestratorAgent`,
`A2AOrchestratorAgent`, `A2AAgent`, `ComputerAgent`
(`parrot_tools/computer/agent.py`), `Chatbot`, `VoiceBot` (`voice.py`),
`DatabaseAgent` (`bots/database/agent.py`).

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    self._configure_count: int = 0                            # line 370
    async def configure(self, app=None) -> None:              # no-op guard at 1603-1609
        #   self._configure_count = getattr(self, "_configure_count", 0) + 1     # line 1603
        #   if self._configure_count > 1 and (resolved_app is None
        #           or resolved_app is previous_app):                            # line 1604
        #       self.logger.info(...); return                                    # 1605-1609
    @property
    def is_configured(self) -> bool: ...                      # line 1882
    @property
    def configure_count(self) -> int: ...                     # line 1887
    async def reconfigure(self, app=None) -> None: ...        # line 1891 (sets _configure_count = 0 at 1901)

# packages/ai-parrot/src/parrot/tools/manager.py
    def find_registered_toolkit(...)                          # line 2734

# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent:
    speakers: Dict[str, str] = {...}                          # line 78 — class-level, 2 entries by default
    num_speakers: int = 1                                     # line 71
    async def configure(self, app=None) -> None:              # line 179; super() at 188, own work 189-193
    @staticmethod
    def _to_speakable(text, *, strip_speaker_labels=False)    # line 674
    async def speech_report(self, report, ...)                # line 736
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `configure_skipped` | `AbstractBot.configure` early-return branch | attribute set | `abstract.py:1604-1609` |
| `configure_is_noop` | `_resolve_configure_app` + `_configure_count` | method call | `abstract.py:1600-1603` |
| post-super guards | `configure_skipped` | property read | 8 sites in Edit Sites |
| pre-super guards | `configure_is_noop` | method call | 3 sites in Edit Sites |

### Does NOT Exist (Anti-Hallucination)

Re-verified repo-wide with `git grep` at `7878c0f1e` — all four are introduced by
this feature:

- ~~`AbstractBot.configure_skipped`~~ — zero hits anywhere
- ~~`AbstractBot._configure_skipped`~~ — zero hits anywhere
- ~~`AbstractBot.configure_is_noop`~~ — zero hits; the only `configure_is_noop`
  substring in the repo is the **test name**
  `test_second_configure_is_noop` (`tests/bots/test_double_configure.py:83`)
- ~~`AbstractBot._resolve_configure_app`~~ — zero hits anywhere
- ~~`packages/ai-parrot/tests/bots/test_configure_override_guards.py`~~ — new file
- ~~`AbstractBot.configure()` returning a bool~~ — it returns `None`; do not
  change its return type
- ~~`ObsidianAgent`~~ — the class in `agents/obsidian.py` is
  **`FirefliesObsidianAgent`** (the ledger issue's prose calls it
  `ObsidianAgent`; that name does not exist)
- ~~`ChromeAgent`~~ — the class in `bots/chrome.py` is **`WebAgent`**
- ~~`BaseBot.configure`~~ — `BaseBot` (`bots/base.py:91`) does **not** override
  `configure`; do not add a guard there
- ~~`Agent.configure`~~ — `Agent` (`bots/agent.py:1562`) does **not** override
  `configure`; it inherits `BasicAgent`'s

### Edit Sites (Blueprint Anchors)

Verified against: `7878c0f1e`. Every anchor confirmed unique (`grep -c` = 1).
`/sdd-task` MUST re-run each `grep -c` — these anchors save the search, not the check.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        self._configure_count = getattr(self, "_configure_count", 0) + 1` | `abstract.py:1603` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `    def configure_count(self) -> int:` | `abstract.py:1887` | 1 |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `        await self._wire_tool_namespaces_into_working_memory()` | `agent.py:191` | 1 |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `                speaker_data = dict(next(iter(self.speakers.values())))` | `agent.py:765` | 1 |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | `        """Load configuration for this Chatbot."""` | `chatbot.py:133` | 1 |
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | `        await self._configure_skill_file_registry()` | `fireflies_insights.py:153` | 1 |
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | MODIFY | `        self._initialize_tools([self.obsidian_toolkit])` | `obsidian.py:276` | 1 |
| `packages/ai-parrot/src/parrot/bots/chrome.py` | MODIFY | `        config = self.chrome_config` | `chrome.py:351` | 1 |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | `        url = getattr(self, "url", None)` | `voice.py:398` | 1 |
| `packages/ai-parrot/src/parrot/bots/document.py` | MODIFY | `        self.logger.info(f"DocumentAgent '{self.name}' configured with {len(self.tools)} tools")` | `document.py:253` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` | MODIFY | `        for name in self._pending_agent_names:` | `orchestrator.py:113` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py` | MODIFY | `        self._discovery_tool = ListAvailableA2AAgentsTool(self)` | `a2a_orchestrator.py:275` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | `        await super().configure(app=app)` | `database/agent.py:331` | 1 |
| `packages/ai-parrot/src/parrot/bots/a2a_agent.py` | MODIFY | `        self.setup_a2a(self.app, self.url)` | `a2a_agent.py:19` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` | MODIFY | `        client = getattr(self, "_llm", None)` | `computer/agent.py:135` | 1 |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | `async def test_speech_report_verbatim_supertonic_zero_llm_calls(mock_agent_deps, tmp_path):` | `test_basic_agent_new.py:351` | 1 |
| `packages/ai-parrot/tests/bots/test_configure_override_guards.py` | CREATE | — | — | — |
| `docs/agent-configure-lifecycle.md` | MODIFY | `## 6. Work after \`super().configure()\`` | `agent-configure-lifecycle.md` §6 | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first; `configure_is_noop` is the deliberate exception — a plain `def`,
  because pre-super overrides must call it before their first `await`.
- `self.logger`, never `print`. The existing INFO log on the no-op path stays
  exactly where it is: the pre-super pattern keeps calling
  `super().configure(app)` precisely so that log and the counter still happen.
- Google-style docstrings and full type hints on the new members.
- Minimal diffs: in M2 each file gets two inserted lines and nothing else.
- `ruff check --fix` on every touched file; `black` (line length 120).

### Known Risks / Gotchas

- **The documented recipe is the trap.** `if self.configure_count > 1: return`
  is what the current docs and docstring say, and it is wrong on the
  CLI-then-server path. An implementer who follows the old docs instead of this
  spec will introduce a silent missing-setup bug that no existing test catches —
  which is why `test_configure_skipped_false_when_app_arrives_later` and
  `test_post_super_work_runs_when_app_arrives_later` are acceptance criteria.
- `_configure_skipped` must be read via `getattr(self, "_configure_skipped", False)`
  in the property, matching how `configure_count` tolerates instances built by
  `__new__` + manual attribute assignment — a pattern `bots/chrome.py:363-366`
  documents as already used by existing tests.
- `bots/data.py` overrides `configure` with an **extra** `queries` parameter
  (`data.py:864-868`); do not normalize that signature here.
- `bots/a2a_agent.py` registers its own `configure` as an aiohttp **middleware**
  (`a2a_agent.py:14`), so it is re-entered per request wiring, and its
  `setup_a2a` re-registration is the most likely place a duplicate-route error
  surfaces in production. Its signature is `configure(self)` — no `app`
  parameter. Guard it; do not change the signature.
- Two of the three pre-super sites are large methods
  (`database/agent.py:197-331`); the guard goes at the very top, before the
  first side effect, not merely before `super()`.
- `self.speakers` is a **class-level** dict shared by every instance
  (`agent.py:78`, called out at `agent.py:827-829`). M4 must not mutate it —
  keep copying into `dict(...)`.
- Worktree testing: prefix with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`; the shared
  `.venv` is editable-installed against the main checkout. Never `uv sync`
  inside the worktree.

### External Dependencies

None. No new packages.

---

## 8. Open Questions

- [ ] None. The one design question — how an override learns whether the base
      actually ran, given the no-op condition depends on `resolved_app is
      previous_app` resolved inside the base — is resolved in §2 by publishing
      the decision (`configure_skipped`) rather than having each override
      re-derive it.

---

## 9. Design Research Cross-Check

> Status: skipped (ledger-driven fix lane — `/sdd-fix` routes a verified fix
> group straight to a spec; the three issues are themselves review findings, two
> of them from FEAT-591's adversarial review and one from FEAT-721's).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial draft from `fixgroup:62ef5080d7a8` (issues `81fa838a18c1`, `b032fa211abd`, `b858ae4ad636`) |
