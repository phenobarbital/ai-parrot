# TASK-5587: Parse agy 1.5.8 `step_type: "tool"` steps in GoogleCodingDispatcher

**Feature**: FEAT-888 — agy dispatcher — parse agy 1.5.8 `step_type: "tool"` steps
**Spec**: `sdd/specs/dispatchers-google-coding-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:339fbb135e7f`

---

## Context

agy 1.5.8 reports every tool call as two `step_update` events with `step_type: "tool"`:
first `state: "ACTIVE"`, then `state: "DONE"`, sharing one `step_index`.
`GoogleCodingDispatcher` only knows the older `tool_call` / `tool_response` step types, so an agy seat
never publishes `dispatch.tool_use` / `dispatch.tool_result`, `tool_use_count` stays 0, and no tool row
renders (spec §1). This task adds one shared parser (`parse_agy_tool_step` → `AgyToolStep`) and wires it
into both `_publish_agy_event` (event kind) and `_extract_agy_display` (display keys). It also checks in
two sanitized live captures as fixtures.

---

## Scope

- Add `import re` and the `ConfigDict` and `Field` pydantic imports to `google_coding.py`.
- Add the module-level `_AGY_EXIT_CODE_RE`, `_AGY_COMMAND_OUTPUT_MARKER`, `_AGY_PARAM_ALIASES`, `AgyToolStep`
  and `parse_agy_tool_step` after `_SCHEMA_DIR_GITIGNORE`.
- `_publish_agy_event`: a `st == "tool"` branch maps `ACTIVE` to `dispatch.tool_use` and `DONE` to
  `dispatch.tool_result`. Other states stay `dispatch.message`.
- `_extract_agy_display`: an `elif step_type == "tool":` branch built on the parser, after the `tool_response`
  branch and before the `text_delta` read.
- Fixtures: `packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_tool_steps.jsonl` and
  `agy_1_5_8_denied_command.jsonl`. These are the live captures from 2026-11-13 with the scratch directory
  replaced by `/work/agyprobe`.
- Tests: `TestAgyToolStepParser` and `TestAgyToolStepEvents` in `test_google_coding_dispatcher.py`.

**NOT in scope**: the `init` event drift (separate ledger issue); `result.denied_actions`; deduplicating
repeated `ACTIVE` updates (spec §8 Q1); FEAT-887 M8 `CommandOutcome` / replay; any other dispatcher,
`_shared.py` or `session_state.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | parser + two new branches |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | parser and event tests |
| `packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_tool_steps.jsonl` | CREATE | live capture: echo / failing ls / read_file |
| `packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_denied_command.jsonl` | CREATE | live capture: refused command |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import GoogleCodingDispatcher  # verified: test_google_coding_dispatcher.py:15-23
from parrot.flows.dev_loop.dispatchers._shared import summarize_tool_input  # verified: google_coding.py:36
from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX  # verified: test_google_coding_dispatcher.py:315
from parrot.flows.dev_loop.session_state import SessionHost  # verified: google_coding.py:49
from pydantic import BaseModel, ValidationError  # verified: google_coding.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py
_SCHEMA_DIR_GITIGNORE = ".gitignore"  # line 56
class GoogleCodingDispatcher:  # line 59
    async def _publish_agy_event(self, stream_key: str, event: Dict[str, Any], run_id: str, node_id: str) -> None  # line 477
        # lines 490-496:
        #   elif event_type == "step_update":
        #       su = event.get("step_update", {})
        #       st = su.get("step_type") if isinstance(su, dict) else None
        #       if st == "tool_call": kind = "dispatch.tool_use"
        #       elif st == "tool_response": kind = "dispatch.tool_result"
    @staticmethod
    def _extract_agy_display(event: Dict[str, Any]) -> Dict[str, Any]  # line 509
        # :548 step_type = su.get("step_type"); :549 tool_call; :564 tool_response; :577 text_delta
        # whole body wrapped in try/except Exception → {} (:527, :593)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
def summarize_tool_input(tool_name: str, tool_input: Any, *, max_chars: int = TOOL_INPUT_MAX_CHARS) -> str  # line 205
    # "command"/"cmd" → the command; "file_path"/"path"/"notebook_path" → the path (tail-clamped)
    # :334 summary outcome = "error" if payload.get("is_error") else "ok"

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
# :1174-1175 dispatch tool_use → _with_dispatch(..., tool_use_count=count + 1)

# packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
# fixture `dispatcher` (line 82): GoogleCodingDispatcher with disp._fake_redis = AsyncMock (xadd recorded)
# class TestAgyEventExtraction:  line 356
# TestAgyWireFormat.test_session_host_is_folded (line 312): binds _SESSION_HOST_CTX to SessionHost("run-…")
#   and reads host.state.nodes["development"].dispatch.tool_use_count
```

