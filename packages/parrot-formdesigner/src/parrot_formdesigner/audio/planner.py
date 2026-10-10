"""Visible-plan computation for audio form sessions (FEAT-649, Module 5)."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from ..core.schema import FormSchema, FormSubsection, walk_fields
from ..core.types import FieldType
from ..core.voice import VoiceFormConfig
from ..core.voice_answer import unwrap_voice
from ..services.rule_evaluator import RuleEvaluator, RuleResolution
from .models import AudioAnswer, AudioFormManifest


class PlanDelta(BaseModel):
    """What changed between two re-plans."""

    order: list[str] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    required_changed: dict[str, bool] = Field(default_factory=dict)
    hidden_by_cap: list[str] = Field(default_factory=list)
    entered_section: str | None = None
    computed: dict[str, Any] = Field(default_factory=dict)


class QuestionPlanner:
    """Compute the visible, capped question plan from the manifest and RuleEvaluator."""

    def __init__(self, form: FormSchema, manifest: AudioFormManifest, cfg: VoiceFormConfig) -> None:
        self.form = form
        self.manifest = manifest
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self._order: list[str] = [q.field_id for q in manifest.questions]
        self._parent: dict[str, str] = {}  # GROUP child field_id -> top-level GROUP field_id
        self._section: dict[str, str] = {}  # field_id -> str(section_uid)
        for section in form.sections:
            for item in section.fields:
                # Q1 (option a, 2026-10-10): FormSubsection.depends_on is ignored — HTTP parity;
                # RuleEvaluator untouched. See spec section 8 Q1.
                fields = item.fields if isinstance(item, FormSubsection) else [item]
                for top in fields:
                    for f in walk_fields([top]):
                        self._section[f.field_id] = str(section.section_uid)
                        if f is not top and top.field_type == FieldType.GROUP:
                            self._parent[f.field_id] = top.field_id
        self._resolution: RuleResolution | None = None
        self._prev_visible: set[str] = set(self._order)
        self._prev_required: dict[str, bool] = {}

    def _rule_key(self, field_id: str) -> str:
        """Key into RuleResolution: GROUP children inherit their parent's entry (owner decision)."""
        return self._parent.get(field_id, field_id)

    def section_of(self, field_id: str) -> str | None:
        """Section uid (str) owning ``field_id``."""
        return self._section.get(field_id)

    def effective_required(self, field_id: str) -> bool:
        """Dynamic RuleResolution.required (S1a); falls back to the manifest flag before the first replan."""
        if self._resolution is not None:
            key = self._rule_key(field_id)
            if key in self._resolution.required:
                return bool(self._resolution.required[key])
        q = next((q for q in self.manifest.questions if q.field_id == field_id), None)
        return bool(q.required) if q else False

    async def replan(
        self,
        answers: dict[str, AudioAnswer],
        *,
        locale: str,
        resolution: RuleResolution | None = None,
    ) -> tuple[list[str], PlanDelta]:
        """Re-run RuleEvaluator.resolve() and return (plan, delta); required fields always survive the cap."""
        if resolution is None:
            scalars = unwrap_voice({fid: a.value for fid, a in answers.items()})
            resolution = await RuleEvaluator().resolve(self.form, scalars, locale=locale)
        self._resolution = resolution
        visible = [fid for fid in self._order if resolution.visible.get(self._rule_key(fid), True)]
        plan, hidden_by_cap = self._apply_cap(visible)
        required_now = {fid: self.effective_required(fid) for fid in plan}
        delta = PlanDelta(
            order=plan,
            hidden=[fid for fid in self._order if fid in self._prev_visible and fid not in visible],
            cleared=sorted(
                set(resolution.cleared) | {fid for fid in answers if fid in self._order and fid not in visible}
            ),
            required_changed={fid: r for fid, r in required_now.items() if self._prev_required.get(fid, r) != r},
            hidden_by_cap=hidden_by_cap,
            computed=dict(resolution.computed),
        )
        self._prev_visible, self._prev_required = set(visible), required_now
        return plan, delta

    def _apply_cap(self, visible: list[str]) -> tuple[list[str], list[str]]:
        """Keep every required field; fill remaining slots with optional ones in order."""
        cap = self.cfg.max_questions
        if cap is None or len(visible) <= cap:
            return visible, []
        required = [fid for fid in visible if self.effective_required(fid)]
        if len(required) >= cap:
            if len(required) > cap:
                self.logger.warning("required_exceeds_cap: %d required > max_questions=%d", len(required), cap)
            keep = set(required)
        else:
            keep = set(required)
            for fid in visible:
                if len(keep) >= cap:
                    break
                keep.add(fid)
        return [f for f in visible if f in keep], [f for f in visible if f not in keep]

    def next_cursor(self, plan: list[str], answers: dict[str, AudioAnswer]) -> str | None:
        """First field_id in plan without an accepted answer; None -> review."""
        return next((fid for fid in plan if fid not in answers), None)

    def previous(self, plan: list[str], history: list[str], to_field_id: str | None) -> str | None:
        """Target of a go-back: explicit field if planned, else the latest history entry still in plan."""
        if to_field_id is not None and to_field_id in plan:
            return to_field_id
        current = history[-1] if history else None
        for fid in reversed(history):
            if fid != current and fid in plan:
                return fid
        return None
