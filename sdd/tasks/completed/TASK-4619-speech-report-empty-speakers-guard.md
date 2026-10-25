# TASK-4619: `speech_report` raises a clear error on empty `self.speakers`

**Feature**: FEAT-726 — Configure-Override Idempotency & `speech_report` Hardening
**Spec**: `sdd/specs/bots-agent-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4617
**Assigned-to**: unassigned

**Discovered-from**: `issue:b032fa211abd`

---

## Context

Implements spec §3 Module 4, closing `issue:b032fa211abd` — a finding deferred
from FEAT-591's adversarial code review.

`BasicAgent.speech_report` picks the narrator for the non-Gemini script path
with:

```python
speaker_data = dict(next(iter(self.speakers.values())))   # agent.py:765
```

`self.speakers` is a **class-level** dict with two entries by default
(`agent.py:78-81`), so this is safe today. If a subclass ever sets
`self.speakers = {}`, `next(iter(...))` raises a bare `StopIteration` — an
opaque failure with no indication of what the caller did wrong. Inside a
coroutine a leaked `StopIteration` is especially confusing: Python converts it
to a `RuntimeError("coroutine raised StopIteration")`, which names nothing
about speakers at all.

The sibling multi-speaker path has the same latent hole from the other
direction: `definitions = list(self.speakers.values())` (`agent.py:832`) already
raises on `num_speakers < 1` (`:830-831`), but with an empty `self.speakers` it
would silently build an **empty** `speakers` list and hand it to
`ConversationalScriptConfig`. One path would fail opaquely and the other
silently. Both get the same explicit check.

**Depends-on note**: this task depends on TASK-4617 only because both edit
`packages/ai-parrot/src/parrot/bots/agent.py`. There is no logical dependency —
nothing here reads `configure_skipped`.

---

## Scope

- Add an explicit `not self.speakers` check before the narrator pick at
  `agent.py:765`, raising `ValueError` with an actionable message.
- Add the same check before the multi-speaker `definitions` build at
  `agent.py:832`.
- Add `test_speech_report_empty_speakers_raises_value_error` to
  `packages/ai-parrot/tests/test_basic_agent_new.py`.

**NOT in scope**:
- The `google_tts` verbatim coverage test — TASK-4620 (it appends to the same
  test file, hence its dependency on this task).
- Any `configure()` change — TASK-4616/4617/4618.
- Changing the default `speakers` dict (`agent.py:78-81`), the `num_speakers`
  default (`:71`), or the `num_speakers < 1` check already at `:830-831`.
- Refactoring `speech_report`'s routing or the verbatim path.
- Mutating `self.speakers`. It is class-level and shared by every instance —
  `agent.py:827-829` says so explicitly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | empty-`speakers` guard in both script paths of `speech_report` |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | add the empty-speakers test |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `36b9847aa`. Every anchor re-confirmed `grep -c` = 1.

### Verified Imports

No new imports in `agent.py` — `ValueError` is a builtin and the module already
raises it at `agent.py:831`.

```python
import pytest                                       # verified: packages/ai-parrot/tests/test_basic_agent_new.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):
    num_speakers: int = 1                                    # line 71
    speech_backend: SpeechBackend = "gemini"                 # line 72
    speech_mode: SpeechMode = "script"                       # line 73
    speech_voice: Optional[str] = None                       # line 74
    speakers: Dict[str, str] = {                             # line 78 — CLASS-LEVEL, 2 entries
        "interviewer": {"name": "Lydia", "role": "interviewer", "characteristic": "Bright", "gender": "female"},
        "interviewee": {"name": "Brian", "role": "interviewee", "characteristic": "Informative", "gender": "male"},
    }                                                        # line 81

    @staticmethod
    def _to_speakable(text, *, strip_speaker_labels: bool = False) -> str:   # line 674

    async def speech_report(                                 # line 736
        self,
        report: str,
        max_lines: int = 15,
        num_speakers: int = 2,
        podcast_instructions: Optional[str] = "for_podcast.txt",
        directory: Optional[Path] = None,
        output_directory: Optional[Path] = None,
        script_model: Optional[str] = None,
        tts_model: Optional[str] = None,
        tts_backend: Optional[SpeechBackend] = None,
        speech_mode: Optional[SpeechMode] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        # routing: backend, mode = self._resolve_speech_route(tts_backend, speech_mode)   # :751
        # non-gemini/non-script branch:
        #     if mode == "verbatim":                                  # :762
        #         speakable_text = self._to_speakable(report)         # :763
        #     else:
        #         speaker_data = dict(next(iter(self.speakers.values())))   # :765  <-- site 1
        #         speaker_data["gender"] = speaker_data.get("gender", "neutral").lower()
        #         narrator = FictionalSpeaker(**speaker_data)
        # gemini/script branch:
        #     if num_speakers < 1:                                    # :830
        #         raise ValueError(f"num_speakers must be >= 1 (got {num_speakers}).")   # :831
        #     definitions = list(self.speakers.values())              # :832  <-- site 2
```

### Does NOT Exist

- ~~a `speakers` validation helper on `BasicAgent`~~ — there is none; the only
  related check is the `num_speakers < 1` guard at `agent.py:830-831`.
- ~~`self.speakers` as an instance attribute set in `__init__`~~ — it is
  **class-level** (`agent.py:78`). Never mutate it in place; `agent.py:827-829`
  documents that constraint.
- ~~`BasicAgent.speakers` being a `list`~~ — it is a `Dict[str, dict]`; the
  values are the speaker definition dicts.
- ~~catching `StopIteration` as the fix~~ — do NOT wrap the `next()` in
  `try/except StopIteration`. The issue asks for a clear error *before* the
  call; a caught `StopIteration` inside a coroutine is exactly the confusing
  path being removed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_basic_agent_new.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.speech_report",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent._to_speakable"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Mirror the error style already in this method — a plain `ValueError` with an
f-string naming the offending value, as at `agent.py:831`:

```python
# packages/ai-parrot/src/parrot/bots/agent.py:830-831 — the shape to mirror
if num_speakers < 1:
    raise ValueError(f"num_speakers must be >= 1 (got {num_speakers}).")
```

And the test mirrors the existing sibling for that very guard — read it first,
it is the template for this task's test:

```python
# packages/ai-parrot/tests/test_basic_agent_new.py:340-347 (verified)
@pytest.mark.asyncio
async def test_speech_report_rejects_zero_speakers(mock_agent_deps):
    """num_speakers < 1 is a caller error, not a silent empty podcast."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    with pytest.raises(ValueError, match="num_speakers"):
        await agent.speech_report(report="Analysis Text", num_speakers=0)
```

A subclass carrying its own `speakers` is also an established pattern in this
file — see the `Shouty` subclass used by the test above
`test_speech_report_rejects_zero_speakers` (it asserts
`Shouty.speakers["host"]["gender"]`). Follow it rather than touching
`BasicAgent.speakers`.

### Key Constraints

- `ValueError`, not a custom exception class — matches `:831` and keeps the
  change to two guards.
- The message must name the attribute (`speakers`) and the way out
  (`speech_mode='verbatim'` or setting `speakers` on the class). An error that
  only says "empty" repeats the original problem.
- Use `type(self).__name__` in the message, not a hardcoded `BasicAgent` — the
  real failing class will almost always be a subclass.
- The verbatim path (`mode == "verbatim"`, `:762-763`) must stay reachable with
  an empty `speakers` dict: it never touches `self.speakers`. Do NOT hoist the
  guard above the `if mode == "verbatim":` test — that would break the one
  working configuration for an agent with no speakers, and TASK-4620's test
  asserts the verbatim path works.
- Do not mutate `self.speakers`; keep the `dict(...)` copy at `:765`.
- `ruff check --fix`; 120-column lines.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/agent.py:762-770` — site 1 and its verbatim sibling
- `packages/ai-parrot/src/parrot/bots/agent.py:826-838` — site 2 and the existing `num_speakers` guard
- `packages/ai-parrot/tests/test_basic_agent_new.py:351` —
  `test_speech_report_verbatim_supertonic_zero_llm_calls`, the fixture pattern to reuse

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4617 is `done` — *why*: it edits the same file
   (`agent.py`); running concurrently conflicts.
2. Read `agent.py:736-850` — *why*: `speech_report` has two script paths and one
   verbatim path, and the guard must land in the two script paths only.
3. Add the site-1 guard above `:765` — *why*: that `next(iter(...))` is the bare
   `StopIteration` the issue reports.
4. Add the site-2 guard above `:832` — *why*: the same empty dict silently
   produces an empty speaker list there; fixing one path and not the other
   leaves half the bug.
5. Add the test — *why*: it is what distinguishes "raises `ValueError`" from
   "still raises `RuntimeError: coroutine raised StopIteration`".

### `packages/ai-parrot/src/parrot/bots/agent.py` (MODIFY — site 1, narrator pick)

```python
# occurrences: 1 (verified: grep -c '                speaker_data = dict(next(iter(self.speakers.values())))' packages/ai-parrot/src/parrot/bots/agent.py)
# BEFORE — insert above `                speaker_data = dict(next(iter(self.speakers.values())))` (verified: agent.py:765)
# NOTE the indentation: this site is inside `else:` inside `if backend != "gemini" or mode != "script":`,
# so the guard is indented 16 spaces to match the anchor.
                if not self.speakers:
                    raise ValueError(
                        f"{type(self).__name__}.speakers is empty; script mode needs at least "
                        "one speaker definition to pick a narrator. Set `speakers` on the "
                        "agent class or use speech_mode='verbatim'."
                    )
```

**Why**: this is the exact line `issue:b032fa211abd` names. The check sits inside
the `else:` of `if mode == "verbatim":`, so the verbatim path — which never
reads `self.speakers` — is unaffected and still works for an agent with no
speakers. Match the anchor's 16-space indentation exactly; a mis-indented guard
either lands in the verbatim branch or breaks the block.

### `packages/ai-parrot/src/parrot/bots/agent.py` (MODIFY — site 2, multi-speaker build)

```python
# occurrences: 1 (verified: grep -c '        definitions = list(self.speakers.values())' packages/ai-parrot/src/parrot/bots/agent.py)
# BEFORE — insert above `        definitions = list(self.speakers.values())` (verified: agent.py:832),
# i.e. directly below the existing `num_speakers < 1` raise at :830-831.
# Indentation here is 8 spaces.
        if not self.speakers:
            raise ValueError(
                f"{type(self).__name__}.speakers is empty; script mode needs at least "
                "one speaker definition. Set `speakers` on the agent class or use "
                "speech_mode='verbatim'."
            )
```

**Why**: placed immediately after the existing `num_speakers` validation, the two
input checks read as one block. Without it an empty `self.speakers` yields
`speakers == []`, which reaches `ConversationalScriptConfig` and fails later and
further from the cause.

### `packages/ai-parrot/tests/test_basic_agent_new.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_speech_report_verbatim_supertonic_zero_llm_calls(mock_agent_deps, tmp_path):' packages/ai-parrot/tests/test_basic_agent_new.py)
# APPEND after the existing test that starts at test_basic_agent_new.py:351
# (place it after that test's body ends, not inside it).


@pytest.mark.asyncio
async def test_speech_report_empty_speakers_raises_value_error(mock_agent_deps, tmp_path):
    """Empty speakers in script mode raises a ValueError naming `speakers`.

    Regression for issue:b032fa211abd — it used to leak a bare StopIteration,
    which a coroutine surfaces as `RuntimeError: coroutine raised StopIteration`
    and which names nothing about speakers.
    """
    # FILL IN: build the agent the way test_speech_report_verbatim_supertonic_zero_llm_calls
    # does (same mock_agent_deps fixture), set its class `speakers` to {} on a
    # subclass (never mutate BasicAgent.speakers — it is class-level and shared),
    # select a NON-verbatim script route, and assert:
    #     with pytest.raises(ValueError, match="speakers"):
    #         await agent.speech_report(...)
    # Cover BOTH script paths: the non-gemini narrator pick (agent.py:765) and the
    # gemini/script multi-speaker build (agent.py:832) — parametrize or write two
    # asserts. Assert no StopIteration/RuntimeError escapes.
    # — bounded by AC "speech_report raises ValueError naming `speakers` ... in both
    #   script paths; no bare StopIteration escapes"
```

**Why**: `pytest.raises(ValueError, match="speakers")` is what makes the test
fail before the fix and pass after it — matching on the attribute name, not on
the full sentence, so a later wording tweak does not break the test. Setting
`speakers = {}` on a **subclass** is load-bearing: assigning to
`BasicAgent.speakers` would leak an empty dict into every other test in the
session.

### FILL IN checklist

- [ ] `test_basic_agent_new.py::test_speech_report_empty_speakers_raises_value_error` — agent construction via `mock_agent_deps`, a subclass with `speakers = {}`, and both script paths asserted; bounded by AC "ValueError naming `speakers` in both script paths"

---

## Acceptance Criteria

- [ ] `speech_report` raises `ValueError` whose message contains `speakers` when
      `self.speakers` is empty, in **both** script paths (`agent.py:765` and
      `agent.py:832`).
- [ ] The message names the class via `type(self).__name__` and states the way
      out (set `speakers`, or use `speech_mode='verbatim'`).
- [ ] No bare `StopIteration` (and no
      `RuntimeError: coroutine raised StopIteration`) can escape
      `speech_report` for an empty `speakers`.
- [ ] The **verbatim** path still works with an empty `speakers` dict — the
      guard is not hoisted above the `if mode == "verbatim":` test.
- [ ] `self.speakers` is not mutated; the `dict(...)` copy at `:765` is kept.
- [ ] The existing `num_speakers < 1` check at `:830-831` is unchanged.
- [ ] `test_speech_report_empty_speakers_raises_value_error` passes, and
      `test_speech_report_verbatim_supertonic_zero_llm_calls` still passes.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_basic_agent_new.py -q`
- `pytest packages/ai-parrot/tests/test_basic_agent_new.py::test_speech_report_empty_speakers_raises_value_error -q`

---

## Test Specification

See the Implementation Blueprint's MODIFY block for
`test_basic_agent_new.py`. Run inside the worktree with
`PYTHONPATH=packages/ai-parrot/src`. Keep it offline — the test must make no
real LLM or TTS call.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug bots-agent-tech-debt --feature-id FEAT-726`)
2. **Read the spec** at `sdd/specs/bots-agent-tech-debt.spec.md` (§3 Module 4)
3. **Check dependencies** — TASK-4617 must be `"done"` in
   `sdd/tasks/index/bots-agent-tech-debt.json` (same file: `agent.py`)
4. **Verify the Codebase Contract** — re-run both `grep -c` calls; `agent.py` is
   a long file that TASK-4617 has just edited, so line numbers will have shifted
   by a couple of lines even though the anchors are stable
5. **Update status** in `sdd/tasks/index/bots-agent-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4619 bots-agent-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Both script paths guarded. Site 1 (the narrator pick, `next(iter(...))`) and
site 2 (the multi-speaker `definitions` build) now raise `ValueError` naming
`speakers` and `type(self).__name__`, and pointing at the two ways out: set
`speakers` on the class, or use `speech_mode='verbatim'`.

Site 2 was not in the original ledger issue, which named only the
`StopIteration` line. It is included because the same empty dict there built an
**empty** `speakers` list and handed it to `ConversationalScriptConfig`, failing
later and further from the cause — one path failing opaquely and the other
silently is not half a bug fixed.

The guards sit INSIDE the non-verbatim branch, not above the
`if mode == "verbatim"` test: verbatim never reads `self.speakers` and is the
one working configuration for a speakerless agent.
`test_speech_report_verbatim_works_with_empty_speakers` pins that, so a later
"simplification" that hoists the guard fails.

Tests use a `Speechless(BasicAgent)` subclass with `speakers = {}` — never
assignment to `BasicAgent.speakers`, which is class-level and shared by every
instance in the session (`agent.py:78`, called out at `:827-829`). They follow
the existing `test_speech_report_rejects_zero_speakers` shape. Appended at the
end of the file rather than spliced after the supertonic test; same suite,
no structural risk.

Validation: `pytest tests/test_basic_agent_new.py -q` -> **27 passed** (3 new).
`ruff check` clean on both files.
