"""Deterministic narration for audio forms (FEAT-649, Module 3)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from ...core.types import FieldType
from ...core.voice import FieldVoiceMeta, VoiceFormConfig
from ..models import AudioQuestion, NarrationPlan, ReviewItemData
from .lexicon import locale_chain

_TEMPLATES_DIR = Path(__file__).parent / "templates"

NARRATION_KEYS: frozenset[str] = frozenset(
    {
        "question",
        "question_with_prompt",
        "hint_bridge",
        "options_intro",
        "option_item",
        "options_count_only",
        "boolean_prompt",
        "required_mark",
        "confirm_readback",
        "confirm_option",
        "no_match",
        "required_reject",
        "skipped",
        "section_intro",
        "computed_statement",
        "review_intro",
        "review_item",
        "review_item_skipped",
        "review_all_correct",
        "review_edit_ack",
        "plausibility_flag",
        "plausibility_keep",
        "submitted",
        "resume_welcome",
        "command_ack_repeat",
        "command_ack_back",
        "command_ack_skip",
        "command_ack_help",
        "command_ack_stop",
        "command_ack_next",
        "command_ack_send",
        "command_ack_change",
    }
)
# Keys pre-synthesised at start_session as ``sys:<key>`` (no per-question variables).
_SYSTEM_KEYS: tuple[str, ...] = (
    "no_match",
    "required_reject",
    "skipped",
    "review_all_correct",
    "submitted",
    "resume_welcome",
    "command_ack_repeat",
    "command_ack_back",
    "command_ack_skip",
    "command_ack_help",
    "command_ack_stop",
    "command_ack_next",
    "command_ack_send",
    "command_ack_change",
)
_PROMPT_WHITELIST = ("label", "hint", "section", "n", "total")
_SELECT_TYPES = frozenset(
    {
        FieldType.SELECT.value,
        FieldType.MULTI_SELECT.value,
        FieldType.DYNAMIC_SELECT.value,
    }
)
_HIDDEN = "[hidden]"


class _VerbatimDict(dict):
    """format_map mapping that leaves unknown placeholders verbatim."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_author_prompt(prompt: str, *, label: str, hint: str, section: str, n: int, total: int) -> str:
    """Render an author prompt with ``str.format_map`` over a whitelist (never Jinja).

    Unknown placeholders are rendered verbatim; malformed format strings return the prompt unchanged.
    """
    values = _VerbatimDict(label=label, hint=hint, section=section, n=n, total=total)
    try:
        return prompt.format_map(values)
    except (ValueError, IndexError, KeyError, AttributeError, TypeError):
        # `{0}`, `{label.x}`, `{label[0]}`, unbalanced braces: return the raw author prompt.
        return prompt


class Narrator:
    """Render narration templates for one locale (sandboxed Jinja2, StrictUndefined)."""

    def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None:
        """Load ``<locale>/narration.yaml`` with fallback ``es-MX → es → en``."""
        self.logger = logging.getLogger(__name__)
        self.locale = locale
        self._dir = templates_dir or _TEMPLATES_DIR
        self._env = ImmutableSandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        self._templates: dict[str, str] = {}
        for loc in reversed(locale_chain(locale)):  # en first, most specific last wins
            path = self._dir / loc / "narration.yaml"
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self._templates.update(data.get("templates") or {})
        missing = NARRATION_KEYS - self._templates.keys()
        if missing:
            self.logger.warning("Narrator(%s): missing template keys %s", locale, sorted(missing))

    def render(self, key: str, **ctx: Any) -> str:
        """Render one template key; raises KeyError for an unknown key."""
        if key not in NARRATION_KEYS or key not in self._templates:
            raise KeyError(key)
        return self._env.from_string(self._templates[key]).render(**ctx).strip()

    def system_phrases(self) -> dict[str, str]:
        """``sys:*`` keys pre-synthesised at start_session."""
        return {f"sys:{k}": self.render(k) for k in _SYSTEM_KEYS}

    def _options_text(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> str | None:
        """Build the options narration for ``q`` or None when nothing is narrated."""
        if q.field_type == FieldType.BOOLEAN.value:
            return self.render("boolean_prompt")
        if q.field_type not in _SELECT_TYPES or meta.enumerate == "never":
            return None
        options = [o for o in (q.options or []) if not o.get("disabled")]
        if not options:
            return None
        if meta.enumerate == "count_only":
            return self.render("options_count_only", count=len(options))
        if meta.enumerate == "auto" and not cfg.enumerate_options:
            return self.render("options_count_only", count=len(options))
        parts = [self.render("options_intro", count=len(options))]
        for i, opt in enumerate(options, start=1):
            label = opt.get("label", opt.get("value", ""))
            parts.append(self.render("option_item", ordinal=i, n=i, label=str(label)))
        return " ".join(parts)

    def plan_question(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> NarrationPlan:
        """label → ``pause:<ms>`` → hint_bridge + hint (or description) → options; keys ``q:<uid>:label|hint|options``."""
        uid = str(q.field_uid)
        segments: dict[str, str] = {}
        keys: list[str] = []
        label_text = q.prompt or self.render("question", label=q.label, required=q.required)
        segments[f"q:{uid}:label"] = label_text
        keys.append(f"q:{uid}:label")
        help_text = q.hint or q.description  # AC4: description narrated when hint is absent
        if help_text:
            pause = meta.pause_ms if meta.pause_ms is not None else cfg.hint_pause_ms
            keys.append(f"pause:{pause}")
            segments[f"q:{uid}:hint"] = f"{self.render('hint_bridge', hint=help_text)} {help_text}".strip()
            keys.append(f"q:{uid}:hint")
        options_text = self._options_text(q, cfg, meta)
        if options_text:
            segments[f"q:{uid}:options"] = options_text
            keys.append(f"q:{uid}:options")
        text = " ".join(segments[k] for k in keys if not k.startswith("pause:"))
        return NarrationPlan(text=text, audio_keys=keys, segments=segments)

    def plan_review(self, items: list[ReviewItemData], cfg: VoiceFormConfig) -> NarrationPlan:
        """review_intro + one review_item / review_item_skipped per item (sensitive → "[hidden]")."""
        segments: dict[str, str] = {"review:intro": self.render("review_intro", count=len(items), total=len(items))}
        keys = ["review:intro"]
        for item in items:
            key = f"review:{item.position}"
            if item.skipped:
                segments[key] = self.render(
                    "review_item_skipped",
                    position=item.position,
                    label=item.label,
                    flagged=item.flagged,
                )
            else:
                answer = _HIDDEN if item.sensitive else item.answer_text
                segments[key] = self.render(
                    "review_item",
                    position=item.position,
                    label=item.label,
                    answer=answer,
                    flagged=item.flagged,
                )
            keys.append(key)
        text = " ".join(segments[k] for k in keys)
        return NarrationPlan(text=text, audio_keys=keys, segments=segments)
