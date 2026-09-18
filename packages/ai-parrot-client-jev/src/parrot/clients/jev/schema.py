"""Translate Pydantic output types into System One questions, and answers back.

This is what makes ``JevClient.invoke(prompt, output_type=MyModel)`` work:
Jev cannot fill an arbitrary JSON schema, but every field of a Pydantic model
can be phrased as one typed question.

+----------------------------------------------+-----------+------------------------------------------+
| Field annotation                             | Primitive | Answer coercion                          |
+==============================================+===========+==========================================+
| ``bool``                                     | noul      | ``noul >= threshold``                    |
| ``Literal["a", "b"]`` / ``str``-valued Enum  | choice    | the selected label                       |
| ``int`` / ``float`` + ``criteria=[levels]``  | score     | rounded level for ``int``, raw ``float`` |
+----------------------------------------------+-----------+------------------------------------------+

Question text comes from ``Field(description=...)``. Extra guidance goes in
``Field(json_schema_extra={...})``:

- ``"criteria"``: label → description mapping for choices, ``{"true": ..,
  "false": ..}`` for nouls, or the ordered level list for scores.
- ``"question"``: an explicit :class:`Noul` / :class:`Choice` / :class:`Score`
  (or its ``dict`` form) that overrides the derivation entirely.

Example::

    class Triage(BaseModel):
        category: Literal["billing", "technical", "other"] = Field(
            description="What is this ticket about?"
        )
        urgent: bool = Field(description="Does the customer need an answer today?")
        severity: int = Field(
            description="How badly is the customer affected?",
            json_schema_extra={"criteria": ["Cosmetic", "Degraded", "Blocked"]},
        )
"""

from __future__ import annotations

import types
from enum import Enum
from typing import Any, Dict, Literal, Mapping, Optional, Type, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .exceptions import JevSchemaError
from .models import (
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    NoulCriteria,
    Question,
    Score,
    ScoreAnswer,
    SystemOneResponse,
    parse_question,
)

#: ``json_schema_extra`` key holding an explicit question override.
QUESTION_EXTRA_KEY = "question"
#: ``json_schema_extra`` key holding label descriptions / score levels / noul outcomes.
CRITERIA_EXTRA_KEY = "criteria"


def _unwrap_optional(annotation: Any) -> Any:
    """Return ``T`` for ``Optional[T]`` / ``T | None``; anything else unchanged."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _field_extra(field: FieldInfo) -> Dict[str, Any]:
    """Return the field's ``json_schema_extra`` as a plain dict (empty when absent or callable)."""
    extra = field.json_schema_extra
    return dict(extra) if isinstance(extra, Mapping) else {}


def _instructions(name: str, field: FieldInfo) -> str:
    """Question text: the field description, else its title, else a humanized name."""
    return field.description or field.title or name.replace("_", " ")


def _choice_labels(annotation: Any) -> Optional[list[str]]:
    """Labels for a ``Literal[...]`` or ``Enum`` annotation, or ``None`` when it is neither."""
    if get_origin(annotation) is Literal:
        return [str(value) for value in get_args(annotation)]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [str(member.value) for member in annotation]
    return None


