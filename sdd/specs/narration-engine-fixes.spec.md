---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [security, voice-form, path-traversal, codeql]
---

# Feature Specification: Narration Engine Fixes — Locale Path-Traversal Hardening

**Feature ID**: FEAT-669
**Date**: 2026-10-14
**Author**: Claude (agent:sdd-fix, ledger issue:fdc36d0581ce)
**Status**: approved
**Target version**: 1.2.3

---

## 1. Motivation & Business Requirements

### Problem Statement

GitHub code scanning (CodeQL `py/path-injection`, high) reports five open alerts
(#223–#227) on `main @ 42376abda` against the formdesigner voice-narration module.
The taint source is `audio_ws.py:601` — `locale = data.get("locale", "en")` read
straight from the WebSocket `start_session` payload and used with **no format
validation**:

- **Real gap (alerts 223/224)** — `Narrator.__init__`
  (`audio/narration/engine.py:118-122`) builds `self._dir / loc / "narration.yaml"`
  for every `locale_chain()` candidate and reads + `yaml.safe_load`s it with **no
  containment check**. A locale like `../../../../x` reads any `narration.yaml`
  outside the packaged templates tree (CWE-22, constrained to that filename).
- **Guarded but still flagged (alerts 225/226/227)** — `lexicon.py
  load_locale_document` already resolves and checks `is_relative_to(base)`
  (commit `256f9e8ba`), but CodeQL does not model that barrier.

### Goals

- Reject malformed locales at the single shared source (`locale_chain`) so no
  path component downstream is ever attacker-shaped.
- Add the same resolve + containment guard to `Narrator.__init__` that
  `load_locale_document` already has (parity, defense in depth).
- Regression tests proving traversal-shaped locales fall back to `en` and the
  guards fail closed.
- Close ledger `issue:fdc36d0581ce`; allow dismissing alerts 225–227 as
  sanitized if the scanner still flags the guarded lines.

### Non-Goals (explicitly out of scope)

- No change to the WebSocket protocol or `start_session` message schema.
- No change to template content, narration keys, or lexicon semantics.
- No change to `load_locale_document`'s existing guard (it stays as is).
- No dismissal automation for GitHub alerts (manual, after merge).

---

## 2. Architectural Design

### Overview

Two-layer fix, both layers tiny and local to `audio/narration/`:

1. **Source validation** — `locale_chain()` (the one function every narration
   path consumer funnels locale candidates through) gains a strict format
   whitelist: a candidate must match `^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$`
   or it is dropped from the chain. `DEFAULT_LOCALE` (`en`) is always appended,
   so a fully-invalid locale yields `["en"]` and every caller keeps working via
   fallback instead of erroring.
2. **Sink containment** — `Narrator.__init__` resolves the templates root once
   and verifies each candidate file resolves inside it
   (`path.is_relative_to(base)`), raising `ValueError` on escape — the exact
   pattern `load_locale_document` already uses.

### Component Diagram

```
audio_ws.py:601 (WS payload locale)
        │
        ├──→ Narrator(locale) ──→ locale_chain() [M1: regex whitelist]
        │                         └→ path guard [M2: resolve + is_relative_to]
        └──→ load_lexicon(locale) ──→ load_locale_document()
                                       └→ locale_chain() [M1] + existing guard
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `lexicon.locale_chain` | modifies | adds regex filter; public contract for valid locales unchanged |
| `engine.Narrator.__init__` | modifies | adds containment check around existing loop |
| `lexicon.load_locale_document` | unchanged | existing guard kept verbatim |

### Data Models

None — no new models.

### New Public Interfaces

None — behavior change only for malformed locales (fallback to `en`).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: locale whitelist | yes | regex + filter in `locale_chain`, exact regex fixed | — |
| M2: Narrator guard | yes | resolve + `is_relative_to` mirror of lexicon.py:91-95 | — |
| M3: tests | yes | test list fixed in §4 | — |

### Module 1: Locale format whitelist in `locale_chain`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py`
- **Responsibility**: Drop any locale candidate that is not a plausible BCP-47-ish
  tag before it can become a path component.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # lexicon.py (modifies locale_chain, lexicon.py:69)
  _LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$")

  def locale_chain(locale: str) -> list[str]:
      """Fallback chain: ``es-MX`` → ``es`` → ``en`` (deduplicated, order kept).

      Candidates that do not match ``_LOCALE_RE`` are dropped (path-injection
      hardening — the chain feeds filesystem paths); ``DEFAULT_LOCALE`` is
      always present, so a malformed locale yields ``["en"]``.
      """
  ```

### Module 2: Containment guard in `Narrator.__init__`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py`
- **Responsibility**: Never read a `narration.yaml` that resolves outside the
  templates root, regardless of what the chain produced.
- **Depends on**: Module 1 (chain already clean; this is defense in depth).
- **Interface Skeleton**:
  ```python
  # engine.py (modifies Narrator.__init__, engine.py:111-123)
  class Narrator:
      def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None:
          """Load ``<locale>/narration.yaml`` with fallback ``es-MX → es → en``.

          Raises:
              ValueError: when a locale candidate resolves outside the
                  templates directory (mirrors lexicon.load_locale_document).
          """
          # base = (templates_dir or _TEMPLATES_DIR).resolve()
          # per candidate: path = (base / loc / "narration.yaml").resolve()
          #   if not path.is_relative_to(base): raise ValueError(...)
  ```

### Module 3: Regression tests
- **Path**: `packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py`,
  `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py`
- **Responsibility**: Lock the whitelist and both guards.
- **Depends on**: Modules 1–2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_locale_chain_rejects_traversal` | M1 | `locale_chain("../../x") == ["en"]`; same for `"..", "es/../..", "a/b", ""` |
| `test_locale_chain_accepts_valid_tags` | M1 | `es-MX`, `es_MX`, `en`, `pt-BR`, `zh-Hant-TW` keep their chains |
| `test_load_locale_document_traversal_falls_back` | M1 | `load_locale_document("../../etc")` returns the `en` document |
| `test_narrator_traversal_locale_falls_back_to_en` | M2 | `Narrator("../../x")` loads `en` templates and renders |
| `test_narrator_guard_raises_on_escaping_candidate` | M2 | monkeypatched `locale_chain` returning `"../esc"` → `ValueError` |

Existing tests that MUST keep passing unchanged: `test_locale_chain`
(`es-MX → es → en`), `test_fallback`, `test_narration_conformance_all_locales`,
`test_fallback_es_mx_to_es_to_en`.

### Integration Tests

None — the WS handler is untouched.

### Test Data / Fixtures

Reuse existing patterns in the two test files (packaged locales, `tmp_path`
template dirs).

---

## 5. Acceptance Criteria

- [ ] `locale_chain` drops every candidate not matching the whitelist and always
      includes `en`; traversal-shaped locales yield `["en"]`.
- [ ] `Narrator.__init__` raises `ValueError` for a candidate resolving outside
      the templates root and never opens such a path.
- [ ] `Narrator("../../x")` and `load_locale_document("../../x")` both fall back
      to `en` (no exception through the public API).
- [ ] All new tests plus the existing narration/lexicon suites pass:
      `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py packages/parrot-formdesigner/tests/formdesigner/test_audio_spoken_lexicon.py`
- [ ] `ruff check` clean on the touched files.
- [ ] Ledger `issue:fdc36d0581ce` closeable: both files appear in the feature diff.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot_formdesigner.audio.narration import load_lexicon, load_locale_document, locale_chain, normalize  # verified: tests/formdesigner/test_narration_lexicon.py:5
from parrot_formdesigner.audio.narration.engine import Narrator  # verified: api/audio_ws.py imports Narrator (audio_ws.py:686 call site)
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py
TEMPLATES_DIR = Path(__file__).parent / "templates"  # line 17
DEFAULT_LOCALE = "en"  # line 18
def locale_chain(locale: str) -> list[str]:  # line 69
def load_locale_document(locale: str, *, templates_dir: Path | None = None) -> tuple[str, dict[str, Any]]:  # line 78
    # lines 91-95: base.resolve(); per-candidate resolve(); is_relative_to(base) else ValueError

# packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py
_TEMPLATES_DIR = Path(__file__).parent / "templates"  # line 18
class Narrator:  # line 108
    def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None:  # line 111
        # line 115: self._dir = templates_dir or _TEMPLATES_DIR
        # lines 118-123: for loc in reversed(locale_chain(locale)): path = self._dir / loc / "narration.yaml"; is_file(); read_text()
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_LOCALE_RE` filter | `locale_chain` loop | candidate filter | `lexicon.py:71-75` |
| containment guard | `Narrator.__init__` loop | resolve + `is_relative_to` | `engine.py:118-123` |

### Does NOT Exist (Anti-Hallucination)

- ~~any locale validation in `audio_ws.py`~~ — the WS handler does not validate
  `data["locale"]`; do not add one there (out of scope).
- ~~`Narrator._base`~~ — no resolved-base attribute exists yet; the guard
  introduces a local variable, not a new attribute contract.

### Edit Sites (Blueprint Anchors)

Verified against: `dfd17735d`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py` | MODIFY | `def locale_chain(locale: str) -> list[str]:` | `lexicon.py:69` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` | MODIFY | `for loc in reversed(locale_chain(locale)):  # en first, most specific last wins` | `engine.py:118` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py` | MODIFY | `def test_locale_chain(self):` | `test_narration_lexicon.py:47` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py` | MODIFY | `def test_unknown_key_raises():` | `test_narration_engine.py:54` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror the exact guard already in `load_locale_document` (`lexicon.py:91-95`)
  — same resolve order, same `ValueError` message shape.
- The regex is a **whitelist of shape**, not of known locales: 2–3 letter
  primary subtag, then `-` or `_` separated alphanumeric subtags of 1–8 chars.
  `.`, `/`, `\`, and empty candidates all fail it.
- Keep the `es-MX → es → en` ordering and dedup semantics byte-identical for
  valid inputs — four existing tests pin them.

### Known Risks / Gotchas

- `locale_chain("es_MX")` currently produces `["es_MX", "es", "en"]`; `es_MX`
  must still match the regex (underscore separator is in the whitelist).
- Returning `["en"]` (not raising) for malformed locales is deliberate: the WS
  handler treats locale as a preference, and existing callers rely on fallback.
- CodeQL may still not credit either barrier; alerts 225–227 (and possibly
  223/224) may need manual dismissal as "sanitized" after merge. That is a
  GitHub UI action, not code.

### External Dependencies

None.

---

## 8. Open Questions

None — scope fixed by ledger `issue:fdc36d0581ce`.

---

## 9. Design Research Cross-Check

Skipped — small ledger-driven security fix (`/sdd-fix` lane); the fix mirrors an
existing in-repo guard pattern (`256f9e8ba`) rather than introducing new design.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Claude (agent:sdd-fix) | Initial spec from ledger issue:fdc36d0581ce (CodeQL alerts 223–227) |
