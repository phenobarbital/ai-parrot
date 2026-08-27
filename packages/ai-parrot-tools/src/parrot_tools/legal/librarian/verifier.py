"""Deterministic span existence gate (FEAT-449 §3 M4, R2/R4).

The governing invariant, verbatim:

    The system cannot assert anything about the corpus without a
    verifiable span reference; without a citation, the answer is
    "no encontré".

``SpanVerifier`` is pure code — no LLM, no network — fully unit-testable.
It is the ONLY place that turns a stochastic ``DraftAnswer`` into a sealed
``LegalAnswer``: every ``DraftSpan`` is checked against the retrieval set
that actually fed the prompt, and any span that cannot be proven to exist
(wrong id, tampered/drifted payload, or a quote that isn't verbatim) is
pruned before it can reach the caller. Fabrication cannot survive this
gate by construction.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from parrot_tools.legal.boe.hashing import HASH_NORM_VERSION, seal_hash

from .models import (
    ConflictNote,
    DraftAnswer,
    DraftSpan,
    LegalAnswer,
    PayloadEntry,
    ReadingNote,
    SpanRef,
    SuppressionRecord,
    span_key,
)


class SpanVerifier:
    """Existence gate (skeleton §5.1/§5.3; FEAT-449 spec §3 M4).

    Verification order per ``DraftSpan`` — first failure wins, reason is
    exact:

    1. ``payload_key not in retrieval_set`` -> prune ``"span_not_found"``
    2. ``seal_hash(entry.payload) != entry.content_hash`` -> prune
       ``"hash_mismatch"`` (defence in depth: store tampered/drifted
       since ingest)
    3. ``idx = entry.payload.find(span.quote); idx == -1`` -> prune
       ``"quote_mismatch"``; else ``start, end = idx, idx + len(quote)``
       — the FIRST occurrence is used when a quote appears more than
       once in a payload (documented here, not solved: the citation is
       correct either way, only the offset choice is arbitrary).

    A ``DraftReadingNote`` that loses every one of its spans is
    suppressed as a whole (``suppressed_count += 1``, one
    ``SuppressionRecord`` appended with ``claimed_anchors`` = every
    originally-claimed ``payload_key``): its ``reason`` is the single
    span-level failure reason when the note cited exactly one span (or
    every failing span shares the same reason), and ``"anchor_lost"``
    otherwise. A ``DraftConflictNote`` with either side pruned is
    dropped and recorded with reason ``"anchor_lost"`` (spec §3 M4,
    verbatim). ``reading_order`` is filtered to surviving payload keys
    silently — pointers, not claims. Surviving spans become sealed
    ``SpanRef``s; the ``dossier`` is the deduplicated (by span key) list
    of surviving ``SpanRef``s in first-seen order. An empty dossier is a
    first-class "no encontré": ``not_found`` is guaranteed non-empty,
    ``reading_guide``/``conflicts`` are empty, and no exception is
    raised.
    """

    def verify(
        self,
        draft: DraftAnswer,
        retrieval_set: dict[str, PayloadEntry],
        *,
        as_of: date,
        materias: list[str],
        execution_id: str,
        user_id: str | None = None,
    ) -> tuple[LegalAnswer, list[SuppressionRecord]]:
        """Verify a draft answer against the retrieval set and seal it.

        Args:
            draft: The LLM-facing structured output to verify.
            retrieval_set: Every payload the prompt enumerated, keyed by
                ``payload_key`` — the ONLY payloads a citation may
                reference.
            as_of: The date used to resolve retrieval (stated back on
                the returned ``LegalAnswer``).
            materias: Materias searched (stated back).
            execution_id: Identifier for this librarian flow execution,
                threaded into every ``SuppressionRecord``.
            user_id: User attributed to the execution, when known.

        Returns:
            A tuple of the sealed ``LegalAnswer`` and every
            ``SuppressionRecord`` produced while verifying it (for the
            caller to persist via ``SuppressionLog``).
        """
        suppressions: list[SuppressionRecord] = []
        suppressed_count = 0
        dossier_by_key: dict[str, SpanRef] = {}
        surviving_payload_keys: set[str] = set()

        def _verify_one(span: DraftSpan) -> tuple[SpanRef | None, str | None]:
            entry = retrieval_set.get(span.payload_key)
            if entry is None:
                return None, "span_not_found"
            if seal_hash(entry.payload) != entry.content_hash:
                return None, "hash_mismatch"
            idx = entry.payload.find(span.quote)
            if idx == -1:
                return None, "quote_mismatch"
            start, end = idx, idx + len(span.quote)
            ref = SpanRef(
                kind="articulo",
                id=entry.articulo_key,
                version_n=entry.version_n,
                start=start,
                end=end,
                quote=span.quote,
                content_hash=entry.content_hash,
                hash_norm_version=HASH_NORM_VERSION,
                title=entry.title,
                url=entry.url,
                as_of=entry.as_of,
                basis=entry.basis,
            )
            return ref, None

        def _record(reason: str, suppressed_text: str, claimed_anchors: list[str]) -> None:
            nonlocal suppressed_count
            suppressed_count += 1
            suppressions.append(
                SuppressionRecord(
                    execution_id=execution_id,
                    suppressed_text=suppressed_text,
                    claimed_anchors=claimed_anchors,
                    reason=reason,
                    user_id=user_id,
                    created_at=datetime.now(UTC),
                )
            )

        # ── Reading guide ──
        surviving_notes: list[ReadingNote] = []
        for note in draft.reading_guide:
            survivors: list[SpanRef] = []
            failure_reasons: list[str] = []
            for span in note.spans:
                ref, reason = _verify_one(span)
                if ref is not None:
                    survivors.append(ref)
                    surviving_payload_keys.add(span.payload_key)
                else:
                    failure_reasons.append(reason or "span_not_found")

            if not survivors:
                reason = (
                    failure_reasons[0]
                    if failure_reasons and len(set(failure_reasons)) == 1
                    else "anchor_lost"
                )
                _record(
                    reason,
                    note.text,
                    [s.payload_key for s in note.spans],
                )
                continue

            for ref in survivors:
                dossier_by_key.setdefault(span_key(ref), ref)
            surviving_notes.append(
                ReadingNote(
                    text=note.text,
                    spans=[span_key(ref) for ref in survivors],
                    basis=note.basis,
                )
            )

        # ── Conflicts ──
        surviving_conflicts: list[ConflictNote] = []
        for conflict in draft.conflicts:
            ref_a, _reason_a = _verify_one(conflict.span_a)
            ref_b, _reason_b = _verify_one(conflict.span_b)
            if ref_a is None or ref_b is None:
                _record(
                    "anchor_lost",
                    conflict.note,
                    [conflict.span_a.payload_key, conflict.span_b.payload_key],
                )
                continue
            surviving_payload_keys.add(conflict.span_a.payload_key)
            surviving_payload_keys.add(conflict.span_b.payload_key)
            dossier_by_key.setdefault(span_key(ref_a), ref_a)
            dossier_by_key.setdefault(span_key(ref_b), ref_b)
            surviving_conflicts.append(
                ConflictNote(
                    span_a=span_key(ref_a),
                    span_b=span_key(ref_b),
                    note=conflict.note,
                )
            )

        # ── reading_order: filtered silently to surviving payload keys ──
        reading_order = [key for key in draft.reading_order if key in surviving_payload_keys]

        dossier = list(dossier_by_key.values())
        not_found = list(draft.not_found)
        if not dossier and not not_found:
            materias_str = ", ".join(materias) if materias else "(sin materia especificada)"
            not_found = [
                (
                    f"No encontré resultados en el corpus BOE para materias "
                    f"{materias_str} a fecha {as_of.isoformat()}."
                )
            ]

        answer = LegalAnswer(
            as_of=as_of,
            materias=materias,
            dossier=dossier,
            reading_order=reading_order if dossier else [],
            conflicts=surviving_conflicts if dossier else [],
            reading_guide=surviving_notes if dossier else [],
            not_found=not_found,
            suppressed_count=suppressed_count,
        )
        return answer, suppressions