def question_for_field(name: str, field: FieldInfo) -> Question:
    """Derive the System One question that answers one model field.

    Args:
        name: Field name (becomes the question id).
        field: The Pydantic :class:`FieldInfo`.

    Returns:
        A :class:`Noul`, :class:`Choice` or :class:`Score`.

    Raises:
        JevSchemaError: When the annotation has no System One equivalent.
    """
    extra = _field_extra(field)
    explicit = extra.get(QUESTION_EXTRA_KEY)
    if explicit is not None:
        return parse_question(name, explicit)

    annotation = _unwrap_optional(field.annotation)
    instructions = _instructions(name, field)
    criteria = extra.get(CRITERIA_EXTRA_KEY)

    if annotation is bool:
        noul_criteria = None
        if isinstance(criteria, Mapping):
            noul_criteria = NoulCriteria(
                true=criteria.get("true", criteria.get(True)),
                false=criteria.get("false", criteria.get(False)),
            )
        return Noul(instructions=instructions, criteria=noul_criteria)

    labels = _choice_labels(annotation)
    if labels is not None:
        described = criteria if isinstance(criteria, Mapping) else {}
        return Choice(instructions=instructions, criteria={label: described.get(label) for label in labels})

    if annotation in (int, float):
        if not isinstance(criteria, (list, tuple)) or not criteria:
            raise JevSchemaError(
                f"Field {name!r} is numeric but declares no score levels; add "
                f'Field(json_schema_extra={{"criteria": ["level 0", "level 1", ...]}})'
            )
        return Score(instructions=instructions, criteria=list(criteria))

    raise JevSchemaError(
        f"Field {name!r} ({annotation!r}) has no System One equivalent: use bool (noul), "
        "Literal/Enum (choice), or int/float with score levels (score), or set "
        f'json_schema_extra={{"{QUESTION_EXTRA_KEY}": ...}} explicitly'
    )


def questions_from_type(output_type: Type[BaseModel]) -> Dict[str, Question]:
    """Turn every field of a Pydantic model into a question keyed by field name.

    Args:
        output_type: A Pydantic v2 model class.

    Returns:
        ``{field_name: question}`` in declaration order.

    Raises:
        JevSchemaError: When ``output_type`` is not a Pydantic model or a field
            cannot be mapped.
    """
    if not (isinstance(output_type, type) and issubclass(output_type, BaseModel)):
        raise JevSchemaError(f"Jev structured output requires a Pydantic v2 model class, got {output_type!r}")
    return {name: question_for_field(name, field) for name, field in output_type.model_fields.items()}


def _expected_answer_type(annotation: Any) -> Optional[type]:
    """The answer class a derived question for ``annotation`` must produce, or ``None`` when unconstrained."""
    if annotation is bool:
        return NoulAnswer
    if _choice_labels(annotation) is not None:
        return ChoiceAnswer
    if annotation in (int, float):
        return ScoreAnswer
    return None


def answers_to_type(
    response: SystemOneResponse,
    output_type: Type[BaseModel],
    *,
    noul_threshold: float = 0.5,
) -> BaseModel:
    """Validate System One answers back into an instance of ``output_type``.

    Args:
        response: The API response whose answers are keyed by field name.
        output_type: The Pydantic model the questions were derived from.
        noul_threshold: Probability at or above which a noul becomes ``True``.

    Returns:
        A validated ``output_type`` instance.

    Raises:
        JevSchemaError: When a required field got no answer, an answer's kind
            does not match the field's primitive, or validation fails.
    """
    values: Dict[str, Any] = {}
    for name, field in output_type.model_fields.items():
        answer = response.answers.get(name)
        if answer is None:
            if field.is_required():
                raise JevSchemaError(f"Jev returned no answer for required field {name!r}")
            continue
        annotation = _unwrap_optional(field.annotation)
        expected = _expected_answer_type(annotation)
        if expected is not None and not isinstance(answer, expected):
            raise JevSchemaError(
                f"Field {name!r} expects a {expected.model_fields['type'].default} answer but Jev returned "
                f"{answer.type!r}; the questions sent do not match {output_type.__name__}"
            )
        if isinstance(answer, NoulAnswer):
            values[name] = answer.is_yes(noul_threshold)
        elif isinstance(answer, ChoiceAnswer):
            values[name] = answer.choice
        elif isinstance(answer, ScoreAnswer):
            values[name] = answer.level if annotation is int else answer.score
    try:
        return output_type.model_validate(values)
    except Exception as exc:  # pydantic.ValidationError, surfaced with context
        raise JevSchemaError(f"Jev answers do not validate as {output_type.__name__}: {exc}") from exc
