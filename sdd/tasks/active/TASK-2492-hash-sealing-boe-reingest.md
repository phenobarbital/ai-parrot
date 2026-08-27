# TASK-2492: Content-hash sealing for BOE article versions + full re-ingest

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (Sprint 1.5 — evidence retrofit, R3/R7/R11). The span
existence gate (TASK-2495) can only be deterministic if every stored
`articulo.versions[]` entry carries a sealed `content_hash` computed over the
*exact* text that is stored — "hash what you store, slice what you stored".
This task adds the normalization + hashing primitive, threads it through the
parser so the stored `text` IS the normalized text, and re-ingests the corpus.

This task is **blocking** for TASK-2495, TASK-2496, TASK-2497, TASK-2499.

---

## Scope

- Create `parrot_tools/legal/boe/hashing.py` with `HASH_NORM_VERSION = 1`,
  `normalize_for_hash(text) -> str` (Unicode NFC + `\r\n`|`\r` → `\n`,
  **nothing else** — no whitespace collapse, no strip) and
  `seal_hash(normalized_text) -> str` (sha256 hex over UTF-8 of the
  already-normalized text). Module docstring must state that bumping
  `HASH_NORM_VERSION` invalidates every stored span.
- Extend `ArticleVersion` (`boe/models.py`) with `content_hash: str | None`
  and `hash_norm_version: int | None` appended after `derived`, plus a
  `model_validator(mode="after")` enforcing
  `text is None ⇔ content_hash is None ⇔ hash_norm_version is None`.
  Update the class docstring.
- Modify `parser.py::_parse_bloque` version loop: normalize the extracted
  body text, store the normalized text, seal the hash, pass both new fields
  into `ArticleVersion(...)`. `supresion` versions (`text=None`) carry no hash.
- Export `normalize_for_hash`, `seal_hash`, `HASH_NORM_VERSION` from
  `parrot_tools/legal/boe/__init__.py` (check current exports first).
- Update TASK-2376 fixtures/tests under `packages/ai-parrot-tools/tests/legal/`
  that assert version dicts: extend expected records with the two new fields —
  do NOT loosen assertions.
- Write unit tests `test_normalize_for_hash_nfc_newlines_only`,
  `test_article_version_carries_sealed_hash`, and a validator test for the
  invariant.
- Re-ingest: document (in the Completion Note) the operator command
  `await sync_boe(tenant_id, since=None)` — full refresh (R7). Run it against
  the dev ArangoDB tenant if reachable (VPN); if the dev DB times out, note
  the `ENV=prod` fallback per spec §3 M1 and record whether the re-ingest was
  executed or deferred.

**NOT in scope**: the `search_articles` helper (TASK-2496), any ontology YAML
change (TASK-2494), hash *verification* (TASK-2495 — the verifier recomputes;
this task only seals). No change to `datasource.py`/`sync.py` bodies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/hashing.py` | CREATE | `normalize_for_hash`, `seal_hash`, `HASH_NORM_VERSION` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/models.py` | MODIFY | `ArticleVersion` + 2 fields + after-validator |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/parser.py` | MODIFY | `_parse_bloque` normalize → store → seal |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/__init__.py` | MODIFY | export hashing helpers |
| `packages/ai-parrot-tools/tests/legal/test_boe_hashing.py` | CREATE | unit tests |
| `packages/ai-parrot-tools/tests/legal/test_boe_parser.py` | MODIFY | expected version dicts gain the two fields |
| `packages/ai-parrot-tools/tests/legal/test_boe_datasource.py` | MODIFY | same, where version dicts are asserted |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev`.

### Verified Imports
```python
from parrot_tools.legal.boe.models import ArticleVersion, ParsedNorm   # boe/models.py:16,49
from parrot_tools.legal.boe.parser import parse_consolidated            # boe/parser.py:83
from parrot_tools.legal.boe.sync import sync_boe                        # boe/sync.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/legal/boe/models.py:16-46
class ArticleVersion(BaseModel):
    n: int                                   # :39
    text: str | None                         # :40
    valid_from: date                         # :41
    valid_to: date | None                    # :42
    modified_by: str | None                  # :43
    kind: Literal["redaccion", "adicion", "supresion"]   # :44
    source: Literal["boe_consolidada"]       # :45
    derived: bool                            # :46  ← append the two new fields AFTER this

