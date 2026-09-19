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

from pydantic import ValidationError

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

#: Separator joined between identity components before hashing. Chosen
#: because it cannot occur inside a scope id, fingerprint, or decision text
#: (ASCII "unit separator", never produced by ordinary text input).
_ID_SEPARATOR = "\x1f"


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
    dumped = record.model_dump(mode="json")
    dumped.pop("content_fingerprint", None)
    dumped.pop("revision", None)
    dumped.pop("review_history", None)
    evidence = dumped.get("evidence") or []
    dumped["evidence"] = sorted(
        evidence,
        key=lambda item: (item["rel_path"], item["start_line"], item["end_line"], item["source_sha1"]),
    )
    payload = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha1(payload)


def review_fingerprint(record: DecisionRecord) -> str:
    """Narrow digest for ``ReviewEvent.before_sha1`` / ``after_sha1``.

    Covers title, context, decision, consequences, observations, hypotheses
    and ``review_status`` only — deliberately not the audit history, which
    would make the hash self-referential (spec §2 ``ReviewEvent``).
    """
    payload = json.dumps(
        [
            record.title,
            record.context,
            record.decision,
            record.consequences,
            record.observations,
            record.hypotheses,
            record.review_status,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _sha1(payload)


def normalize_rel_path(rel_path: str) -> str:
    """POSIX-normalize a repository-relative path for identity hashing."""
    normalized = rel_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    return normalized


def documented_decision_id(rel_path: str) -> str:
    """Stable id of an imported ADR: ``adr:doc:<sha1(normalized path)>``."""
    return f"adr:doc:{_sha1(normalize_rel_path(rel_path))}"


def candidate_decision_id(scope_id: str, evidence_fingerprint: str, prompt_version: int, decision_text: str) -> str:
    """Stable id of a generated candidate: ``adr:candidate:<sha1(...)>``.

    The same scope and evidence snapshot therefore yield the same id, which
    is what lets a rerun return the existing (possibly reviewed) candidate
    instead of overwriting it (spec §2, AC6).
    """
    normalized_decision = " ".join(decision_text.split())
    payload = _ID_SEPARATOR.join([scope_id, evidence_fingerprint, str(prompt_version), normalized_decision])
    return f"adr:candidate:{_sha1(payload)}"


def status_labels(record: DecisionRecord) -> str:
    """Render the mandatory ``[ORIGIN / STATUS]`` prefix.

    Documented records show their source status; inferred records show their
    review status, so a generic wiki search can never present a candidate as
    an unlabeled decision (spec §2, AC3, AC9).
    """
    if record.origin == "documented":
        return f"[DOCUMENTED / {record.source_status.upper()}]"
    return f"[INFERRED / {record.review_status.upper()}]"


def render_markdown(record: DecisionRecord) -> str:
    """Readable rendering appended after the envelope (and used by `adr export`)."""
    labels = status_labels(record)
    lines = [f"# {labels} {record.title}".strip(), ""]
    lines.append("## Context")
    lines.append(record.context)
    lines.append("")
    lines.append("## Decision")
    lines.append(record.decision)
    lines.append("")
    lines.append("## Consequences")
    lines.append(record.consequences)
    if record.observations:
        lines.append("")
        lines.append("## Observations")
        lines.extend(f"- {observation}" for observation in record.observations)
    if record.hypotheses:
        lines.append("")
        lines.append("## Hypotheses")
        lines.extend(f"- {hypothesis}" for hypothesis in record.hypotheses)
    if record.evidence:
        lines.append("")
        lines.append("## Citations")
        lines.extend(f"- {ref.rel_path}:{ref.start_line}-{ref.end_line}" for ref in record.evidence)
    return "\n".join(lines)


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
    concept_id = page.get("concept_id")
    if page.get("category") != ADR_CATEGORY:
        raise DecisionError(
            ADR_SCHEMA_UNSUPPORTED,
            f"page category {page.get('category')!r} is not {ADR_CATEGORY!r}",
            decision_id=concept_id,
        )
    body = page.get("body") or ""
    parts = body.split("\n", 2)
    if len(parts) < 2 or parts[0] != ENVELOPE_MARKER:
        raise DecisionError(
            ADR_SCHEMA_UNSUPPORTED,
            "missing or unsupported ADR envelope marker",
            decision_id=concept_id,
        )
    try:
        payload = json.loads(parts[1])
        return DecisionRecord.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DecisionError(
            ADR_SCHEMA_UNSUPPORTED,
            f"failed to decode ADR envelope: {exc}",
            decision_id=concept_id,
        ) from exc
