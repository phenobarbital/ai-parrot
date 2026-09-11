"""Unit tests for FormEventBinding.on_failure — FEAT-459 / TASK-3162."""

from __future__ import annotations

from parrot_formdesigner.core.events import FormEventBinding


def test_on_failure_defaults_to_continue() -> None:
    binding = FormEventBinding(handler_ref="survey_v1.onBeforeSubmit")
    assert binding.on_failure == "continue"


def test_on_failure_accepts_abort() -> None:
    binding = FormEventBinding(
        handler_ref="survey_v1.onBeforeSubmit", on_failure="abort"
    )
    assert binding.on_failure == "abort"


def test_required_semantics_unchanged() -> None:
    """required still means MISSING handler, independent of on_failure."""
    binding = FormEventBinding(
        handler_ref="survey_v1.onBeforeSubmit", required=True, on_failure="continue"
    )
    assert binding.required is True
    assert binding.on_failure == "continue"


def test_existing_bindings_deserialize() -> None:
    """A binding serialised before this feature (no on_failure key) still parses."""
    binding = FormEventBinding.model_validate({"handler_ref": "x.onBeforeSubmit"})
    assert binding.on_failure == "continue"