# packages/ai-parrot-tools/src/parrot_tools/legal/boe/parser.py
def _extract_body_text(version_el: ET.Element) -> str | None:   # :175
def _parse_bloque(bloque_el: ET.Element, norma_boe_id: str) -> dict:   # :202
#   :232   text = None if kind == "supresion" else _extract_body_text(version_el)
#   :235   ArticleVersion(n=idx, text=text, valid_from=valid_from, valid_to=None, ...)
#   valid_to is chained AFTER the loop — do not touch that logic.
#   Returned record: versions serialized via model_dump(mode="json") — keep shape.

# packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py:24
async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport
#   since=None ⇒ full refresh (R7).
```

### Does NOT Exist
- ~~`ArticleVersion.content_hash` / `hash_norm_version`~~ — this task creates them.
- ~~`parrot_tools.legal.boe.hashing`~~ — this task creates it.
- ~~Any hash-on-read backfill in `datasource.py`/`sync.py`~~ — rejected (R7); do not add.
- ~~Whitespace collapse / `.strip()` inside `normalize_for_hash`~~ — forbidden (R11):
  offsets must index text identical to what the lawyer is shown.

---

## Implementation Notes

### Pattern to Follow
```python
# hashing.py — complete body per spec §3 M1
import hashlib
import unicodedata

HASH_NORM_VERSION = 1

def normalize_for_hash(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")

def seal_hash(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
```

```python
# parser.py::_parse_bloque — replace line 232 with:
raw = None if kind == "supresion" else _extract_body_text(version_el)
text = normalize_for_hash(raw) if raw is not None else None
content_hash = seal_hash(text) if text is not None else None
norm_version = HASH_NORM_VERSION if text is not None else None
# ...and pass content_hash=content_hash, hash_norm_version=norm_version to ArticleVersion(...)
```

### Key Constraints
- The stored `text` IS the normalized text. Never store raw and hash normalized.
- Validator: use `@model_validator(mode="after")` (Pydantic v2); raise
  `ValueError` with a clear message when the three-way equivalence is broken.
- Google-style docstrings, strict typing.
- Run `pytest packages/ai-parrot-tools/tests/legal/ -v` — every pre-existing
  test must still pass with fixtures extended (not loosened).

### References in Codebase
- `packages/ai-parrot-tools/tests/legal/conftest.py` — `boe_corpus`, `FakeGraphStore`
- `packages/ai-parrot-tools/tests/legal/fixtures/boe_consolidated_sample.xml` — TASK-2372 fixture

---

## Acceptance Criteria

- [ ] `normalize_for_hash("a\r\nb\r c")` == `"a\nb\n c"`; NFC applied; interior double spaces untouched
- [ ] Every non-`supresion` version parsed from the fixture carries `content_hash == seal_hash(text)` and `hash_norm_version == 1`
- [ ] `supresion` versions carry `content_hash is None and hash_norm_version is None`
- [ ] `ArticleVersion(text="x", content_hash=None, ...)` raises `ValueError` (validator)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/ -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`
- [ ] Re-ingest executed on the dev tenant OR explicitly deferred with reason in the Completion Note

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_boe_hashing.py
import hashlib
import pytest
from parrot_tools.legal.boe.hashing import HASH_NORM_VERSION, normalize_for_hash, seal_hash
from parrot_tools.legal.boe.models import ArticleVersion
from parrot_tools.legal.boe.parser import parse_consolidated


def test_normalize_for_hash_nfc_newlines_only():
    assert normalize_for_hash("a\r\nb\rc") == "a\nb\nc"
    assert normalize_for_hash("é") == "é"        # NFC composes
    assert normalize_for_hash("a  b\n") == "a  b\n"          # no collapse, no strip


def test_seal_hash_is_sha256_of_utf8():
    assert seal_hash("hola") == hashlib.sha256("hola".encode()).hexdigest()


def test_article_version_carries_sealed_hash(boe_corpus):
    parsed = parse_consolidated(boe_corpus)
    for art in parsed.articulos:
        for v in art["versions"]:
            if v["text"] is None:
                assert v["content_hash"] is None and v["hash_norm_version"] is None
            else:
                assert v["content_hash"] == seal_hash(v["text"])
                assert v["hash_norm_version"] == HASH_NORM_VERSION


def test_article_version_validator_rejects_partial_hash():
    with pytest.raises(ValueError):
        ArticleVersion(n=0, text="x", valid_from="2020-01-01", valid_to=None,
                       modified_by=None, kind="redaccion", source="boe_consolidada",
                       derived=False, content_hash=None, hash_norm_version=1)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§3 M1, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `_parse_bloque` still builds `ArticleVersion` at ~line 235
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2492-hash-sealing-boe-reingest.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
