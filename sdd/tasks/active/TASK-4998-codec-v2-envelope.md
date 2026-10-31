# TASK-4998: Codec v2 envelope, spec_decision_id, package exports

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4997
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half). Schema-2 records must be written behind a new envelope marker
`<!-- parrot-adr:v2 -->` while v1 bodies stay readable; an unknown schema must fail explicitly with
`ADR_SCHEMA_UNSUPPORTED` (the spec writes `ADR_UNSUPPORTED_SCHEMA` — same code, repo spelling wins, see
models.py:19). Spec entries get the stable id `adr:spec:<document_id>#<entry_id>` (AC3). The new reference
models are exported lazily from the package.

---

## Scope

- Add `ENVELOPE_MARKER_V2` and make `decision_to_page` write v2 for `schema_version == 2` records, v1 otherwise.
- Make `decision_from_page` accept both markers, require the marker to agree with the payload's
  `schema_version`, and raise `DecisionError(ADR_SCHEMA_UNSUPPORTED)` on anything else (no partial record).
- Add `spec_decision_id(document_id, entry_id)` raising `DecisionError(ADR_INVALID_ID)` on a bad charset.
- Export `DecisionRef`, `DecisionTarget` from `parrot.knowledge.wiki.decisions` (lazy map + `__all__` + TYPE_CHECKING).
- Tests in `test_codec.py`.

**NOT in scope**: parsing `## Decisions` blocks (TASK-4999); `ConsequenceService` / `BatchPublisher` exports (TASK-5008).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` | MODIFY | v2 marker, `spec_decision_id`, decode by marker |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` | MODIFY | lazy exports `DecisionRef`, `DecisionTarget` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py` | MODIFY | v2 / unsupported / id tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import (  # verified: models.py:19,40,47,172 (+ ADR_INVALID_ID from TASK-4997)
    ADR_CATEGORY, ADR_INVALID_ID, ADR_SCHEMA_UNSUPPORTED, DecisionError, DecisionRecord,
)
from parrot.knowledge.wiki.decisions.codec import (  # verified: codec.py:34,104,160,191
    ENVELOPE_MARKER, decision_from_page, decision_to_page, documented_decision_id,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py
from parrot.knowledge.wiki.decisions.models import (   # line 23 — import block, ends line 30
    ADR_CATEGORY, ADR_RECORD_TOO_LARGE, ADR_SCHEMA_UNSUPPORTED, MAX_RECORD_BYTES, DecisionError, DecisionRecord,
)
ENVELOPE_MARKER = "<!-- parrot-adr:v1 -->"            # line 34
def canonical_json(record: DecisionRecord) -> str     # line 47
def documented_decision_id(rel_path: str) -> str:     # line 104 — "adr:doc:<sha1>"
def decision_to_page(record: DecisionRecord) -> WikiPageRecord:   # line 160; body built at line 169:
    body = f"{ENVELOPE_MARKER}\n{envelope}\n\n{render_markdown(record)}"
def decision_from_page(page: dict[str, Any]) -> DecisionRecord:  # line 191; marker check at line 212:
    if len(parts) < 2 or parts[0] != ENVELOPE_MARKER:

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py
        DecisionRecord,                                  # line 36 — TYPE_CHECKING import from .models
    "DecisionRecord",                                    # line 57 — __all__
    "DecisionRecord": "parrot.knowledge.wiki.decisions.models",   # line 77 — _LAZY_SOURCES
```

