# TASK-4294: Harden narration locale handling against path traversal

**Feature**: FEAT-669 — Narration Engine Fixes — Locale Path-Traversal Hardening
**Spec**: `sdd/specs/narration-engine-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

CodeQL alerts #223–#227 (`py/path-injection`, high) on `main`: the WebSocket
`start_session` locale (`audio_ws.py:601`) flows unvalidated into
`Narrator.__init__`, which builds `<templates>/<locale>/narration.yaml` paths
with no containment check (alerts 223/224 — real CWE-22). `lexicon.py`'s
`load_locale_document` already guards with resolve + `is_relative_to`
(alerts 225–227 are unmodeled-barrier noise). This task implements spec §3
Modules 1–3: a locale-format whitelist at the shared source (`locale_chain`),
the same containment guard in `Narrator.__init__`, and regression tests.
Ledger: `issue:fdc36d0581ce`.

---

## Scope

- Add `_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$")` to
  `lexicon.py` and filter `locale_chain()` candidates through it; `DEFAULT_LOCALE`
  is always included, so a fully-invalid locale yields `["en"]`.
- Add a resolve + `is_relative_to` containment guard to `Narrator.__init__`
  (`engine.py`), raising `ValueError` when a candidate path escapes the
  templates root — mirror of `lexicon.py:91-95`.
- Write the five regression tests from spec §4 in the two existing test files.

**NOT in scope**: changes to `audio_ws.py` or the WS protocol; changes to
`load_locale_document`'s existing guard; template/lexicon content; GitHub alert
dismissal.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py` | MODIFY | `_LOCALE_RE` + filter in `locale_chain` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` | MODIFY | containment guard in `Narrator.__init__` |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py` | MODIFY | whitelist + fallback regression tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py` | MODIFY | Narrator fallback + guard tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.narration import load_lexicon, load_locale_document, locale_chain, normalize  # verified: tests/formdesigner/test_narration_lexicon.py:5
from parrot_formdesigner.audio.narration.engine import NARRATION_KEYS, Narrator, render_author_prompt  # verified: engine module symbols at engine.py:20/108/95
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py
TEMPLATES_DIR = Path(__file__).parent / "templates"  # line 17
DEFAULT_LOCALE = "en"  # line 18
def locale_chain(locale: str) -> list[str]:  # line 69 — builds (locale, primary-subtag, DEFAULT_LOCALE), deduped
def load_locale_document(locale: str, *, templates_dir: Path | None = None) -> tuple[str, dict[str, Any]]:  # line 78
    # lines 91-95: base = (templates_dir or TEMPLATES_DIR).resolve();
    #   path = (base / candidate / "narration.yaml").resolve();
    #   if not path.is_relative_to(base): raise ValueError(...)

# packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py
_TEMPLATES_DIR = Path(__file__).parent / "templates"  # line 18
class Narrator:  # line 108
    def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None:  # line 111
        # line 115: self._dir = templates_dir or _TEMPLATES_DIR
        # line 118: for loc in reversed(locale_chain(locale)):  # en first, most specific last wins
        # line 119:     path = self._dir / loc / "narration.yaml"
        # lines 120-123: is_file() → yaml.safe_load(path.read_text(...)) → templates.update(...)
```

### Does NOT Exist
- ~~locale validation in `audio_ws.py`~~ — none exists; do not add one (out of scope).
- ~~`Narrator._base`~~ — no resolved-base attribute; the guard uses a local variable.
- ~~`tests/formdesigner/test_narration_engine.py::TestNarrator`~~ — engine tests are module-level functions, not a class.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py#locale_chain",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py#load_locale_document",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py#Narrator.__init__"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# lexicon.py:91-95 — the existing guard to mirror in Narrator.__init__
base = (templates_dir or TEMPLATES_DIR).resolve()
path = (base / candidate / "narration.yaml").resolve()
if not path.is_relative_to(base):
    raise ValueError(f"Locale {locale!r} resolves outside templates directory")
```

### Key Constraints
- `locale_chain` ordering/dedup for VALID locales must stay byte-identical —
  `test_locale_chain` pins `["es-MX", "es", "en"]`.
