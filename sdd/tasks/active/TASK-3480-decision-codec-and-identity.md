# TASK-3480: Decision codec — canonical envelope, identity, and fingerprints

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3479
**Assigned-to**: unassigned

---

## Context

Module 1's second half. A `DecisionRecord` is persisted as an ordinary
`WikiPageRecord` whose body carries a canonical JSON envelope plus a readable
Markdown rendering. This task owns that reversible mapping and the deterministic
identity/fingerprint helpers every writer depends on.

The existing symbol serialization (`symbols.py:190` / `:238`) is deliberately
**not** reused: spec §6 "Does NOT Exist" records that it is lossy and cannot
carry ADR lifecycle or evidence data.

---

## Scope

- Implement `decision_to_page` / `decision_from_page` per the spec §2 "Identity,
  storage, and concurrency" body grammar.
- Implement deterministic identity: `documented_decision_id(rel_path)` and
  `candidate_decision_id(...)`.
- Implement `content_fingerprint` and the review before/after hash.
- Implement the mandatory origin/status label prefix on title and summary.
- Unit-test round-trip fidelity, label visibility in a generic page stub, and
  every malformed-envelope rejection.

**NOT in scope**: writing pages (TASK-3485), parsing Markdown ADRs (TASK-3486),
the CAS primitive (TASK-3481).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` | CREATE | Envelope encode/decode, identity, fingerprints, labels |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py` | CREATE | Round-trip, labels, malformed-envelope codes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens
# WikiPageRecord: store.py:409 (class), fields 444-456; estimate_tokens: store.py:318
from parrot.knowledge.wiki.decisions.models import (  # TASK-3479
    ADR_CATEGORY, ADR_RECORD_TOO_LARGE, ADR_SCHEMA_UNSUPPORTED, MAX_RECORD_BYTES,
    DecisionError, DecisionRecord,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
class WikiPageRecord(BaseModel):
    concept_id: str = Field(..., min_length=1)   # line 444
    node_id: Optional[str] = None                # line 445
    title: str = ""                              # line 446
    category: str = "concept"                    # line 447
    summary: str = ""                            # line 448
    body: str = ""                               # line 449
    source_id: Optional[str] = None              # line 450
    token_count: int = Field(default=0, ge=0)    # line 451
    origin: str = "ingest"                       # line 452
    asserted_by: Optional[str] = None            # line 453
    updated_at: Optional[str] = None             # line 454
    content_hash: Optional[str] = None           # line 455

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:318
def estimate_tokens(text: str) -> int: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:327 — hashing precedent ONLY
def sha1_of_text(text: str) -> str: ...
```

`get_page` returns a **`dict[str, Any]`**, not a `WikiPageRecord`
(`store.py:565`). That is why `decision_from_page` takes a dict.

### Does NOT Exist

- ~~`WikiPageRecord.metadata`~~ — the field list above is complete.
- ~~`symbols.symbol_to_page_fields` reuse for ADRs~~ — lossy (`symbols.py:238`);
  spec §6 forbids reusing it unchanged.
- ~~a `content_hash` computed by the store~~ — the caller supplies it; this codec
  is the only place ADR page hashes are computed.
- ~~fenced-code-block envelope parsing~~ — spec §2: "Parse only the fixed first
  two lines, never arbitrary fenced blocks."

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#estimate_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#sha1_of_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Canonical JSON is **one line**: `json.dumps(..., sort_keys=True,
  separators=(",", ":"), ensure_ascii=False)`. Embedded newlines are escaped by
  `json.dumps` itself — do not post-process.
- SHA-1 is an identity/version fingerprint here, not an authenticity mechanism
  (spec §7). Use `hashlib.sha1(...).hexdigest()` on UTF-8 bytes.
- `content_fingerprint` hashes canonical evidence + semantic content and
  **excludes** itself, `revision`, and `review_history` (spec §2). The review
  before/after hash covers title/context/decision/consequences/observations/
  hypotheses and review status only — a different, narrower digest.
- Pure and synchronous: no I/O, no store, no CLI imports (spec §7 "Keep
  parser/model modules free of CLI imports").

---

## Implementation Blueprint

### Steps (in order)

1. Write the two hashing helpers first — *why*: identity and the page
   `content_hash` both depend on one canonical byte serialization, and defining
   it once prevents two subtly different digests.
2. Write the id builders — *why*: `decision_to_page` needs `decision_id` to
   already be on the record, but the ingest/generation tasks call these builders
   to mint it, so they are part of this module's contract.
3. Write `decision_to_page`, then `decision_from_page` — *why*: writing the
   encoder first fixes the exact byte grammar the decoder must accept.
4. Write the tests last but run them against the encoder before the decoder is
   finished — *why*: round-trip is the only check that catches an asymmetry.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` (CREATE)

```python
"""Reversible ``DecisionRecord`` <-> wiki page mapping (FEAT-578 Module 1).

Body grammar (spec §2 "Identity, storage, and concurrency")::

    <!-- parrot-adr:v1 -->
    {"schema_version":1,...}          # one canonical JSON line

    # [DOCUMENTED / ACCEPTED] Use pgvector for the primary store
    ...readable markdown...

Only the first two lines are ever parsed. The Markdown tail is a rendering
for humans and for the generic wiki search surface — never a source of truth.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from parrot.knowledge.wiki.decisions.models import (
    ADR_CATEGORY,
    ADR_RECORD_TOO_LARGE,
    ADR_SCHEMA_UNSUPPORTED,
    MAX_RECORD_BYTES,
    DecisionError,
    DecisionRecord,
)
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

#: First line of every managed ADR body. Version bumps change this literal.
ENVELOPE_MARKER = "<!-- parrot-adr:v1 -->"


def _sha1(text: str) -> str:
    """SHA-1 hex digest of ``text`` as UTF-8 — identity, not authenticity."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324


def canonical_json(record: DecisionRecord) -> str:
    """Serialize a record to the one-line canonical JSON form."""
    return json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_fingerprint(record: DecisionRecord) -> str:
    """Fingerprint of the record's evidence and semantic content.

    Excludes ``content_fingerprint`` itself, ``revision`` and
    ``review_history`` so that a pure review action does not look like a
    content change (spec §2).
    """
    # FILL IN: build the dict to hash by dumping the record in JSON mode and
    # dropping exactly those three keys, sorting `evidence` deterministically
    # (by rel_path, start_line, end_line, source_sha1) before hashing — bounded
    # by spec §2 "Sort evidence deterministically" and AC6.
    raise NotImplementedError


def review_fingerprint(record: DecisionRecord) -> str:
    """Narrow digest for ``ReviewEvent.before_sha1`` / ``after_sha1``.

    Covers title, context, decision, consequences, observations, hypotheses
    and ``review_status`` only — deliberately not the audit history, which
    would make the hash self-referential (spec §2 ``ReviewEvent``).
    """
    # FILL IN: hash exactly those seven values in a fixed order — bounded by
    # spec §2 ReviewEvent ("avoiding a self-referential audit hash")
    raise NotImplementedError


def normalize_rel_path(rel_path: str) -> str:
    """POSIX-normalize a repository-relative path for identity hashing."""
    # FILL IN: forward slashes, no leading "./", no trailing slash, case
    # preserved — bounded by spec §2 "sha1(normalized-relative-path)"
    raise NotImplementedError


def documented_decision_id(rel_path: str) -> str:
    """Stable id of an imported ADR: ``adr:doc:<sha1(normalized path)>``."""
    return f"adr:doc:{_sha1(normalize_rel_path(rel_path))}"


def candidate_decision_id(scope_id: str, evidence_fingerprint: str, prompt_version: int, decision_text: str) -> str:
    """Stable id of a generated candidate: ``adr:candidate:<sha1(...)>``.

    The same scope and evidence snapshot therefore yield the same id, which
    is what lets a rerun return the existing (possibly reviewed) candidate
    instead of overwriting it (spec §2, AC6).
    """
    # FILL IN: join the four parts with a separator that cannot occur inside
    # them, normalizing decision_text (strip + collapse internal whitespace)
    # before hashing — bounded by spec §2 "normalized-candidate-decision"
    raise NotImplementedError


def status_labels(record: DecisionRecord) -> str:
    """Render the mandatory ``[ORIGIN / STATUS]`` prefix.

    Documented records show their source status; inferred records show their
    review status, so a generic wiki search can never present a candidate as
    an unlabeled decision (spec §2, AC3, AC9).
    """
    # FILL IN: documented -> f"[DOCUMENTED / {source_status.upper()}]";
    # inferred -> f"[INFERRED / {review_status.upper()}]" — bounded by spec §2
    # "Title begins with origin and status labels"
    raise NotImplementedError


def render_markdown(record: DecisionRecord) -> str:
    """Readable rendering appended after the envelope (and used by `adr export`)."""
    # FILL IN: labeled H1, then Context / Decision / Consequences sections, then
    # Observations and Hypotheses as separate lists, then a citations list of
    # `rel_path:start-end`. Observations and hypotheses must NEVER be merged —
    # bounded by AC4 ("observations separately from hypotheses")
    raise NotImplementedError


def decision_to_page(record: DecisionRecord) -> WikiPageRecord:
    """Render the canonical envelope and mandatory readable labels.

    Raises:
        DecisionError: ``ADR_RECORD_TOO_LARGE`` when the serialized body
            exceeds ``MAX_RECORD_BYTES``. History is never truncated to fit.
    """
    envelope = canonical_json(record)
    labels = status_labels(record)
    body = f"{ENVELOPE_MARKER}\n{envelope}\n\n{render_markdown(record)}"
    if len(body.encode("utf-8")) > MAX_RECORD_BYTES:
        raise DecisionError(
            ADR_RECORD_TOO_LARGE,
            f"serialized ADR record exceeds {MAX_RECORD_BYTES} bytes",
            decision_id=record.decision_id,
        )
    return WikiPageRecord(
        concept_id=record.decision_id,
        node_id=record.decision_id,
        title=f"{labels} {record.title}".strip(),
        category=ADR_CATEGORY,
        summary=f"{labels} {record.decision}"[:500],
        body=body,
        source_id=None,
        token_count=estimate_tokens(body),
        origin="ingest" if record.origin == "documented" else "authored",
        asserted_by=None,
        content_hash=_sha1(envelope),
    )


def decision_from_page(page: dict[str, Any]) -> DecisionRecord:
    """Decode a managed ADR page.

    Args:
        page: A row as returned by ``BaseWikiStore.get_page`` (store.py:565),
            i.e. a plain dict that must include a non-empty ``body``.

    Raises:
        DecisionError: ``ADR_SCHEMA_UNSUPPORTED`` for a wrong category, a
            missing/unknown envelope marker, unparseable JSON, or a payload
            that fails ``DecisionRecord`` validation.
    """
    # FILL IN: split the body into at most 3 parts on "\n"; require part 0 ==
    # ENVELOPE_MARKER and category == ADR_CATEGORY; json.loads part 1; wrap both
    # json.JSONDecodeError and pydantic.ValidationError into one
    # ADR_SCHEMA_UNSUPPORTED DecisionError carrying page["concept_id"] —
    # bounded by spec §2 "Unsupported versions return ADR_SCHEMA_UNSUPPORTED"
    raise NotImplementedError
```

**Why this shape**: `source_id=None` is deliberate and load-bearing — spec §2
says records must survive source-slice deletion, and `replace_source_slice`
(`store.py:550`) deletes every page carrying the source's id. `content_hash` is
the digest of the **envelope only**, not the whole body, so a change to the
human-readable rendering alone cannot invalidate an in-flight CAS. Do not change
`ENVELOPE_MARKER`, the two-line grammar, or the `adr:doc:` / `adr:candidate:`
prefixes — the parser, repository, retrieval and context grammar all key on them.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py` (CREATE)

```python
"""Codec round-trip, labels, and envelope rejection (FEAT-578 Module 1)."""

from __future__ import annotations

import json

import pytest

from parrot.knowledge.wiki.decisions.codec import (
    ENVELOPE_MARKER,
    candidate_decision_id,
    content_fingerprint,
    decision_from_page,
    decision_to_page,
    documented_decision_id,
)
from parrot.knowledge.wiki.decisions.models import DecisionError, DecisionRecord, EvidenceRef


@pytest.fixture
def documented() -> DecisionRecord:
    """A fully populated documented record — every field must survive."""
    # FILL IN: populate every DecisionRecord field including evidence, links,
    # review_history and observations/hypotheses, so the round-trip test is
    # actually total — bounded by test_codec_roundtrip_and_labels (spec §4)
    raise NotImplementedError


class TestRoundTrip:
    def test_codec_roundtrip_and_labels(self, documented):
        """All fields survive encode/decode; labels are visible in the stub."""
        page = decision_to_page(documented)
        assert page.category == "adr"
        assert page.source_id is None          # survives source-slice deletion
        assert page.title.startswith("[DOCUMENTED /")
        assert page.summary.startswith("[DOCUMENTED /")
        decoded = decision_from_page(page.model_dump())
        assert decoded == documented

    def test_inferred_labels_are_unmistakable(self):
        """A candidate can never render as an unlabeled decision (AC3/AC9)."""
        # FILL IN: build an origin='inferred', review_status='unreviewed' record;
        # assert both title and summary start with "[INFERRED / UNREVIEWED]"
        raise NotImplementedError

    def test_envelope_is_one_canonical_line(self, documented):
        """Line 1 is the marker, line 2 is sorted compact JSON."""
        lines = decision_to_page(documented).body.split("\n")
        assert lines[0] == ENVELOPE_MARKER
        assert json.loads(lines[1])["schema_version"] == 1
        assert ", " not in lines[1] and '": ' not in lines[1]


class TestInvalidEnvelope:
    @pytest.mark.parametrize(
        "mutate,reason",
        [
            (lambda p: p.update(body="not an adr"), "missing marker"),
            (lambda p: p.update(body="<!-- parrot-adr:v2 -->\n{}"), "unsupported version"),
            (lambda p: p.update(category="concept"), "wrong category"),
            (lambda p: p.update(body=f"{ENVELOPE_MARKER}\n{{nope"), "corrupt json"),
        ],
    )
    def test_invalid_envelope_and_version(self, documented, mutate, reason):
        """Corrupt/unsupported/wrong-category pages fail with a stable code."""
        page = decision_to_page(documented).model_dump()
        mutate(page)
        with pytest.raises(DecisionError) as exc:
            decision_from_page(page)
        assert exc.value.code == "ADR_SCHEMA_UNSUPPORTED", reason

    def test_oversized_record_is_refused_not_truncated(self):
        """History and evidence are never dropped to fit (spec §2)."""
        # FILL IN: build a record whose body exceeds MAX_RECORD_BYTES and assert
        # DecisionError.code == "ADR_RECORD_TOO_LARGE"
        raise NotImplementedError


class TestIdentity:
    @pytest.mark.parametrize("a,b", [("docs/adr/1.md", "./docs/adr/1.md"), ("docs/adr/1.md", "docs/adr/1.md")])
    def test_documented_id_is_path_normalized(self, a, b):
        """Equivalent spellings of one path yield one id."""
        assert documented_decision_id(a) == documented_decision_id(b)

    def test_distinct_paths_never_merge(self):
        """Path identity deliberately does not merge duplicate ADR numbers."""
        assert documented_decision_id("docs/adr/0042-a.md") != documented_decision_id("docs/adrs/0042-a.md")

    def test_candidate_id_is_stable_for_same_evidence(self):
        """AC6: same scope + evidence + decision text reuses the same id."""
        args = ("sym:a.py#f", "fp-1", 1, "  Use  pgvector ")
        assert candidate_decision_id(*args) == candidate_decision_id("sym:a.py#f", "fp-1", 1, "Use pgvector")

    def test_fingerprint_ignores_revision_and_history(self, documented):
        """A pure review action must not change the content fingerprint."""
        # FILL IN: bump revision and append a ReviewEvent; assert the
        # content_fingerprint is unchanged — bounded by spec §2 + AC6
        raise NotImplementedError
```

**Why**: `test_fingerprint_ignores_revision_and_history` is the executable form
of the dedup guarantee in AC6 — if review history leaked into the fingerprint,
every accepted candidate would be regenerated as a new record.

### FILL IN checklist

- [ ] `codec.py::content_fingerprint` — key exclusion + deterministic evidence sort; bounded by spec §2 / AC6
- [ ] `codec.py::review_fingerprint` — the seven covered values; bounded by spec §2 `ReviewEvent`
- [ ] `codec.py::normalize_rel_path` — POSIX normalization rules; bounded by spec §2 identity
- [ ] `codec.py::candidate_decision_id` — separator + decision-text normalization; bounded by spec §2
- [ ] `codec.py::status_labels` — the two label forms; bounded by spec §2 / AC9
- [ ] `codec.py::render_markdown` — sections, with observations and hypotheses kept apart; bounded by AC4
- [ ] `codec.py::decision_from_page` — the four rejection paths; bounded by `ADR_SCHEMA_UNSUPPORTED`
- [ ] `test_codec.py` — `documented` fixture and four test bodies

---

## Acceptance Criteria

- [ ] A fully populated `DecisionRecord` round-trips through `decision_to_page` / `decision_from_page` unchanged (AC1)
- [ ] `page.category == "adr"` and `page.source_id is None` for every encoded record
- [ ] Title and summary both begin with the origin/status label (AC3, AC9)
- [ ] Malformed marker, unsupported version, wrong category and corrupt JSON all raise `ADR_SCHEMA_UNSUPPORTED`
- [ ] An oversized record raises `ADR_RECORD_TOO_LARGE` instead of truncating history (spec §2)
- [ ] `content_fingerprint` is unchanged by a revision bump or a new review event (AC6)
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Identity, storage, and concurrency".
2. **Verify the Codebase Contract** — confirm `WikiPageRecord`'s field list at `store.py:444-456` still has no `metadata`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Commands pass.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