### Does NOT Exist
- ~~`step_type == "tool_call"` / `"tool_response"` in agy 1.5.8~~ — 1.5.8 emits `step_type: "tool"`.
- ~~a numeric exit-code field on an agy tool step~~ — only the text `Command exited with code N.`.
- ~~`tool_info.output` on a refused command's `DONE` step~~ — absent.
- ~~`import re`, `ConfigDict`, `Field` in `google_coding.py`~~ — added by this task.
- ~~`packages/ai-parrot/tests/flows/dev_loop/fixtures/`~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_tool_steps.jsonl",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_denied_command.jsonl",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._publish_agy_event",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._extract_agy_display",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py#summarize_tool_input"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Telemetry never breaks a dispatch: `parse_agy_tool_step` catches everything and returns `None`; the display
  branch stays inside `_extract_agy_display`'s existing `try`.
- Keep the `tool_call` / `tool_response` branches byte-identical.
- `is_error` / `exit_code` appear only when an exit code was parsed. A refused or non-command tool leaves them
  unset, never `False`.
- `black` line length 120; Google-style docstrings; strict type hints.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:788-790` — the `exit_code` display key.

---

## Implementation Blueprint

### Steps (in order)
1. Write the two fixtures from the live captures, replacing the scratch directory with `/work/agyprobe` —
   *why*: they pin the real 1.5.8 shape the parser is written against.
2. Add the imports, constants, `AgyToolStep` and `parse_agy_tool_step` — *why*: one parser, importable without a
   dispatcher instance, so FEAT-887 M8 reuses it.
3. Add the `st == "tool"` kind branch and the `step_type == "tool"` display branch — *why*: these restore
   `tool_use_count` and the tool rows.
4. Add the tests, then run `black`, `ruff check` and the Validation Command.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` (MODIFY — parser)
```python
# occurrences: 1 (verified: grep -c '^_SCHEMA_DIR_GITIGNORE = ".gitignore"$' google_coding.py)
# INSERT after line 56:

# agy >= 1.5.8 reports each tool call as ``step_update`` events with
# ``step_type: "tool"`` (``ACTIVE`` then ``DONE``, one ``step_index``); a
# ``run_command`` exit code exists only as text inside ``tool_info.output``.
_AGY_EXIT_CODE_RE = re.compile(r"Command exited with code (-?\d+)\.")
_AGY_COMMAND_OUTPUT_MARKER = "Command output:"
# agy parameter keys renamed to the shapes ``summarize_tool_input`` recognises.
_AGY_PARAM_ALIASES: Dict[str, str] = {"CommandLine": "command", "Path": "path"}


class AgyToolStep(BaseModel):
    """One agy ``step_update`` tool step (``step_type: "tool"``, agy >= 1.5.8)."""

    model_config = ConfigDict(frozen=True)

    step_index: Optional[int] = None
    state: str = ""
    name: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[str] = None
    exit_code: Optional[int] = None
    command_output: Optional[str] = None

    # properties: command (parameters["CommandLine"]), done (state == "DONE"),
    # is_error (None if exit_code is None else exit_code != 0)


def parse_agy_tool_step(step_update: Any) -> Optional[AgyToolStep]:
    # FILL IN: None unless a dict with step_type == "tool"; name = tool_info.name or tool_name;
    # parameters = tool_info.parameters if dict else {}; output = str(tool_info.output) when present;
    # exit_code from _AGY_EXIT_CODE_RE.search(output); command_output = text after the marker, .strip();
    # wrap in try/except Exception → None
```

### `google_coding.py` (MODIFY — event kind, after `elif st == "tool_response":` at :495-496)
```python
            elif st == "tool":
                state = su.get("state")
                if state == "ACTIVE":
                    kind = "dispatch.tool_use"
                elif state == "DONE":
                    kind = "dispatch.tool_result"
```

### `google_coding.py` (MODIFY — display, after the `tool_response` branch ending at :576)
```python
                    elif step_type == "tool":
                        step = parse_agy_tool_step(su)
                        # FILL IN: tool_name; tool_input via summarize_tool_input(step.name, aliased params);
                        # on step.done: exit_code + is_error when exit_code is not None;
                        # result_snippet = (command_output if not None else output)[:400] when non-empty
```

### FILL IN checklist
- [ ] Parser body and properties — bounded by spec §2 Overview item 1.
- [ ] Display branch body — bounded by spec §2 Overview item 3.
- [ ] Tests as listed in spec §4 Unit Tests — fixtures loaded through `Path(__file__).parent / "fixtures"`.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` passes from the worktree
      with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] Replaying `agy_1_5_8_tool_steps.jsonl` publishes 3 `dispatch.tool_use` + 3 `dispatch.tool_result`, and a
      bound `SessionHost` ends with `tool_use_count == 3`.
- [ ] `AgyToolStep` / `parse_agy_tool_step` importable from `parrot.flows.dev_loop.dispatchers.google_coding`.
- [ ] Legacy `tool_call` tests (`TestAgyEventExtraction`, `TestAgyWireFormat`) still pass unchanged.
- [ ] `ruff check` and `black --check` pass on the changed Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`

---

## Test Specification

See spec §4 Unit Tests (`TestAgyToolStepParser`, `TestAgyToolStepEvents`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug dispatchers-google-coding-fixes --feature-id FEAT-888`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/dispatchers-google-coding-fixes.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `parrot sdd task close TASK-5587 dispatchers-google-coding-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*
