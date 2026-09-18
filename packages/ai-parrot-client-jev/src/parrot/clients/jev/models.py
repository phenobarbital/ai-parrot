"""Wire models for TypeSafe AI's System One API, served by the Jev model.

The shapes mirror ``https://api.typesafe.ai/openapi.json`` (as reproduced by
the official ``typesafe-sdk`` generated schemas): three question primitives
— ``noul`` (yes/no), ``choice`` (one of N labels) and ``score`` (ordered
rubric) — their tagged answers, and the ``/v1/systemone`` request/response
envelopes. Every model is Pydantic v2 so questions can be declared, validated
and serialized without the vendor SDK.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from .exceptions import JevConfigurationError

logger = logging.getLogger(__name__)

#: Text, a JSON object, or a JSON array — what the API accepts for ``state``,
#: ``instructions`` and every criteria description.
JSONContent = Union[str, Dict[str, Any], List[Any]]

#: Hard cap on the number of labels a single ``choice`` question may carry.
MAX_CHOICE_OPTIONS = 255


class JevModel(str, Enum):
    """TypeSafe System One model routes.

    String-valued so members interchange with raw model strings.
    """

    JEV_LATEST = "jev-latest"


# --------------------------------------------------------------------------- #
# Questions                                                                   #
# --------------------------------------------------------------------------- #


class NoulCriteria(BaseModel):
    """Optional descriptions of the *yes* and *no* outcomes of a noul question."""

    model_config = ConfigDict(extra="allow")

    true: Optional[JSONContent] = Field(default=None, description="Description of the yes outcome.")
    false: Optional[JSONContent] = Field(default=None, description="Description of the no outcome.")


class _Question(BaseModel):
    """Shared base of the three question primitives.

    ``extra="allow"`` lets callers forward fields a newer API revision adds
    without waiting for a client release (the vendor SDK allows the same).
    """

    model_config = ConfigDict(extra="allow")

    instructions: Optional[JSONContent] = Field(
        default=None,
        description="The question to ask, as text, a JSON object, or an array. Question ids are not "
        "sent to the model, so the instructions must carry the full meaning.",
    )

    def to_wire(self) -> Dict[str, Any]:
        """Serialize the question for the request body, omitting unset optionals.

        Returns:
            A JSON-ready ``dict`` with a ``type`` discriminator.
        """
        payload = self.model_dump(mode="json")
        if payload.get("instructions") is None:
            payload.pop("instructions", None)
        return payload


class Noul(_Question):
    """A yes/no question. The answer is the probability of *yes*.

    Example::

        Noul(instructions="Does the customer ask for a refund?")
    """

    type: Literal["noul"] = "noul"
    criteria: Optional[NoulCriteria] = Field(default=None, description="Optional yes/no outcome descriptions.")

    def to_wire(self) -> Dict[str, Any]:
        """Serialize, dropping an absent or fully-empty ``criteria`` block."""
        payload = super().to_wire()
        criteria = payload.get("criteria")
        if criteria is None:
            payload.pop("criteria", None)
        else:
            payload["criteria"] = {k: v for k, v in criteria.items() if v is not None}
        return payload


class Choice(_Question):
    """Pick exactly one label out of a fixed set.

    Example::

        Choice(
            instructions="What is this ticket about?",
            criteria={"billing": "Payments and invoices", "technical": None, "other": None},
        )
    """

    type: Literal["choice"] = "choice"
    criteria: Dict[str, Optional[JSONContent]] = Field(
        description="Labels mapped to an optional description (``None`` leaves the label undescribed)."
    )

    @field_validator("criteria")
    @classmethod
    def _validate_criteria(cls, value: Dict[str, Optional[JSONContent]]) -> Dict[str, Optional[JSONContent]]:
        """Require at least one label and no more than :data:`MAX_CHOICE_OPTIONS`."""
        if not value:
            raise ValueError("a choice question needs at least one label in criteria")
        if len(value) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"a choice question supports at most {MAX_CHOICE_OPTIONS} labels, got {len(value)}")
        return value


class Score(_Question):
    """Place the state on an ordered rubric; level ``i`` is ``criteria[i]``.

    Example::

        Score(
            instructions="How severe is the reported problem?",
            criteria=["Cosmetic", "Degraded but usable", "Blocked, no workaround"],
        )
    """

    type: Literal["score"] = "score"
    criteria: List[JSONContent] = Field(description="Ordered level descriptions, one per score starting at zero.")

    @field_validator("criteria")
    @classmethod
    def _validate_criteria(cls, value: List[JSONContent]) -> List[JSONContent]:
        """Require at least one level."""
        if not value:
            raise ValueError("a score question needs at least one level in criteria")
        return value


Question = Union[Noul, Choice, Score]
"""Any of the three question primitives."""

QuestionInput = Union[Noul, Choice, Score, Mapping[str, Any]]
"""A question object or its plain ``dict`` form (``{"type": "choice", ...}``)."""

_QUESTION_ADAPTER: TypeAdapter[Question] = TypeAdapter(
    Annotated[Union[Noul, Choice, Score], Field(discriminator="type")]
)


def parse_question(name: str, question: QuestionInput) -> Question:
    """Coerce a question object or ``dict`` into a validated primitive.

    Args:
        name: The question id, used only in error messages.
        question: A :class:`Noul` / :class:`Choice` / :class:`Score` instance or
            a mapping with a ``type`` discriminator.

    Returns:
        The validated question instance.

    Raises:
        JevConfigurationError: When the mapping is not a valid question.
    """
    if isinstance(question, (Noul, Choice, Score)):
        return question
    if not isinstance(question, Mapping):
        raise JevConfigurationError(
            f'Question "{name}" must be a Noul/Choice/Score instance or a dict with a "type" key, '
            f"got {type(question).__name__}"
        )
    try:
        return _QUESTION_ADAPTER.validate_python(dict(question))
    except ValidationError as exc:
        raise JevConfigurationError(f'Question "{name}" is invalid: {exc}') from exc


def normalize_questions(questions: Mapping[str, QuestionInput]) -> Dict[str, Dict[str, Any]]:
    """Validate a question map and serialize it for the request body.

    Args:
        questions: Questions keyed by the id their answers will be returned under.

    Returns:
        ``{name: wire_dict}`` ready to be JSON-encoded.

    Raises:
        JevConfigurationError: When the map is empty or a question is invalid.
    """
    if not questions:
        raise JevConfigurationError("At least one question is required.")
    return {name: parse_question(name, question).to_wire() for name, question in questions.items()}


# --------------------------------------------------------------------------- #
# Answers                                                                     #
# --------------------------------------------------------------------------- #


class NoulAnswer(BaseModel):
    """Answer to a :class:`Noul` question."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: Literal["noul"] = "noul"
    noul: float = Field(description="Probability of a *yes* answer, from zero to one.")

    @property
    def value(self) -> float:
        """The plain answer value: the *yes* probability."""
        return self.noul

    def is_yes(self, threshold: float = 0.5) -> bool:
        """Decide the boolean at ``threshold`` (inclusive)."""
        return self.noul >= threshold