### Does NOT Exist
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — use `ADR_SCHEMA_UNSUPPORTED`.
- ~~`ENVELOPE_MARKER_V2`, `spec_decision_id`~~ — created here.
- ~~eager imports in `decisions/__init__.py`~~ — the package is PEP 562 lazy on purpose (import cycle, docstring lines 13-22); never add a module-level `from .models import ...` outside `TYPE_CHECKING`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#decision_to_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#decision_from_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#documented_decision_id"
  ]
}
```

---

## Implementation Notes

- `content_hash = _sha1(envelope)` (codec.py) is computed over the JSON line only — unchanged by the marker.
  Schema-1 records keep the v1 marker, so existing pages keep identical bytes and hashes (AC2).
- The id charset is `[a-z0-9_-]+` for both parts (spec §3 M1 skeleton).
- Rollout note (spec §7 F10): old readers fail explicitly on v2 — that is the desired behaviour.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import re`, `ADR_INVALID_ID` import, `ENVELOPE_MARKER_V2`, `_MARKER_SCHEMA`, `_ID_PART` — *why*: decode and id validation need them.
2. Add `spec_decision_id` after `documented_decision_id` — *why*: spec entry identity (AC3).
3. Pick the marker by schema in `decision_to_page` — *why*: v1 bytes must stay identical.
4. Decode by marker in `decision_from_page` — *why*: explicit failure on unknown schema (AC2).
5. Lazy-export the two models; write tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^import json$' codec.py)
# AFTER — insert below `import json` (verified: codec.py:18)
import re

# occurrences: 1 (verified: grep -c '    ADR_CATEGORY,' codec.py)
# AFTER — insert below `    ADR_CATEGORY,` inside the models import block (verified: codec.py:24)
    ADR_INVALID_ID,

# occurrences: 1 (verified: grep -c 'ENVELOPE_MARKER = "<!-- parrot-adr:v1 -->"' codec.py)
# AFTER — insert below `ENVELOPE_MARKER = "<!-- parrot-adr:v1 -->"` (verified: codec.py:34)
#: Marker for schema-2 records (FEAT-784). v1 is still written for schema-1 records and read forever.
ENVELOPE_MARKER_V2 = "<!-- parrot-adr:v2 -->"
#: marker -> the only schema_version allowed behind it.
_MARKER_SCHEMA: dict[str, int] = {ENVELOPE_MARKER: 1, ENVELOPE_MARKER_V2: 2}
_ID_PART = re.compile(r"^[a-z0-9_-]+$")

# occurrences: 1 (verified: grep -c 'def documented_decision_id(rel_path: str) -> str:' codec.py)
# AFTER — insert after the body of `documented_decision_id` (verified: codec.py:104-106)


def spec_decision_id(document_id: str, entry_id: str) -> str:
    """Stable id of a spec/seed decision entry: ``adr:spec:<document_id>#<entry_id>``.

    Path-independent (renaming the spec keeps identity, AC3).

    Raises:
        DecisionError: ``ADR_INVALID_ID`` when either part is not ``[a-z0-9_-]+``.
    """
    for label, part in (("document_id", document_id), ("entry_id", entry_id)):
        if not _ID_PART.match(part or ""):
            raise DecisionError(ADR_INVALID_ID, f"{label} {part!r} must match [a-z0-9_-]+")
    return f"adr:spec:{document_id}#{entry_id}"

# occurrences: 1 (verified: grep -c 'body = f"{ENVELOPE_MARKER}\\n{envelope}' codec.py)
# REPLACE the body line in decision_to_page (verified: codec.py:169) with:
    marker = ENVELOPE_MARKER_V2 if record.schema_version == 2 else ENVELOPE_MARKER
    body = f"{marker}\n{envelope}\n\n{render_markdown(record)}"

# occurrences: 1 (verified: grep -c 'parts\[0\] != ENVELOPE_MARKER' codec.py)
# REPLACE in decision_from_page (verified: codec.py:212-217) the marker check + the try block with:
    expected_schema = _MARKER_SCHEMA.get(parts[0]) if len(parts) >= 2 else None
    if expected_schema is None:
        raise DecisionError(ADR_SCHEMA_UNSUPPORTED, "missing or unsupported ADR envelope marker",
                            decision_id=concept_id)
    try:
        payload = json.loads(parts[1])
        # FILL IN: if payload is not a dict or payload.get("schema_version", 1) != expected_schema,
        #          raise DecisionError(ADR_SCHEMA_UNSUPPORTED, ...) BEFORE model_validate — bounded by AC2
        #          ("never silent data loss": a v3 payload behind any marker must not partially decode)
        return DecisionRecord.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        # keep the existing raise unchanged
