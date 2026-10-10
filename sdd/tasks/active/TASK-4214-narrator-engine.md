# TASK-4214: Narrator: sandboxed Jinja2 rendering, locale fallback, question/review plans, author prompt whitelist

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4213, TASK-4211
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3 — Narration** (the engine half; TASK-4213 ships the
lexicon and the per-locale `narration.yaml` files). Every spoken turn of the audio
form runtime is produced deterministically from YAML templates rendered in a
Jinja2 **sandbox** (G4) — the LLM never writes narration (§7 "Narration never from
the LLM"). Author-supplied `meta["voice"]["prompt"]` strings are rendered with
`str.format_map` over a whitelist, never Jinja (template-injection guard). The
`Narrator` is consumed by the engine (TASK-4225/4226), the audio renderer
(TASK-4232, `render_author_prompt`) and the design-time optimiser (TASK-4234).

---

## Scope

- Create `audio/narration/engine.py` with `NARRATION_KEYS`, `Narrator`
  (`__init__`, `render`, `plan_question`, `plan_review`, `system_phrases`) and
  `render_author_prompt`.
- Load `<locale>/narration.yaml` (key `templates:`) with fallback chain
  `es-MX → es → en`; a key missing in the resolved locale falls back to `en`.
- Use `jinja2.sandbox.ImmutableSandboxedEnvironment(undefined=StrictUndefined,
  autoescape=False)`.
- `plan_question` builds a `NarrationPlan` for one `AudioQuestion`: label →
  `pause:<ms>` → hint bridge + hint (or `description` when `hint` is absent — AC4) →
  options intro + one item per option / count-only, honouring
  `FieldVoiceMeta.enumerate` and `VoiceFormConfig.enumerate_options`. Audio keys
  are `q:<field_uid>:label`, `q:<field_uid>:hint`, `q:<field_uid>:options`, plus
  the pause marker `pause:<ms>` (not synthesised).
- `plan_review` builds the review narration (`review_intro`, `review_item` /
  `review_item_skipped` per item with its position; sensitive items read `[hidden]`).
- `system_phrases()` returns `sys:<key>` → text for the fixed system phrases
  pre-synthesised at `start_session` (command acks, `no_match`, `required_reject`,
  `review_all_correct`, `submitted`, `resume_welcome`, …).
- Extend `audio/narration/__init__.py` exports with `Narrator`, `NARRATION_KEYS`,
  `render_author_prompt`.
- Write `test_narration_engine.py` (conformance, fallback, StrictUndefined,
  author prompt not Jinja, question/review plans).

**NOT in scope**: the YAML files and the lexicon (TASK-4213); matching (TASK-4215);
building `AudioQuestion.prompt` inside the renderer (TASK-4232); synthesis (TASK-4218).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` | CREATE | `Narrator`, `NARRATION_KEYS`, `render_author_prompt` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/__init__.py` | MODIFY | export the engine symbols |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from jinja2 import StrictUndefined                                   # jinja2>=3.1 (pyproject.toml:41)
from jinja2.sandbox import ImmutableSandboxedEnvironment            # jinja2>=3.1
import yaml                                                         # PyYAML>=6.0 (pyproject.toml:40)
from parrot_formdesigner.core.types import FieldType                # core/types.py:16
```

#### Provided by dependency tasks (do not exist yet — land before this task)
```python
# TASK-4213 — audio/narration/lexicon.py + templates/{en,es}/narration.yaml (top-level keys `templates:` and `lexicon:`)
from parrot_formdesigner.audio.narration.lexicon import Lexicon, load_lexicon, normalize
# TASK-4211 — audio/models.py deltas (Phase/ReviewItemData live here per plan decision)
from parrot_formdesigner.audio.models import AudioQuestion, NarrationPlan, ReviewItemData
#   NarrationPlan(text: str, audio_keys: list[str], segments: dict[str, str])
#   ReviewItemData(position: int, field_id: str, label: str, answer_text: str, skipped=False, flagged=False, sensitive=False)
#   AudioQuestion += hint: str|None, prompt: str|None, voice_meta: FieldVoiceMeta, section_title, ...
# TASK-4209 — core/voice.py
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig
#   FieldVoiceMeta.enumerate: Literal["auto","always","never","count_only"]; .pause_ms: int|None; .prompt: str|None
#   VoiceFormConfig.hint_pause_ms: int = 600; .enumerate_options: bool = True
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py:72 (current, before TASK-4211 deltas)
class AudioQuestion(BaseModel):
    field_id: str; field_uid: uuid.UUID; field_type: str; label: str
    description: Optional[str] = None; required: bool = False
    options: Optional[list[dict]] = None   # entries {"value", "label"} (+ "disabled" after TASK-4232)
    sensitive: bool = False
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py:218
def _resolve(value: LocalizedString | None, locale: str = "en") -> str   # NOT needed: AudioQuestion carries resolved strings
```

### Does NOT Exist
- ~~`audio/narration/engine.py`~~, ~~`Narrator`~~, ~~`NARRATION_KEYS`~~, ~~`render_author_prompt`~~ — created here.
- ~~`jinja2.Environment` for narration~~ — must be the immutable sandbox, never a plain `Environment`.
- ~~`Narrator.render_question()`~~ / ~~`Narrator.speak()`~~ — the API is `render` / `plan_question` / `plan_review` / `system_phrases` only.
- ~~SSML output~~ — SuperTonic has no SSML (spec Non-Goals); pauses are `pause:<ms>` keys the client honours.
- ~~`ReviewItemData` in `audio/narration`~~ — it lives in `audio/models.py` (TASK-4211).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioQuestion"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure and synchronous — no I/O after `__init__` (YAML is read once in the constructor). The engine (TASK-4225) calls the narrator from inside `handle()`, which never awaits.
- `render()` raises `KeyError` for a key not in `NARRATION_KEYS` **or** absent from every locale in the chain; the conformance test guards every locale.
- `StrictUndefined`: a template referencing a missing variable raises `jinja2.UndefinedError` — do not swallow it.
- Locale chain: `"es-MX"` → `["es-MX", "es", "en"]`; `"en"` → `["en"]`. Merge templates so a key missing in `es` resolves from `en`.
- Sensitive questions: `plan_review` renders `answer_text="[hidden]"` for `item.sensitive` (S8, AC15) — never the real value.
- `self.logger = logging.getLogger(__name__)`; Google-style docstrings; no `print`.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/templates/*.j2` + renderers using Jinja2 — existing Jinja2 usage in the package.
- `api/audio_ws.py:1333` `_narration_text` — today's narration (label + "Options: …"), the behaviour being replaced.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-4213's YAML shape (`templates:` mapping of every `NARRATION_KEYS` key) and TASK-4211's `NarrationPlan`/`ReviewItemData` — *why*: the blueprint assumes those exact names.
2. Write `engine.py` from the block below — *why*: the signatures are fixed by spec §3 M3.
3. Fill the `plan_question` / `plan_review` branches — *why*: they encode AC4/AC15 behaviour.
4. Append the exports to `narration/__init__.py` — *why*: TASK-4225/4232/4234 import from the package.
5. Write the tests and run the Validation Commands.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` (CREATE)
```python
"""Deterministic narration for audio forms (FEAT-649, Module 3)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from ...core.types import FieldType
from ...core.voice import FieldVoiceMeta, VoiceFormConfig
from ..models import AudioQuestion, NarrationPlan, ReviewItemData

_TEMPLATES_DIR = Path(__file__).parent / "templates"

NARRATION_KEYS: frozenset[str] = frozenset({
    "question", "question_with_prompt", "hint_bridge", "options_intro", "option_item", "options_count_only",
    "boolean_prompt", "required_mark", "confirm_readback", "confirm_option", "no_match", "required_reject", "skipped",
    "section_intro", "computed_statement", "review_intro", "review_item", "review_item_skipped", "review_all_correct",
    "review_edit_ack", "plausibility_flag", "plausibility_keep", "submitted", "resume_welcome", "command_ack_repeat",
    "command_ack_back", "command_ack_skip", "command_ack_help", "command_ack_stop", "command_ack_next",
    "command_ack_send", "command_ack_change",
})
# Keys pre-synthesised at start_session as ``sys:<key>`` (no per-question variables).
_SYSTEM_KEYS: tuple[str, ...] = (
    "no_match", "required_reject", "skipped", "review_all_correct", "submitted", "resume_welcome",
    "command_ack_repeat", "command_ack_back", "command_ack_skip", "command_ack_help", "command_ack_stop",
    "command_ack_next", "command_ack_send", "command_ack_change",
)
_PROMPT_WHITELIST = ("label", "hint", "section", "n", "total")


def locale_chain(locale: str) -> list[str]:
    """Return the fallback chain for ``locale`` (``es-MX`` → ``es`` → ``en``)."""
    chain = [locale]
    base = locale.split("-")[0]
    if base != locale:
        chain.append(base)
    if "en" not in chain:
        chain.append("en")
    return chain


class _VerbatimDict(dict):
    """format_map mapping that leaves unknown placeholders verbatim."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_author_prompt(prompt: str, *, label: str, hint: str, section: str, n: int, total: int) -> str:
    """Render an author prompt with ``str.format_map`` over a whitelist (never Jinja).

    Unknown placeholders are rendered verbatim; malformed format strings return the prompt unchanged.
    """
    values = _VerbatimDict(label=label, hint=hint, section=section, n=n, total=total)
    try:
        return prompt.format_map(values)
    except (ValueError, IndexError, AttributeError):
        # FILL IN: confirm `{0}` / `{label.x}` / unbalanced braces all fall back to the raw prompt — bounded by test_author_prompt_is_not_jinja
        return prompt
```
**Why this shape**: module-level constants and the whitelist renderer are fixed by spec §3 M3; `_VerbatimDict` implements "unknown placeholders rendered verbatim". `{{ 7*7 }}` under `format_map` becomes `{ 7*7 }` — the test must assert it is NOT `49` (no evaluation); FILL IN decides whether doubled braces stay literal.

### `audio/narration/engine.py` (CREATE, continued — `Narrator`)
```python
class Narrator:
    """Render narration templates for one locale (sandboxed Jinja2, StrictUndefined)."""

    def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None:
        """Load ``<locale>/narration.yaml`` with fallback ``es-MX → es → en``."""
        self.logger = logging.getLogger(__name__)
        self.locale = locale
        self._dir = templates_dir or _TEMPLATES_DIR
        self._env = ImmutableSandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        self._templates: dict[str, str] = {}
        for loc in reversed(locale_chain(locale)):          # en first, most specific last wins
            path = self._dir / loc / "narration.yaml"
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self._templates.update(data.get("templates") or {})
        missing = NARRATION_KEYS - self._templates.keys()
        if missing:
            self.logger.warning("Narrator(%s): missing template keys %s", locale, sorted(missing))

    def render(self, key: str, **ctx: Any) -> str:
        """Render one template key; raises KeyError for an unknown key."""
        if key not in NARRATION_KEYS or key not in self._templates:
            raise KeyError(key)
        return self._env.from_string(self._templates[key]).render(**ctx).strip()

    def system_phrases(self) -> dict[str, str]:
        """``sys:*`` keys pre-synthesised at start_session."""
        return {f"sys:{k}": self.render(k) for k in _SYSTEM_KEYS}

    def plan_question(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> NarrationPlan:
        """label → ``pause:<ms>`` → hint_bridge + hint (or description) → options; keys ``q:<uid>:label|hint|options``."""
        uid = str(q.field_uid)
        segments: dict[str, str] = {}
        keys: list[str] = []
        label_text = q.prompt or self.render("question", label=q.label, required=q.required)
        segments[f"q:{uid}:label"] = label_text
        keys.append(f"q:{uid}:label")
        help_text = q.hint or q.description          # AC4: description narrated when hint is absent
        if help_text:
            pause = meta.pause_ms if meta.pause_ms is not None else cfg.hint_pause_ms
            keys.append(f"pause:{pause}")
            segments[f"q:{uid}:hint"] = self.render("hint_bridge", hint=help_text)
            keys.append(f"q:{uid}:hint")
        # FILL IN: options narration — enumerate rule: meta.enumerate "never" → none; "count_only" → options_count_only(count=N);
        #   "always" → options_intro + option_item(n, label) per non-disabled option; "auto" → enumerate only when
        #   cfg.enumerate_options and field_type in SELECT/MULTI_SELECT/DYNAMIC_SELECT family; BOOLEAN → boolean_prompt.
        #   Join into ONE segment `q:<uid>:options` — bounded by spec §3 M3 plan_question docstring, AC6
        text = " ".join(segments[k] for k in keys if not k.startswith("pause:"))
        return NarrationPlan(text=text, audio_keys=keys, segments=segments)

    def plan_review(self, items: list[ReviewItemData], cfg: VoiceFormConfig) -> NarrationPlan:
        """review_intro + one review_item / review_item_skipped per item (sensitive → "[hidden]")."""
        segments: dict[str, str] = {"review:intro": self.render("review_intro", total=len(items))}
        keys = ["review:intro"]
        for item in items:
            # FILL IN: pick review_item vs review_item_skipped; answer = "[hidden]" when item.sensitive;
            #   key f"review:{item.position}"; pass position/label/answer (+ flagged) — bounded by AC15, S8
            pass
        text = " ".join(segments[k] for k in keys)
        return NarrationPlan(text=text, audio_keys=keys, segments=segments)
```
**Why this shape**: the sandbox + StrictUndefined pairing and the key naming are fixed by spec §3 M3/§7; `cfg` is accepted by `plan_review` for future review options (keep the parameter). Do not cache the rendered `Template` per key unless profiling demands it — the forms are short.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/__init__.py` (MODIFY)
```python
# occurrences: FILL IN — re-run `grep -c '<last import line>' audio/narration/__init__.py` after TASK-4213 lands (file does not exist yet)
# AFTER — append below TASK-4213's lexicon import
from .engine import NARRATION_KEYS, Narrator, locale_chain, render_author_prompt
# FILL IN: extend __all__ (if TASK-4213 declared one) with "NARRATION_KEYS", "Narrator", "locale_chain", "render_author_prompt"
```
**Why**: consumers import `from parrot_formdesigner.audio.narration import Narrator`. The anchor cannot be verified today because TASK-4213 creates the file; verify its count before editing.

### FILL IN checklist
- [ ] `render_author_prompt` — malformed-format fallback and literal braces; bounded by `test_author_prompt_is_not_jinja`
- [ ] `Narrator.plan_question` — options narration per enumerate rule; bounded by spec §3 M3, AC6
- [ ] `Narrator.plan_review` — item/skipped selection, `[hidden]` masking; bounded by AC15, S8
- [ ] `narration/__init__.py` — verify anchor count, extend `__all__`

---

## Acceptance Criteria

- [ ] Every `NARRATION_KEYS` key renders in `en` and `es` (conformance test).
- [ ] `Narrator("es-MX")` resolves `es` templates and falls back to `en` for absent keys.
- [ ] A template referencing an undefined variable raises `jinja2.UndefinedError`.
- [ ] `render_author_prompt("{{ 7*7 }} {label}", …)` never evaluates `7*7`; whitelisted placeholders are substituted, unknown ones verbatim.
- [ ] `plan_question` emits `pause:<hint_pause_ms>` before the hint and narrates `description` when `hint` is absent (AC4).
- [ ] `plan_review` reads sensitive items as `[hidden]` (AC15).
- [ ] `ruff check` passes on both source files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py
import uuid

import pytest
from jinja2 import UndefinedError

from parrot_formdesigner.audio.models import AudioQuestion, ReviewItemData
from parrot_formdesigner.audio.narration import NARRATION_KEYS, Narrator, render_author_prompt
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig


@pytest.mark.parametrize("locale", ["en", "es"])
def test_narration_conformance_all_locales(locale):
    n = Narrator(locale)
    for key in NARRATION_KEYS:
        assert key in n._templates, key   # FILL IN: render each key with a full sample ctx


def test_fallback_es_mx_to_es_to_en(tmp_path): ...          # FILL IN: tmp templates dir with en+es only
def test_strict_undefined_raises(tmp_path): ...              # FILL IN: template "{{ missing }}" → UndefinedError
def test_author_prompt_is_not_jinja():
    out = render_author_prompt("{{ 7*7 }} {label} {unknown}", label="Name", hint="", section="", n=1, total=4)
    assert "49" not in out and "Name" in out and "{unknown}" in out
def test_plan_question_hint_pause_and_description_fallback(): ...   # FILL IN
def test_plan_review_hides_sensitive(): ...                          # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`).
2. **Read the spec** (§3 Module 3, §7) for full context.
3. **Check dependencies** — TASK-4213 and TASK-4211 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — especially the "Provided by dependency tasks" names as actually landed.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4214 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