class ChoiceAnswer(BaseModel):
    """Answer to a :class:`Choice` question."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: Literal["choice"] = "choice"
    choice: str = Field(description="The selected label.")
    confidence: float = Field(description="Reported confidence in the selected label.")
    probabilities: Dict[str, float] = Field(default_factory=dict, description="Probability per label.")

    @property
    def value(self) -> str:
        """The plain answer value: the selected label."""
        return self.choice


class ScoreAnswer(BaseModel):
    """Answer to a :class:`Score` question."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: Literal["score"] = "score"
    score: float = Field(description="Expected score; may fall between the integer rubric levels.")
    confidence: float = Field(description="Reported confidence in the score.")
    legend: Dict[int, JSONContent] = Field(default_factory=dict, description="Rubric descriptions keyed by level.")
    probabilities: Dict[int, float] = Field(default_factory=dict, description="Probability per integer level.")

    @property
    def value(self) -> float:
        """The plain answer value: the expected score."""
        return self.score

    @property
    def level(self) -> int:
        """The nearest integer rubric level."""
        return int(round(self.score))


Answer = Annotated[Union[NoulAnswer, ChoiceAnswer, ScoreAnswer], Field(discriminator="type")]
"""An answer, identified by its ``type`` discriminator."""

_KNOWN_ANSWER_TYPES = frozenset({"noul", "choice", "score"})


class JevUsage(BaseModel):
    """Token accounting reported by the API (output tokens are free)."""

    model_config = ConfigDict(extra="allow")

    input_tokens: Optional[int] = Field(default=None, description="Input tokens consumed, when reported.")
    output_tokens: Optional[int] = Field(default=None, description="Output tokens, when reported.")
    billing_units: Optional[int] = Field(default=None, description="Billing units, when reported.")


class SystemOneResponse(BaseModel):
    """A ``POST /v1/systemone`` response: answers keyed by question id."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(description="The model that answered the request.")
    answers: Dict[str, Answer] = Field(default_factory=dict, description="Answers keyed by question id.")
    usage: JevUsage = Field(default_factory=JevUsage, description="Token usage for the request.")
    request_id: Optional[str] = Field(default=None, description="Server request id (from the response header).")

    @field_validator("answers", mode="before")
    @classmethod
    def _drop_unknown_answer_types(cls, value: Any) -> Any:
        """Forward-compat: skip answer kinds this client version does not model."""
        if not isinstance(value, dict):
            return value
        kept: Dict[str, Any] = {}
        for name, answer in value.items():
            tag = answer.get("type") if isinstance(answer, dict) else getattr(answer, "type", None)
            if tag not in _KNOWN_ANSWER_TYPES:
                logger.warning("Ignoring answer %r with unrecognized type %r", name, tag)
                continue
            kept[name] = answer
        return kept

    @property
    def nouls(self) -> Dict[str, NoulAnswer]:
        """Yes/no answers keyed by question id."""
        return {name: answer for name, answer in self.answers.items() if isinstance(answer, NoulAnswer)}

    @property
    def choices(self) -> Dict[str, ChoiceAnswer]:
        """Choice answers keyed by question id."""
        return {name: answer for name, answer in self.answers.items() if isinstance(answer, ChoiceAnswer)}

    @property
    def scores(self) -> Dict[str, ScoreAnswer]:
        """Score answers keyed by question id."""
        return {name: answer for name, answer in self.answers.items() if isinstance(answer, ScoreAnswer)}

    def values(self) -> Dict[str, Union[str, float]]:
        """Plain answer values keyed by question id (label, score, or yes-probability)."""
        return {name: answer.value for name, answer in self.answers.items()}

    def __getitem__(self, name: str) -> Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]:
        """Look up one answer by question id."""
        return self.answers[name]


class ModelMetadata(BaseModel):
    """One entry of ``GET /v1/models``."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Model route, e.g. ``jev-latest``.")
    description: str = Field(default="", description="Human-readable description.")
    release_date: str = Field(default="", description="Release date as reported by the API.")


class ListModelsResponse(BaseModel):
    """The models available to the account."""

    model_config = ConfigDict(extra="allow")

    models: List[ModelMetadata] = Field(default_factory=list, description="Available models.")
