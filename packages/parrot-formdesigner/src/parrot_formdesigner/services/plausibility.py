"""LLM-assisted answer plausibility checker (FEAT-649 Module 8).

One batched structured-output call judges whether each eligible answer makes sense for its
question. Advisory only: low confidence never blocks; ``on_error`` governs LLM failure only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..core.llm_validation import (
    NOT_EXAMINED_MAX_FIELDS,
    NOT_EXAMINED_UNRENDERABLE,
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,
)
from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..core.voice import is_sensitive

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

_ALWAYS_EXCLUDED = frozenset({FieldType.PASSWORD, FieldType.HIDDEN})
_OPTION_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT})


class PlausibilityItemOut(BaseModel):
    """One verdict as returned by the LLM."""

    field_id: str
    plausible: bool
    confidence: float
    reason: str = ""


class PlausibilityBatch(BaseModel):
    """Structured-output schema sent to the LLM."""

    items: list[PlausibilityItemOut] = Field(default_factory=list)


class PlausibilityBlocked(Exception):
    """Raised only when ``on_error == "block"`` and the LLM is unavailable/timed out/unparsable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _loc(value: Any, locale: str) -> str:
    """Resolve a LocalizedString (str | dict) to text: locale -> base language -> en -> first."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        lang = (locale or "en").split("-")[0]
        for key in (locale, lang, "en"):
            if key in value and value[key] is not None:
                return str(value[key])
        for item in value.values():
            if item is not None:
                return str(item)
        return ""
    return str(value)


def _is_answered(value: Any) -> bool:
    """None, blank strings, empty list/dict are unanswered."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def select_fields(
    form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
) -> tuple[list[FormField], dict[str, str]]:
    """Partition eligible fields into those to send and those the cap dropped.

    Args:
        form: The form whose fields are being judged.
        scalars: Submitted answers by field id.
        cfg: The form's LLM validation settings.
        only: When given, restrict consideration to these field ids.

    Returns:
        ``(picked, not_examined)`` — ``picked`` is the ``cfg.max_fields``-capped,
        required-first list; ``not_examined`` maps every field id cut by that cap
        to ``NOT_EXAMINED_MAX_FIELDS``.
    """
    excluded = set(cfg.exclude_field_types) | _ALWAYS_EXCLUDED
    picked: list[FormField] = []
    for field in form.iter_fields_recursive():
        if only is not None and field.field_id not in only:
            continue
        if not llm_validation_enabled(form, field):
            continue
        if field.read_only or field.field_type in excluded or is_sensitive(field):
            continue
        if not _is_answered(scalars.get(field.field_id)):
            continue
        picked.append(field)
    picked.sort(key=lambda f: 0 if f.required else 1)
    return picked[: cfg.max_fields], {f.field_id: NOT_EXAMINED_MAX_FIELDS for f in picked[cfg.max_fields :]}


def eligible_fields(
    form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
) -> list[FormField]:
    """Fields to send: enabled, answered, not read_only, type not excluded, not sensitive.

    Ordered required-first (stable), cut at ``cfg.max_fields``; ``only`` restricts to a subset.
    Thin wrapper over :func:`select_fields` — call that one to learn what the cap cut.
    """
    return select_fields(form, scalars, cfg, only=only)[0]


def _bool_text(value: bool, locale: str) -> str:
    """Localise a boolean answer."""
    lang = (locale or "en").split("-")[0]
    if lang == "es":
        return "sí" if value else "no"
    return "yes" if value else "no"


