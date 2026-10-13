"""Design-time voice optimiser (FEAT-649): proposes hints/prompts, never writes."""

from __future__ import annotations

import difflib
import json
import logging
import uuid
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, Field

from ..audio.commands import command_option_collisions
from ..audio.narration.engine import Narrator
from ..audio.narration.lexicon import Lexicon, normalize
from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..core.voice import VoiceFormConfig
from ..renderers.audio import AudioFormRenderer

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

logger = logging.getLogger(__name__)
_FUZZY_COLLISION = 0.8
_EXCLUDED_TYPES = {FieldType.PASSWORD, FieldType.HIDDEN}


def _text(value: object) -> str:
    """Flatten a LocalizedString to one plain string."""
    if isinstance(value, dict):
        return str(next(iter(value.values()), ""))
    return str(value or "")


class VoiceHintProposal(BaseModel):
    """One proposal for one field (staging only)."""

    field_uid: uuid.UUID
    hint: dict[str, str]
    prompt: str | None = None
    enumerate: str = "auto"
    llm_validation: bool | None = None
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)


class _ProposalBatch(BaseModel):
    """Structured-output schema sent to the LLM."""

    proposals: list[VoiceHintProposal]


class VoiceOptimizer:
    """Proposes voice metadata with one structured-output LLM call; never mutates the form."""

    def __init__(self, client: "AbstractClient", narrator_factory: Callable[[str], Narrator]) -> None:
        self._client = client
        self._narrator_factory = narrator_factory
        self.logger = logger

    async def propose(
        self, form: FormSchema, *, locale: str, fields: set[str] | None, style: str, max_hint_words: int
    ) -> tuple[list[VoiceHintProposal], dict[str, str]]:
        """Return (proposals, narration_preview keyed by field_id). NEVER writes (owner decision)."""
        prompt = self._build_prompt(form, locale=locale, fields=fields, style=style, max_hint_words=max_hint_words)
        response = await self._client.ask(prompt, structured_output=_ProposalBatch)
        output = getattr(response, "output", response)
        if isinstance(output, str):
            try:
                output = _ProposalBatch.model_validate_json(output)
            except ValueError as exc:
                self.logger.warning("voice optimiser returned unparseable output: %s", exc)
                output = None
        elif isinstance(output, dict):
            try:
                output = _ProposalBatch.model_validate(output)
            except ValueError as exc:
                self.logger.warning("voice optimiser returned invalid output: %s", exc)
                output = None
        raw = list(getattr(output, "proposals", None) or [])
        by_uid = {f.field_uid: f for f in form.iter_fields_recursive()}
        proposals: list[VoiceHintProposal] = []
        for prop in raw:
            if prop.field_uid not in by_uid:
                self.logger.warning("dropping proposal for unknown field_uid %s", prop.field_uid)
                continue
            for loc, text in prop.hint.items():
                if len(text.split()) > max_hint_words:
                    prop.warnings.append(f"hint[{loc}] exceeds {max_hint_words} words")
            proposals.append(prop)
        return proposals, self._preview(form, proposals, locale=locale)

    def _build_prompt(
        self, form: FormSchema, *, locale: str, fields: set[str] | None, style: str, max_hint_words: int
    ) -> str:
        """Per field: label, description, type, option labels; never PASSWORD/HIDDEN fields."""
        listing: list[dict] = []
        for field in form.iter_fields_recursive():
            if field.field_type in _EXCLUDED_TYPES:
                continue
            if fields is not None and field.field_id not in fields:
                continue
            entry: dict = {
                "field_uid": str(field.field_uid),
                "field_id": field.field_id,
                "type": field.field_type.value if hasattr(field.field_type, "value") else str(field.field_type),
                "label": _text(field.label),
                "description": _text(field.description),
            }
            if field.options:
                entry["options"] = [_text(o.label) for o in field.options]
            listing.append(entry)
        return (
            "You help a form author prepare a form for voice (spoken) interaction.\n"
            f"For each field below propose a short spoken hint (style: {style}, at most {max_hint_words} words) "
            f"in locale '{locale}', as a mapping locale -> text. Optionally propose a spoken prompt, an "
            "enumeration mode (auto|always|never|count_only) and whether llm_validation should be enabled. "
            "Echo each field_uid exactly. Add a one-line rationale. Proposals are reviewed by the author.\n"
            f"Form: {_text(form.title)}\nFields:\n{json.dumps(listing, ensure_ascii=False, indent=1)}"
        )

    def _preview(self, form: FormSchema, proposals: list[VoiceHintProposal], *, locale: str) -> dict[str, str]:
        """Render the narration text each field WOULD get with its proposal applied (in-memory copy only)."""
        narrator = self._narrator_factory(locale)
        cfg = form.voice or VoiceFormConfig()
        copy = form.model_copy(deep=True)
        by_uid: dict[uuid.UUID, FormField] = {f.field_uid: f for f in copy.iter_fields_recursive()}
        for prop in proposals:
            field = by_uid.get(prop.field_uid)
            if field is None:
                continue
            field.hint = dict(prop.hint)
            if prop.llm_validation is not None:
                field.llm_validation = prop.llm_validation
            voice = dict((field.meta or {}).get("voice") or {})
            if prop.prompt:
                voice["prompt"] = prop.prompt
            voice["enumerate"] = prop.enumerate
            field.meta = {**(field.meta or {}), "voice": voice}
        wanted = {p.field_uid for p in proposals}
        uid_to_id = {uid: f.field_id for uid, f in by_uid.items()}
        wanted_ids = {uid_to_id[u] for u in wanted}
        preview: dict[str, str] = {}
        for q in AudioFormRenderer().split_into_questions(copy, locale=locale):
            if q.field_id in wanted_ids and q.voice_meta is not None:
                preview[q.field_id] = narrator.plan_question(q, cfg, q.voice_meta).text
        return preview

    def self_test(self, form: FormSchema, lexicon: Lexicon) -> list[str]:
        """Deterministic, no LLM: option-label fuzzy collisions (>= 0.8) and option-vs-command collisions."""
        findings: list[str] = []
        for field in form.iter_fields_recursive():
            if not field.options or field.field_type in _EXCLUDED_TYPES:
                continue
            labels = [(opt.value, normalize(_text(opt.label), lexicon)) for opt in field.options]
            for i, (va, la) in enumerate(labels):
                for vb, lb in labels[i + 1 :]:
                    if difflib.SequenceMatcher(None, la, lb).ratio() >= _FUZZY_COLLISION:
                        findings.append(f"{field.field_id}: options '{va}' and '{vb}' sound alike")
            options = [{"value": o.value, "label": _text(o.label)} for o in field.options]
            for label, command in command_option_collisions(options, lexicon):
                findings.append(f"{field.field_id}: option '{label}' collides with command {command.value}")
        return findings
