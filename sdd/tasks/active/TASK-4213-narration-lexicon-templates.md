# TASK-4213: Narration lexicon + en/es narration.yaml templates + package-data

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (data half) and G4: deterministic per-locale narration templates and lexicons
(`en`, `es` in v1) for option matching, yes/no, ordinals, review confirmation and hands-free commands.
Narration is **never** produced by an LLM. This task ships the data files, the `Lexicon` model, its
loader with locale fallback and the `normalize()` pipeline; the `Narrator` that renders the templates
is TASK-4214. The option matcher (TASK-4215) and command classifier (TASK-4216) consume `Lexicon` and
`normalize()`.

Binding plan decision: the lexicon lives in the **same** per-locale `narration.yaml`, under a top-level
`lexicon:` key; the templates live under `templates:`.

This task is **exclusive** (`parallel: false`): it edits `packages/parrot-formdesigner/pyproject.toml`
(package-data), a shared packaging manifest.

---

## Scope

- Create `audio/narration/__init__.py` (exports the lexicon API; TASK-4214 adds `Narrator`).
- Create `audio/narration/lexicon.py`: `Lexicon`, `load_lexicon()`, `normalize()`, `load_locale_document()`, `TEMPLATES_DIR`.
- Create `templates/en/narration.yaml` and `templates/es/narration.yaml` with every narration key and a full lexicon.
- Add the YAML files to setuptools package-data.
- Write lexicon tests (loading, fallback `es-MX → es → en`, normalisation, en/es key parity).

