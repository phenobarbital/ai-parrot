import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models.telemetry import MAX_TURN_SERIES, AttemptTelemetry, TurnUsage


class TestTurnUsage:
    def test_unknown_usage_is_representable(self):
        turn = TurnUsage(round_number=7)
        assert turn.input_tokens is None and turn.output_tokens is None

    def test_round_number_is_one_indexed(self):
        with pytest.raises(ValidationError):
            TurnUsage(round_number=0)

    def test_negative_input_tokens_rejected(self):
        with pytest.raises(ValidationError):
            TurnUsage(round_number=1, input_tokens=-1)

    def test_negative_output_tokens_rejected(self):
        with pytest.raises(ValidationError):
            TurnUsage(round_number=1, output_tokens=-1)

    def test_valid_usage_is_accepted(self):
        turn = TurnUsage(round_number=1, input_tokens=100, output_tokens=200)
        assert turn.input_tokens == 100
        assert turn.output_tokens == 200


class TestAttemptTelemetry:
    def test_series_cap(self):
        # MAX_TURN_SERIES + 1 turns should raise ValidationError
        with pytest.raises(ValidationError):
            AttemptTelemetry(
                turn_series=[TurnUsage(round_number=i) for i in range(1, MAX_TURN_SERIES + 2)]
            )

        # MAX_TURN_SERIES turns should validate successfully
        telemetry = AttemptTelemetry(
            turn_series=[TurnUsage(round_number=i) for i in range(1, MAX_TURN_SERIES + 1)]
        )
        assert len(telemetry.turn_series) == MAX_TURN_SERIES

    def test_defaults_are_empty_not_zero(self):
        # provider_* default to None (not 0)
        telemetry = AttemptTelemetry()
        assert telemetry.provider_input_tokens is None
        assert telemetry.provider_output_tokens is None
        # budget_report defaults to None
        assert telemetry.budget_report is None

    def test_terminal_defaults_to_completed(self):
        telemetry = AttemptTelemetry()
        assert telemetry.terminal == "completed"

    def test_error_class_defaults_to_empty_string(self):
        telemetry = AttemptTelemetry()
        assert telemetry.error_class == ""

    def test_resolved_model_defaults_to_empty_string(self):
        telemetry = AttemptTelemetry()
        assert telemetry.resolved_model == ""

    def test_turns_defaults_to_zero(self):
        telemetry = AttemptTelemetry()
        assert telemetry.turns == 0

    def test_turns_with_unknown_usage_defaults_to_zero(self):
        telemetry = AttemptTelemetry()
        assert telemetry.turns_with_unknown_usage == 0

    def test_successful_completion(self):
        telemetry = AttemptTelemetry(
            resolved_model="anthropic/claude-3-5-sonnet-20241022",
            turns=10,
            terminal="completed",
            provider_input_tokens=50000,
            provider_output_tokens=10000,
            turn_series=[TurnUsage(round_number=i, input_tokens=5000, output_tokens=1000) for i in range(1, 11)],
        )
        assert telemetry.terminal == "completed"
        assert telemetry.turns == 10

    def test_failed_attempt(self):
        telemetry = AttemptTelemetry(
            resolved_model="anthropic/claude-3-5-sonnet-20241022",
            turns=5,
            terminal="failed",
            error_class="TimeoutError",
        )
        assert telemetry.terminal == "failed"
        assert telemetry.error_class == "TimeoutError"

    def test_salvaged_attempt(self):
        telemetry = AttemptTelemetry(
            resolved_model="anthropic/claude-3-5-sonnet-20241022",
            turns=25,
            terminal="salvaged",
            provider_input_tokens=100000,
            provider_output_tokens=20000,
        )
        assert telemetry.terminal == "salvaged"
        assert telemetry.turns == 25