def _truncate(text: str, limit: int | None) -> str:
    """Return ``text`` cut to at most ``limit`` characters, ending in ``…`` when cut.

    The marker replaces the final kept character rather than extending past
    ``limit``, so the result is never longer than ``limit``. ``None`` (or a
    non-positive limit) leaves ``text`` untouched.
    """
    if limit is None or limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _answer_text(
    field: FormField, value: Any, locale: str, labels: dict[str, str], *, max_chars: int | None = None
) -> str | None:
    """Render an answer as text; ``None`` when it cannot be rendered safely (dicts).

    ``max_chars`` caps the rendered result (``None`` = uncapped).
    """
    if isinstance(value, dict):
        return None
    if isinstance(value, bool):
        return _truncate(_bool_text(value, locale), max_chars)
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, (dict, list, tuple)):
                return None
            if isinstance(item, bool):
                parts.append(_bool_text(item, locale))
            else:
                key = str(item)
                parts.append(labels.get(key, key) if field.field_type in _OPTION_TYPES else key)
        return _truncate(", ".join(parts), max_chars)
    key = str(value)
    return _truncate(labels.get(key, key) if field.field_type in _OPTION_TYPES else key, max_chars)


def build_items(
    form: FormSchema,
    fields: list[FormField],
    scalars: dict[str, Any],
    *,
    locale: str,
    max_answer_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Prompt items: field_id, label, description, hint, field_type, options (labels), answer (text).

    ``max_answer_chars`` caps each rendered answer (``None`` = uncapped, the
    pre-FEAT-737 behaviour kept for direct callers).
    """
    items: list[dict[str, Any]] = []
    for field in fields:
        labels = {opt.value: _loc(opt.label, locale) for opt in (field.options or [])}
        answer = _answer_text(field, scalars.get(field.field_id), locale, labels, max_chars=max_answer_chars)
        if answer is None:
            continue
        item: dict[str, Any] = {
            "field_id": field.field_id,
            "label": _loc(field.label, locale) or field.field_id,
            "description": _loc(field.description, locale),
            "hint": _loc(getattr(field, "hint", None), locale),
            "field_type": field.field_type.value if hasattr(field.field_type, "value") else str(field.field_type),
            "answer": answer,
        }
        if field.field_type in _OPTION_TYPES and labels:
            item["options"] = [lbl for lbl in labels.values() if lbl]
        items.append(item)
    return items


_SYSTEM_PROMPT = (
    "You review answers to a form. For each item decide whether the answer plausibly responds to "
    "the question (not noise, not an unrelated phrase). Return one verdict per field_id with a "
    "confidence between 0 and 1 and a short reason. Do not judge correctness of facts."
)


class AnswerPlausibilityChecker:
    """Run one batched plausibility check for a form submission."""

    def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None:
        self._client = client
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def check(
        self, form: FormSchema, scalars: dict[str, Any], *, locale: str, fields: set[str] | None = None
    ) -> PlausibilityReport:
        """Return the report; raise PlausibilityBlocked only under ``on_error == "block"``.

        The report's ``not_examined`` names every eligible field the model never
        saw — cut by ``cfg.max_fields`` or dropped as unrenderable — so a
        ``status="ok"`` report can no longer over-claim coverage. ``items`` and
        ``not_examined`` are always disjoint.
        """
        cfg = self.config
        targets, capped = select_fields(form, scalars, cfg, only=fields)
        if not targets:
            return PlausibilityReport(
                status="ok", threshold=cfg.threshold, model=cfg.model, items={}, not_examined=capped
            )
        if self._client is None:
            return self._fail("no LLM client configured")
        items = build_items(form, targets, scalars, locale=locale, max_answer_chars=cfg.max_answer_chars)
        if not items:
            # Every eligible answer was unrenderable: an "ok" report with no items would
            # be indistinguishable from a clean pass, so name each one explicitly.
            self.logger.warning(
                "plausibility: all %d eligible answers for form %s were unrenderable", len(targets), form.form_id
            )
            return PlausibilityReport(
                status="ok",
                threshold=cfg.threshold,
                model=cfg.model,
                items={},
                not_examined=capped | {f.field_id: NOT_EXAMINED_UNRENDERABLE for f in targets},
            )
        prompt = json.dumps({"locale": locale, "items": items}, ensure_ascii=False)
        kwargs: dict[str, Any] = {"system_prompt": _SYSTEM_PROMPT, "structured_output": PlausibilityBatch}
        if cfg.model:
            kwargs["model"] = cfg.model
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(self._client.ask(prompt, **kwargs), timeout=cfg.timeout_s)
            batch = self._parse(response)
        except Exception as exc:  # timeout, provider error, unparsable output
            self.logger.warning("plausibility check failed for form %s: %s", form.form_id, type(exc).__name__)
            return self._fail(f"llm_error: {type(exc).__name__}")
        resolved_model, provider, usage = self._identity(response)
        if not resolved_model:
            # FEAT-732 AC12: a parseable answer nobody can attribute is not a success.
            self.logger.warning("plausibility: response for form %s carries no model identity", form.form_id)
            return self._fail("llm_error: unidentified_model")
        latency_ms = int((time.monotonic() - started) * 1000)
        known = {f.field_id for f in targets}
        sent = {item["field_id"] for item in items}
        verdicts: dict[str, PlausibilityVerdict] = {}
        for out in batch.items:
            # Gate on what was actually SENT, not merely on what was eligible: a verdict
            # for a field the model never saw is unattributable, and keeping it would also
            # put the same id in both `items` and `not_examined` (FEAT-737 AC5).
            if out.field_id not in sent:
                self.logger.warning("plausibility: dropping unsent field_id %r from LLM output", out.field_id)
                continue
            confidence = out.confidence
            if confidence != confidence:  # NaN
                confidence = 0.0
            confidence = max(0.0, min(1.0, float(confidence)))
            verdicts[out.field_id] = PlausibilityVerdict(
                plausible=out.plausible,
                confidence=confidence,
                reason=_truncate(out.reason or "", cfg.max_reason_chars),
            )
        not_examined = capped | dict.fromkeys(known - sent, NOT_EXAMINED_UNRENDERABLE)
        return PlausibilityReport(
            status="ok",
            threshold=cfg.threshold,
            model=cfg.model,
            resolved_model=resolved_model,
            provider=provider,
            usage=usage,
            latency_ms=latency_ms,
            items=verdicts,
            not_examined=not_examined,
        )

    def _parse(self, response: Any) -> PlausibilityBatch:
        """Accept AIMessage.structured_output / .output as a PlausibilityBatch, dict or JSON string."""
        for attr in ("structured_output", "output"):
            candidate = getattr(response, attr, None)
            if candidate is None:
                continue
            if isinstance(candidate, PlausibilityBatch):
                return candidate
            try:
                if isinstance(candidate, dict):
                    return PlausibilityBatch.model_validate(candidate)
                if isinstance(candidate, (str, bytes)):
                    return PlausibilityBatch.model_validate_json(candidate)
                if isinstance(candidate, BaseModel):
                    return PlausibilityBatch.model_validate(candidate.model_dump())
            except ValueError:
                continue
        raise ValueError("unparsable plausibility output")

    @staticmethod
    def _identity(response: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Extract (resolved_model, provider, usage) from an AIMessage-shaped response.

        Reads ``response.model`` / ``.provider`` / ``.usage`` — required fields on
        AIMessage (responses.py:138-139,143). Tolerant of test doubles: a missing
        or empty attribute yields ``None``, which ``check()`` then treats as an LLM
        failure rather than an unattributable success.
        """
        model = getattr(response, "model", None)
        provider = getattr(response, "provider", None)
        raw_usage = getattr(response, "usage", None)
        usage: dict[str, Any] | None = None
        if isinstance(raw_usage, BaseModel):
            usage = raw_usage.model_dump(mode="json")
        elif isinstance(raw_usage, dict):
            usage = dict(raw_usage)
        return (str(model) if model else None, str(provider) if provider else None, usage)

    def _fail(self, reason: str) -> PlausibilityReport:
        """Map an LLM failure through ``on_error``."""
        if self.config.on_error == "block":
            raise PlausibilityBlocked(reason)
        return PlausibilityReport(
            status="skipped", reason=reason, threshold=self.config.threshold, model=self.config.model
        )