**NOT in scope**: `Narrator`, `NARRATION_KEYS` constant, Jinja2 rendering, `render_author_prompt` (TASK-4214);
option matching (TASK-4215); command classification (TASK-4216); `pt`/`fr` lexicons (follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/__init__.py` | CREATE | Package; exports lexicon API |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py` | CREATE | `Lexicon`, loader, `normalize` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/en/narration.yaml` | CREATE | English templates + lexicon |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/es/narration.yaml` | CREATE | Spanish templates + lexicon |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | package-data for the YAML files |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml                                   # PyYAML>=6.0 is a hard dependency (verified: packages/parrot-formdesigner/pyproject.toml:40); used lazily at extractors/yaml.py:36
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```toml
# packages/parrot-formdesigner/pyproject.toml
[tool.setuptools.packages.find]                                   # line 85-87: where=["src"], include=["parrot_formdesigner*"]
[tool.setuptools.package-data]                                    # line 89
"parrot_formdesigner" = ["py.typed"]                              # line 90
"parrot_formdesigner.renderers" = ["templates/*.j2"]              # line 91 <- anchor (NOT the spec's `"jinja2>=3.1",` line)
```
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/ — current contents: __init__.py, models.py only
```

### Does NOT Exist
- ~~`audio/narration/`~~ — created here (and extended by TASK-4214).
- ~~`Narrator`~~, ~~`NARRATION_KEYS`~~, ~~`render_author_prompt`~~ — TASK-4214, not here.
- ~~`rapidfuzz`~~ — not a dependency; never import it here.
- ~~`fakeredis`~~ — irrelevant here; do not add test deps.
- ~~`parrot_formdesigner.audio.narration.templates` as a Python package~~ — templates are data dirs (no `__init__.py`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/__init__.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/en/narration.yaml", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/es/narration.yaml", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Template variables (binding — TASK-4214 renders with exactly these names)
| Key | Variables |
|---|---|
| `question` | `label` |
| `question_with_prompt` | `prompt` |
| `hint_bridge` | — |
| `options_intro` | `count` |
| `option_item` | `ordinal`, `label` |
| `options_count_only` | `count` |
| `boolean_prompt`, `required_mark`, `no_match`, `required_reject`, `skipped`, `plausibility_keep`, `submitted`, `resume_welcome`, `review_all_correct`, `command_ack_*` | — |
| `confirm_readback` | `answer` |
| `confirm_option` | `label` |
| `section_intro` | `title` |
| `computed_statement` | `label`, `value` |
| `review_intro` | `count` |
| `review_item` | `position`, `label`, `answer` |
| `review_item_skipped` | `position`, `label` |
| `review_edit_ack`, `plausibility_flag` | `label` |

The full key set (spec §3 M3 `NARRATION_KEYS`): `question, question_with_prompt, hint_bridge, options_intro,
option_item, options_count_only, boolean_prompt, required_mark, confirm_readback, confirm_option, no_match,
required_reject, skipped, section_intro, computed_statement, review_intro, review_item, review_item_skipped,
review_all_correct, review_edit_ack, plausibility_flag, plausibility_keep, submitted, resume_welcome,
command_ack_repeat, command_ack_back, command_ack_skip, command_ack_help, command_ack_stop, command_ack_next,
command_ack_send, command_ack_change` (32 keys). Both locales MUST define all 32.

### Lexicon rules
- `commands` keys are exactly `repeat, back, skip, help, stop, next, send, change, yes, no` (lower-case names of
  `VoiceCommand`, TASK-4216).
- `ordinals` value `-1` means "last".
- Every lexicon phrase is stored **normalised** after loading (accents stripped, casefolded), so `"sí"` and `"si"` match.
- `normalize()` pipeline (spec §3 M3): NFKD → drop combining marks → casefold → strip punctuation → drop whole-word
  fillers → collapse whitespace. Fillers never include `option`/`opción`/`number`/`número` (the matcher needs them).
- Templates are Jinja2 source strings — this task only stores them; never render them here.

---

## Implementation Blueprint

### Steps (in order)
1. Write `lexicon.py` — *why*: the YAML structure is validated by its loader.
2. Write the two YAML files (identical key sets) — *why*: conformance is tested on both locales.
3. Write `narration/__init__.py`.
4. Add package-data — *why*: without it wheels ship no YAML and `load_lexicon` fails outside the source tree.
5. Write and run the tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py` (CREATE)
```python
"""Per-locale lexicon and transcript normalisation for voice forms (FEAT-649)."""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_LOCALE = "en"
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


class Lexicon(BaseModel):
    """Locale vocabulary used by the option matcher and command classifier."""

    locale: str
    ordinals: dict[str, int] = Field(default_factory=dict)
    cardinals: dict[str, int] = Field(default_factory=dict)
    yes: list[str] = Field(default_factory=list)
    no: list[str] = Field(default_factory=list)
    all: list[str] = Field(default_factory=list)
    none: list[str] = Field(default_factory=list)
    conjunctions: list[str] = Field(default_factory=list)
    fillers: list[str] = Field(default_factory=list)
    commands: dict[str, list[str]] = Field(default_factory=dict)
    review_confirm: list[str] = Field(default_factory=list)
    review_change: list[str] = Field(default_factory=list)


def locale_chain(locale: str) -> list[str]:
    """Fallback chain: ``es-MX`` → ``es`` → ``en`` (deduplicated, order kept)."""
    chain: list[str] = []
    for candidate in (locale, locale.replace("_", "-").split("-")[0], DEFAULT_LOCALE):
        if candidate and candidate not in chain:
            chain.append(candidate)
    return chain


def load_locale_document(locale: str, *, templates_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    """Load the first existing ``<dir>/<locale>/narration.yaml`` along the fallback chain.

    Returns ``(resolved_locale, document)``. Raises FileNotFoundError when even ``en`` is missing.
    """
    base = templates_dir or TEMPLATES_DIR
    for candidate in locale_chain(locale):
        path = base / candidate / "narration.yaml"
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return candidate, yaml.safe_load(fh) or {}
    raise FileNotFoundError(f"No narration.yaml for {locale!r} under {base}")


def _strip_text(text: str) -> str:
    """NFKD → drop combining marks → casefold → strip punctuation → collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _PUNCT_RE.sub(" ", no_marks.casefold())
    return _SPACE_RE.sub(" ", cleaned).strip()


def normalize(text: str, lexicon: Lexicon) -> str:
    """Normalise a transcript: accent/case/punctuation folding, then drop whole-word fillers."""
    stripped = _strip_text(text)
    fillers = set(lexicon.fillers)
    return " ".join(token for token in stripped.split(" ") if token and token not in fillers)


@lru_cache(maxsize=16)
def load_lexicon(locale: str) -> Lexicon:
    """Return the lexicon for ``locale`` (with fallback), every phrase pre-normalised."""
    resolved, document = load_locale_document(locale)
    raw = document.get("lexicon") or {}
    # FILL IN: apply _strip_text to every key of ordinals/cardinals, every list entry and every
    #          commands[*] entry (fillers too), then Lexicon(locale=resolved, **normalised) —
    #          bounded by "every lexicon phrase is stored normalised" (Implementation Notes)
    raise NotImplementedError
```
**Why this shape**: `normalize` is fully specified by spec §3 M3; only the per-collection normalisation loop is left.
`load_locale_document` is shared with the Narrator (TASK-4214) so both use one fallback rule. `lru_cache` keeps
loading off the hot path (lexicons are immutable at runtime).

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/en/narration.yaml` (CREATE)
```yaml
# FEAT-649 — English narration templates (Jinja2 source, rendered in a sandbox) + lexicon.
templates:
  question: "{{ label }}"
  question_with_prompt: "{{ prompt }}"
  hint_bridge: "Hint:"
  options_intro: "There are {{ count }} options:"
  option_item: "{{ ordinal }}, {{ label }}."
  options_count_only: "There are {{ count }} options on screen."
  boolean_prompt: "Please answer yes or no."
  required_mark: "This question is required."
  confirm_readback: "I heard: {{ answer }}. Is that correct?"
  confirm_option: "Did you mean {{ label }}?"
  no_match: "Sorry, I could not match that answer. Please try again."
  required_reject: "This question is required and cannot be skipped."
  skipped: "Skipped."
  section_intro: "Section: {{ title }}."
  computed_statement: "{{ label }} is set to {{ value }}."
  review_intro: "Let's review your {{ count }} answers."
  review_item: "{{ position }}. {{ label }}: {{ answer }}."
  review_item_skipped: "{{ position }}. {{ label }}: skipped."
  review_all_correct: "Is everything correct? Say yes to send, or say change and the number."
  review_edit_ack: "Let's change {{ label }}."
  plausibility_flag: "Your answer to {{ label }} may not fit the question. Say change to fix it, or yes to keep it."
  plausibility_keep: "Keeping your answer."
  submitted: "Thank you. Your form has been sent."
  resume_welcome: "Welcome back. Let's continue where you left off."
  command_ack_repeat: "Repeating."
  command_ack_back: "Going back."
  command_ack_skip: "Skipping."
  command_ack_help: "You can say repeat, back, skip, next, or stop."
  command_ack_stop: "Stopping the session."
  command_ack_next: "Next question."
  command_ack_send: "Sending your form."
  command_ack_change: "Which answer do you want to change?"
lexicon:
  ordinals: {first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6, seventh: 7, eighth: 8, ninth: 9, tenth: 10, last: -1}
  cardinals: {one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10}
  "yes": ["yes", "yeah", "yep", "ok", "okay", "sure", "correct", "right", "true"]
  "no": ["no", "nope", "incorrect", "wrong", "false"]
  all: ["all", "all of them", "everything"]
  none: ["none", "nothing", "none of them"]
  conjunctions: ["and", "plus", "also"]
  fillers: ["um", "uh", "er", "hmm", "well", "please"]
  commands:
    repeat: ["repeat", "say again", "again", "repeat that"]
    back: ["back", "go back", "previous"]
    skip: ["skip", "skip it", "pass"]
    help: ["help"]
    stop: ["stop", "cancel", "quit"]
    next: ["next", "continue"]
    send: ["send", "submit"]
    change: ["change", "edit"]
    "yes": ["yes", "ok", "okay", "correct"]
    "no": ["no", "incorrect"]
  review_confirm: ["yes", "ok", "okay", "send", "submit", "confirm", "correct"]
  review_change: ["change", "edit", "modify", "fix"]
```
**Why**: `"yes"`/`"no"` keys are quoted because YAML 1.1 parses bare `yes`/`no` as booleans.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/es/narration.yaml` (CREATE)
```yaml
# FEAT-649 — Spanish narration templates (Jinja2 source, rendered in a sandbox) + lexicon.
templates:
  question: "{{ label }}"
  question_with_prompt: "{{ prompt }}"
  hint_bridge: "Pista:"
  options_intro: "Hay {{ count }} opciones:"
  option_item: "{{ ordinal }}, {{ label }}."
  options_count_only: "Hay {{ count }} opciones en pantalla."
  boolean_prompt: "Responde sí o no."
  required_mark: "Esta pregunta es obligatoria."
  confirm_readback: "Entendí: {{ answer }}. ¿Es correcto?"
  confirm_option: "¿Quisiste decir {{ label }}?"
  no_match: "Lo siento, no pude reconocer esa respuesta. Inténtalo de nuevo."
  required_reject: "Esta pregunta es obligatoria y no se puede saltar."
  skipped: "Pregunta omitida."
  section_intro: "Sección: {{ title }}."
  computed_statement: "{{ label }} quedó en {{ value }}."
  review_intro: "Revisemos tus {{ count }} respuestas."
  review_item: "{{ position }}. {{ label }}: {{ answer }}."
  review_item_skipped: "{{ position }}. {{ label }}: omitida."
  review_all_correct: "¿Todo está correcto? Di sí para enviar, o di cambiar y el número."
  review_edit_ack: "Cambiemos {{ label }}."
  plausibility_flag: "Tu respuesta a {{ label }} podría no corresponder a la pregunta. Di cambiar para corregirla, o sí para mantenerla."
  plausibility_keep: "Mantengo tu respuesta."
  submitted: "Gracias. Tu formulario fue enviado."
  resume_welcome: "Bienvenido de nuevo. Continuemos donde lo dejaste."
  command_ack_repeat: "Repito."
  command_ack_back: "Regresando."
  command_ack_skip: "Saltando."
  command_ack_help: "Puedes decir repetir, atrás, saltar, siguiente o detener."
  command_ack_stop: "Deteniendo la sesión."
  command_ack_next: "Siguiente pregunta."
  command_ack_send: "Enviando tu formulario."
  command_ack_change: "¿Qué respuesta quieres cambiar?"
lexicon:
  ordinals: {primero: 1, primera: 1, segundo: 2, segunda: 2, tercero: 3, tercera: 3, cuarto: 4, cuarta: 4, quinto: 5, quinta: 5, sexto: 6, sexta: 6, "séptimo": 7, "séptima": 7, octavo: 8, octava: 8, noveno: 9, novena: 9, "décimo": 10, "décima": 10, "último": -1, "última": -1}
  cardinals: {uno: 1, una: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, nueve: 9, diez: 10}
  "yes": ["sí", "si", "claro", "ok", "vale", "correcto", "verdadero", "de acuerdo"]
  "no": ["no", "incorrecto", "falso"]
  all: ["todas", "todos", "todo"]
  none: ["ninguna", "ninguno", "nada"]
  conjunctions: ["y", "e", "más", "también"]
  fillers: ["eh", "pues", "bueno", "mmm", "por favor"]
  commands:
    repeat: ["repetir", "repite", "otra vez", "de nuevo"]
    back: ["atrás", "regresar", "volver", "anterior"]
    skip: ["saltar", "salta", "omitir", "paso"]
    help: ["ayuda"]
    stop: ["detener", "parar", "cancelar", "salir"]
    next: ["siguiente", "continuar"]
    send: ["enviar", "mandar"]
    change: ["cambiar", "corregir"]
    "yes": ["sí", "si", "ok", "vale", "correcto"]
    "no": ["no", "incorrecto"]
  review_confirm: ["sí", "si", "ok", "vale", "enviar", "confirmar", "correcto"]
  review_change: ["cambiar", "corregir", "modificar"]
```
**Why**: `"por favor"` is a two-word filler — `normalize` drops whole tokens, so implement filler removal so that
multi-word fillers are removed too (FILL IN below), or split it into `por`/`favor` only if that does not break
option labels; prefer removing the exact phrase.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/__init__.py` (CREATE)
```python
"""Deterministic narration (templates + lexicon) for audio forms (FEAT-649)."""

from .lexicon import TEMPLATES_DIR, Lexicon, load_lexicon, load_locale_document, locale_chain, normalize

__all__ = ["TEMPLATES_DIR", "Lexicon", "load_lexicon", "load_locale_document", "locale_chain", "normalize"]
```

### `packages/parrot-formdesigner/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot_formdesigner.renderers" = \["templates/\*.j2"\]' packages/parrot-formdesigner/pyproject.toml)
# AFTER — insert below `"parrot_formdesigner.renderers" = ["templates/*.j2"]` (verified: pyproject.toml:91)
"parrot_formdesigner.audio.narration" = ["templates/*/*.yaml"]
```
**Why**: the spec's Edit Sites row points at `"jinja2>=3.1",` (a dependency line); package-data belongs in
`[tool.setuptools.package-data]`. No dependency or lockfile change.

### FILL IN checklist
- [ ] `lexicon.py::load_lexicon` — per-collection normalisation; bounded by Implementation Notes
- [ ] `lexicon.py::normalize` — multi-word filler removal (e.g. `por favor`) without touching option words; bounded by spec §3 M3 pipeline
- [ ] test bodies marked `FILL IN`

---

## Acceptance Criteria

- [ ] `load_lexicon("es-MX").locale == "es"`; `load_lexicon("fr").locale == "en"`.
- [ ] `en` and `es` define the same 32 template keys (the full list above) and the same `commands` keys.
- [ ] `normalize("¡Sí, por favor!", load_lexicon("es")) == "si"`; `normalize("Opción 3", ...) == "opcion 3"`.
- [ ] Lexicon phrases are stored normalised (`"atras" in load_lexicon("es").commands["back"]`).
- [ ] `"yes"`/`"no"` entries load as lists of strings, not booleans.
- [ ] `pyproject.toml` package-data includes `templates/*/*.yaml`; no other pyproject change.
- [ ] `ruff check` clean on the Python files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py
import pytest

from parrot_formdesigner.audio.narration import load_lexicon, load_locale_document, locale_chain, normalize

EXPECTED_KEYS = {
    "question", "question_with_prompt", "hint_bridge", "options_intro", "option_item", "options_count_only",
    "boolean_prompt", "required_mark", "confirm_readback", "confirm_option", "no_match", "required_reject",
    "skipped", "section_intro", "computed_statement", "review_intro", "review_item", "review_item_skipped",
    "review_all_correct", "review_edit_ack", "plausibility_flag", "plausibility_keep", "submitted",
    "resume_welcome", "command_ack_repeat", "command_ack_back", "command_ack_skip", "command_ack_help",
    "command_ack_stop", "command_ack_next", "command_ack_send", "command_ack_change",
}
COMMAND_KEYS = {"repeat", "back", "skip", "help", "stop", "next", "send", "change", "yes", "no"}


class TestLexicon:
    def test_locale_chain(self):
        assert locale_chain("es-MX") == ["es-MX", "es", "en"]
        assert locale_chain("en") == ["en"]

    def test_fallback(self):
        assert load_lexicon("es-MX").locale == "es"
        assert load_lexicon("fr").locale == "en"

    @pytest.mark.parametrize("locale", ["en", "es"])
    def test_templates_and_commands_complete(self, locale):
        _, doc = load_locale_document(locale)
        assert set(doc["templates"]) == EXPECTED_KEYS
        assert set(doc["lexicon"]["commands"]) == COMMAND_KEYS

    def test_yes_no_are_strings(self):
        lex = load_lexicon("en")
        assert all(isinstance(x, str) for x in lex.yes + lex.no)

    def test_normalize_pipeline(self):
        es = load_lexicon("es")
        assert normalize("¡Sí, por favor!", es) == "si"
        assert normalize("Opción   3", es) == "opcion 3"

    def test_phrases_stored_normalised(self):
        # FILL IN: "atras" in load_lexicon("es").commands["back"]; "septimo" in load_lexicon("es").ordinals
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/audio-form-interaction-workflow.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
   (with `PYTHONPATH=packages/parrot-formdesigner/src` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4213 audio-form-interaction-workflow verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