- `es_MX` (underscore) must remain a valid candidate.
- Malformed locales must NOT raise through the public API — they fall back to `en`.
- 120-column lines, Google docstrings, `ruff check` clean.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_LOCALE_RE` to `lexicon.py` and filter candidates in `locale_chain` — *why*: single shared sanitizer for every narration path consumer.
2. Add the containment guard to `Narrator.__init__` — *why*: defense in depth at the only unguarded sink (alerts 223/224).
3. Add the five regression tests — *why*: pin the whitelist and both guards.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def locale_chain' lexicon.py)
# REPLACE the body of locale_chain (lexicon.py:69-75); add _LOCALE_RE near _PUNCT_RE/_SPACE_RE (line 19-20)
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$")

def locale_chain(locale: str) -> list[str]:
    """Fallback chain: ``es-MX`` → ``es`` → ``en`` (deduplicated, order kept).

    Candidates that do not match ``_LOCALE_RE`` are dropped — the chain feeds
    filesystem paths (``<templates>/<candidate>/narration.yaml``), so this is
    the path-injection barrier for every consumer. ``DEFAULT_LOCALE`` is always
    present: a malformed locale yields ``["en"]``.
    """
    chain: list[str] = []
    for candidate in (locale, locale.replace("_", "-").split("-")[0], DEFAULT_LOCALE):
        if candidate and candidate not in chain and _LOCALE_RE.fullmatch(candidate):
            chain.append(candidate)
    return chain
```
**Why this shape**: keeps the existing three-candidate derivation and dedup untouched for valid tags; only adds the regex gate (spec §3 M1).

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'for loc in reversed' engine.py)
# REPLACE lines 115-122 body portion: resolve the root once, guard each candidate
        base = (templates_dir or _TEMPLATES_DIR).resolve()
        self._dir = templates_dir or _TEMPLATES_DIR
        ...
        for loc in reversed(locale_chain(locale)):  # en first, most specific last wins
            path = (base / loc / "narration.yaml").resolve()
            if not path.is_relative_to(base):
                raise ValueError(f"Locale {locale!r} resolves outside templates directory")
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
```
**Why**: mirrors `load_locale_document`'s guard exactly (spec §7); `self._dir` stays as-is for any other consumer.

### FILL IN checklist
- [ ] tests per spec §4 table — bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] `locale_chain("../../x") == ["en"]`; `locale_chain("es-MX")` unchanged.
- [ ] `Narrator("../../x")` loads `en` templates; monkeypatched escaping candidate raises `ValueError`.
- [ ] `load_locale_document("../../etc")` returns the `en` document.
- [ ] All validation commands pass; `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_spoken_lexicon.py -q`
- `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py`

---

## Test Specification

```python
# add to tests/formdesigner/test_narration_lexicon.py
@pytest.mark.parametrize("bad", ["../../x", "..", "es/../..", "a/b", "", ".", "es-MX/../.."])
def test_locale_chain_rejects_traversal(bad):
    assert locale_chain(bad) == ["en"]

@pytest.mark.parametrize(("tag", "head"), [("es-MX", "es-MX"), ("es_MX", "es_MX"), ("pt-BR", "pt-BR"), ("zh-Hant-TW", "zh-Hant-TW")])
def test_locale_chain_accepts_valid_tags(tag, head):
    chain = locale_chain(tag)
    assert chain[0] == head and chain[-1] == "en"

def test_load_locale_document_traversal_falls_back():
    resolved, doc = load_locale_document("../../etc")
    assert resolved == "en" and doc

# add to tests/formdesigner/test_narration_engine.py
def test_narrator_traversal_locale_falls_back_to_en():
    n = Narrator("../../x")
    assert n.render("no_match")

def test_narrator_guard_raises_on_escaping_candidate(monkeypatch):
    monkeypatch.setattr("parrot_formdesigner.audio.narration.engine.locale_chain", lambda loc: ["../escape"])
    with pytest.raises(ValueError, match="outside templates"):
        Narrator("en")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug narration-engine-fixes --feature-id FEAT-669`)
2. **Read the spec** at `sdd/specs/narration-engine-fixes.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/narration-engine-fixes.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the four listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4294 narration-engine-fixes verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