```
**Why**: the marker is the version switch the spec freezes (S3); checking marker/payload agreement
prevents a v2 body hidden behind a v1 marker from being read by a schema-1-only consumer as valid.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        DecisionRecord,' __init__.py)
# AFTER — insert below `        DecisionRecord,` (verified: __init__.py:36)
        DecisionRef,
        DecisionTarget,

# occurrences: 1 (verified: grep -c '    "DecisionRecord",' __init__.py)
# AFTER — insert below `    "DecisionRecord",` (verified: __init__.py:57)
    "DecisionRef",
    "DecisionTarget",

# occurrences: 1 (verified: grep -c '    "DecisionRecord": "parrot.knowledge.wiki.decisions.models",' __init__.py)
# AFTER — insert below that line (verified: __init__.py:77)
    "DecisionRef": "parrot.knowledge.wiki.decisions.models",
    "DecisionTarget": "parrot.knowledge.wiki.decisions.models",
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py` (MODIFY — append)
```python
# --- FEAT-784 ------------------------------------------------------------------
from parrot.knowledge.wiki.decisions.codec import ENVELOPE_MARKER_V2, spec_decision_id  # noqa: E402


def test_v1_record_keeps_v1_marker_and_hash():
    # FILL IN: schema-1 record → decision_to_page body starts with ENVELOPE_MARKER; content_hash unchanged vs before


def test_v2_record_round_trips():
    # FILL IN: schema_version=2 record with about/targets → body starts with ENVELOPE_MARKER_V2 →
    #          decision_from_page(page.model_dump()) == record


@pytest.mark.parametrize("marker,schema", [("<!-- parrot-adr:v3 -->", 3), (None, 3), (None, 2)])
def test_unsupported_schema_fails_explicitly(marker, schema):
    """AC2: unknown marker, v3 payload, or v2 payload behind the v1 marker ⇒ ADR_SCHEMA_UNSUPPORTED."""
    # FILL IN: craft page dict (category "adr"); marker None means ENVELOPE_MARKER;
    #          with pytest.raises(DecisionError) as e: decision_from_page(page); assert e.value.code == "ADR_SCHEMA_UNSUPPORTED"


@pytest.mark.parametrize("doc,entry,ok", [("feat-784", "rule_1", True), ("Feat", "x", False),
                                          ("a b", "x", False), ("doc", "", False), ("doc", "a#b", False)])
def test_spec_decision_id_charset(doc, entry, ok):
    # FILL IN: ok → == f"adr:spec:{doc}#{entry}"; else DecisionError code ADR_INVALID_ID


def test_lazy_exports():
    import parrot.knowledge.wiki.decisions as pkg
    assert pkg.DecisionRef.__name__ == "DecisionRef" and "DecisionTarget" in pkg.__all__
```

### FILL IN checklist
- [ ] `decision_from_page` marker/payload agreement — AC2
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Existing `test_codec.py` tests pass unchanged (v1 bytes identical).
- [ ] v2 round trip; v3 payload / unknown marker / mismatched marker ⇒ `ADR_SCHEMA_UNSUPPORTED`.
- [ ] `spec_decision_id("feat-784", "rule")  == "adr:spec:feat-784#rule"`; bad charset ⇒ `ADR_INVALID_ID`.
- [ ] `from parrot.knowledge.wiki.decisions import DecisionRef, DecisionTarget` works.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py -q`

---

## Test Specification

See the `test_codec.py` blueprint block (spec §4 `test_unsupported_schema_fails_explicitly`, `test_spec_decision_id_charset`).

---

## Agent Instructions

1. Work in worktree `feat-FEAT-784-sdd-decision-audit`; TASK-4997 must be `done`.
2. Verify anchors with `grep -c`; implement the blueprint; complete FILL INs.
3. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the three files; `scripts/sdd/close_task.sh TASK-4998 sdd-decision-audit verified`.

---

## Completion Note

*(filled in by the implementing agent)*
