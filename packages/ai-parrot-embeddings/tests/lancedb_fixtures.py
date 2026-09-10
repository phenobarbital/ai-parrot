"""Deterministic fixtures shared by every LanceDB test module (FEAT-542).

Not a test module (no ``test_`` prefix). Imported by
test_lancedb_models/filters/lifecycle/mutations/vector_search/fts_hybrid/
store/multiprocess test modules across TASK-3059/3060/3062/3063/3064/3065/
3067/3068/3069.
"""
from __future__ import annotations

import hashlib
from typing import Any

EMBEDDING_DIMENSION = 8
EMBEDDING_IDENTITY = "lancedb-test-embedding-v1"


def _deterministic_vector(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Deterministic, nonzero, reproducible vector derived from ``text``.

    No downloaded weights, no randomness: same text always maps to the
    same vector, across processes and across runs.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [((digest[i % len(digest)] / 255.0) * 2.0) - 1.0 for i in range(dimension)]
    if not any(values):  # pragma: no cover — astronomically unlikely for sha256
        values[0] = 1.0
    return values


class DeterministicEmbedding:
    """8-D provider with call counters and no downloads.

    The counters are what let dependent tasks prove FTS never constructs
    or invokes a model (spec AC6): assert ``embed_documents_calls`` and
    ``embed_query_calls`` stay at 0 across an FTS-only code path.
    """

    def __init__(self) -> None:
        self.embed_documents_calls = 0
        self.embed_query_calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls += 1
        return [_deterministic_vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls += 1
        return _deterministic_vector(text)


def corpus() -> list[dict[str, Any]]:
    """The 24 fixed documents the spec's acceptance matrix is written against.

    Each entry: ``{"id": str | None, "text": str, "metadata": dict}``.
    ``id`` is ``None`` where the fallback SHA-256 identity path must be
    exercised instead of an explicit id.

    Coverage (spec §4 "Test Data / Fixtures"):
    - child chunks across two sources (source_a / source_b)
    - the lexical identifier ``ZXQ731``
    - a semantic-only neighbor with non-overlapping query text
    - explicit parents (``document_type="parent"``)
    - contradictory parent/chunk markers (``is_chunk=True`` + parent marker)
    - legacy unmarked rows (no parent/chunk metadata at all)
    - null/absent fields
    - quoted filter values (to exercise identifier/literal escaping)
    """
    docs: list[dict[str, Any]] = []

    # 1-2: explicit parent documents, one per source.
    docs.append(
        {
            "id": "parent-a",
            "text": "Source A parent document covering onboarding and billing topics.",
            "metadata": {
                "source": "source_a",
                "source_type": "manual",
                "document_type": "parent",
                "is_full_document": True,
            },
        }
    )
    docs.append(
        {
            "id": "parent-b",
            "text": "Source B parent document covering shipping and returns topics.",
            "metadata": {
                "source": "source_b",
                "source_type": "manual",
                "document_type": "parent",
                "is_full_document": True,
            },
        }
    )

    # 3-10: child chunks under source_a, parent_id=parent-a.
    source_a_chunks = [
        "Billing cycles run monthly and invoices are emailed on the first.",
        "Refunds for source A are processed within five business days.",
        "Onboarding requires a verified email address before first login.",
        "Two-factor authentication is optional for source A accounts.",
        "Source A supports CSV export of billing history on request.",
        "Cancelling a source A subscription takes effect at period end.",
        "Source A billing disputes should reference the invoice number.",
        "Source A account limits reset at the start of each billing cycle.",
    ]
    for i, text in enumerate(source_a_chunks):
        docs.append(
            {
                "id": f"a-chunk-{i}",
                "text": text,
                "metadata": {
                    "source": "source_a",
                    "source_type": "manual",
                    "parent_id": "parent-a",
                    "is_chunk": True,
                },
            }
        )

    # 11-18: child chunks under source_b, parent_id=parent-b.
    source_b_chunks = [
        "Shipping to domestic addresses takes three to five business days.",
        "International shipping for source B is available to select regions.",
        "Returns for source B require an RMA number issued within 30 days.",
        "Source B packages include a prepaid return label by default.",
        "Damaged source B shipments should be reported within 48 hours.",
        "Source B offers expedited shipping for an additional fee.",
        "Tracking numbers for source B ship the same business day.",
        "Source B warehouses are located on the east and west coasts.",
    ]
    for i, text in enumerate(source_b_chunks):
        docs.append(
            {
                "id": f"b-chunk-{i}",
                "text": text,
                "metadata": {
                    "source": "source_b",
                    "source_type": "manual",
                    "parent_id": "parent-b",
                    "is_chunk": True,
                },
            }
        )

    # 19: the lexical identifier row — findable by exact-token FTS, not by
    # semantic similarity to the billing/shipping corpus above.
    docs.append(
        {
            "id": "lexical-zxq731",
            "text": "Internal support reference token ZXQ731 identifies this escalation.",
            "metadata": {"source": "source_a", "source_type": "ticket"},
        }
    )

    # 20: semantic-only neighbor — shares NO query tokens with the lexical
    # row above, but is the nearest semantic neighbor to a query about
    # "escalation reference tracking" (used by hybrid-fusion tests).
    docs.append(
        {
            "id": "semantic-neighbor",
            "text": "A dedicated case identifier is assigned when support issues are escalated.",
            "metadata": {"source": "source_a", "source_type": "ticket"},
        }
    )

    # 21: contradictory parent/chunk markers — is_chunk=True cannot override
    # an explicit parent marker (spec §2 "Filters, Parent Visibility").
    docs.append(
        {
            "id": "contradictory-markers",
            "text": "This row claims to be both a chunk and a parent document.",
            "metadata": {
                "source": "source_a",
                "document_type": "parent",
                "is_chunk": True,
            },
        }
    )

    # 22: legacy unmarked row — no parent/chunk metadata at all; must remain
    # visible by default (missing markers remain visible).
    docs.append(
        {
            "id": "legacy-unmarked",
            "text": "Legacy row imported before parent/chunk markers existed.",
            "metadata": {},
        }
    )

    # 23: null/absent fields — explicit None for a declared field, and one
    # field omitted entirely.
    docs.append(
        {
            "id": None,  # exercises the SHA-256 fallback identity path
            "text": "Row with an explicit null source_type and no parent_id field.",
            "metadata": {"source": "source_a", "source_type": None},
        }
    )

    # 24: quoted filter values — exercises identifier/literal escaping in
    # the metadata filter compiler (TASK-3060).
    docs.append(
        {
            "id": "quoted-value",
            "text": "Row whose source name contains a single quote for escaping tests.",
            "metadata": {"source": "O'Brien's source", "source_type": "manual"},
        }
    )

    assert len(docs) == 24
    return docs
