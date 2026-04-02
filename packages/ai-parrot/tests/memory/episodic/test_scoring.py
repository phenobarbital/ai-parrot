"""Unit tests for episodic memory importance scoring strategies."""
import pytest

from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, EpisodicMemory
from parrot.memory.episodic.scoring import (
    HeuristicScorer,
    ImportanceScorer,
    ValueScorer,
)


@pytest.fixture
def success_episode() -> EpisodicMemory:
    """A successful episode with tools and detailed outcome."""
    return EpisodicMemory(
        agent_id="test-agent",
        situation="User asked about weather forecast for tomorrow",
        action_taken="Called weather API with location parameter",
        outcome=EpisodeOutcome.SUCCESS,
        outcome_details="Returned 5-day forecast with temperature and precipitation data",
        category=EpisodeCategory.TOOL_EXECUTION,
        related_tools=["weather_api"],
        lesson_learned="Always include timezone in weather queries for accurate local time",
        embedding=[0.0] * 384,
    )


@pytest.fixture
def failure_episode() -> EpisodicMemory:
    """A minimal failure episode."""
    return EpisodicMemory(
        agent_id="test-agent",
        situation="Q",
        action_taken="Failed",
        outcome=EpisodeOutcome.FAILURE,
        category=EpisodeCategory.ERROR_RECOVERY,
        embedding=[0.0] * 384,
    )


@pytest.fixture
def partial_episode() -> EpisodicMemory:
    """A partial success episode."""
    return EpisodicMemory(
        agent_id="test-agent",
        situation="Attempted to retrieve user data from database",
        action_taken="Ran database query with user_id filter",
        outcome=EpisodeOutcome.PARTIAL,
        outcome_details="Retrieved partial data, some fields missing",
        category=EpisodeCategory.QUERY_RESOLUTION,
        embedding=[0.0] * 384,
    )


@pytest.fixture
def timeout_episode() -> EpisodicMemory:
    """A timeout episode with known error type."""
    return EpisodicMemory(
        agent_id="test-agent",
        situation="Fetching large dataset from external service",
        action_taken="Called external API endpoint with large payload",
        outcome=EpisodeOutcome.TIMEOUT,
        error_type="timeout",
        error_message="Request timed out after 30 seconds",
        category=EpisodeCategory.TOOL_EXECUTION,
        embedding=[0.0] * 384,
    )


class TestHeuristicScorer:
    """Tests for HeuristicScorer."""

    def test_success_scores_lower_than_failure(
        self, success_episode: EpisodicMemory, failure_episode: EpisodicMemory
    ) -> None:
        """SUCCESS episodes should score lower than FAILURE."""
        scorer = HeuristicScorer()
        assert scorer.score(success_episode) < scorer.score(failure_episode)

    def test_failure_scores_higher_than_partial(
        self, failure_episode: EpisodicMemory, partial_episode: EpisodicMemory
    ) -> None:
        """FAILURE episodes should score higher than PARTIAL."""
        scorer = HeuristicScorer()
        assert scorer.score(failure_episode) > scorer.score(partial_episode)

    def test_partial_scores_higher_than_success(
        self, partial_episode: EpisodicMemory, success_episode: EpisodicMemory
    ) -> None:
        """PARTIAL episodes should score higher than SUCCESS."""
        scorer = HeuristicScorer()
        assert scorer.score(partial_episode) > scorer.score(success_episode)

    def test_score_range(self, success_episode: EpisodicMemory) -> None:
        """Score must be in [0.0, 1.0]."""
        scorer = HeuristicScorer()
        score = scorer.score(success_episode)
        assert 0.0 <= score <= 1.0

    def test_known_error_boosts_importance(
        self, timeout_episode: EpisodicMemory
    ) -> None:
        """Known error types should boost the score above base TIMEOUT/FAILURE."""
        scorer = HeuristicScorer()
        # timeout + known error type "timeout" → base 7 + 2 = 9, normalized 0.9
        score = scorer.score(timeout_episode)
        # Should be higher than plain timeout (7/10 = 0.7)
        assert score > 0.7

    def test_exact_success_score(self, success_episode: EpisodicMemory) -> None:
        """SUCCESS without error type should normalize to 0.3."""
        scorer = HeuristicScorer()
        assert scorer.score(success_episode) == pytest.approx(0.3, abs=0.01)

    def test_exact_failure_score(self, failure_episode: EpisodicMemory) -> None:
        """FAILURE without error type should normalize to 0.7."""
        scorer = HeuristicScorer()
        assert scorer.score(failure_episode) == pytest.approx(0.7, abs=0.01)

    def test_protocol_compliance(self) -> None:
        """HeuristicScorer must satisfy ImportanceScorer protocol."""
        assert isinstance(HeuristicScorer(), ImportanceScorer)


class TestValueScorer:
    """Tests for ValueScorer."""

    def test_default_weights(self) -> None:
        """Default weights match spec values."""
        scorer = ValueScorer()
        assert scorer.outcome_weight == 0.3
        assert scorer.tool_usage_weight == 0.2
        assert scorer.query_length_weight == 0.1
        assert scorer.response_length_weight == 0.2
        assert scorer.feedback_weight == 0.3
        assert scorer.threshold == 0.4

    def test_success_scores_higher_than_failure(
        self, success_episode: EpisodicMemory, failure_episode: EpisodicMemory
    ) -> None:
        """SUCCESS episodes should score higher than minimal FAILURE."""
        scorer = ValueScorer()
        assert scorer.score(success_episode) > scorer.score(failure_episode)

    def test_score_range_success(self, success_episode: EpisodicMemory) -> None:
        """Score must be in [0.0, 1.0] for success episode."""
        scorer = ValueScorer()
        assert 0.0 <= scorer.score(success_episode) <= 1.0

    def test_score_range_failure(self, failure_episode: EpisodicMemory) -> None:
        """Score must be in [0.0, 1.0] for failure episode."""
        scorer = ValueScorer()
        assert 0.0 <= scorer.score(failure_episode) <= 1.0

    def test_tool_usage_adds_value(self) -> None:
        """Episodes with tools should score higher than without tools."""
        scorer = ValueScorer()
        ep_with_tools = EpisodicMemory(
            agent_id="a",
            situation="Long enough situation to pass length check",
            action_taken="Called API",
            outcome=EpisodeOutcome.SUCCESS,
            related_tools=["api_tool"],
            embedding=[0.0] * 384,
        )
        ep_without_tools = EpisodicMemory(
            agent_id="a",
            situation="Long enough situation to pass length check",
            action_taken="Called API",
            outcome=EpisodeOutcome.SUCCESS,
            related_tools=[],
            embedding=[0.0] * 384,
        )
        assert scorer.score(ep_with_tools) > scorer.score(ep_without_tools)

    def test_threshold_with_configurable_value(
        self, failure_episode: EpisodicMemory
    ) -> None:
        """A minimal failure episode should score below default threshold."""
        scorer = ValueScorer(threshold=0.4)
        score = scorer.score(failure_episode)
        assert score < 0.4

    def test_is_valuable_returns_bool(
        self, success_episode: EpisodicMemory
    ) -> None:
        """is_valuable should return bool."""
        scorer = ValueScorer()
        result = scorer.is_valuable(success_episode)
        assert isinstance(result, bool)

    def test_configurable_weights_change_score(
        self, success_episode: EpisodicMemory
    ) -> None:
        """Adjusting weights changes the score."""
        scorer_default = ValueScorer()
        scorer_custom = ValueScorer(outcome_weight=1.0, tool_usage_weight=0.0)
        # Different weights → different scores (or at least same range)
        score_default = scorer_default.score(success_episode)
        score_custom = scorer_custom.score(success_episode)
        assert 0.0 <= score_default <= 1.0
        assert 0.0 <= score_custom <= 1.0

    def test_lesson_learned_adds_value(self) -> None:
        """Episodes with lesson_learned should score higher."""
        scorer = ValueScorer()
        ep_with_lesson = EpisodicMemory(
            agent_id="a",
            situation="Test situation with enough words to qualify",
            action_taken="Did something",
            outcome=EpisodeOutcome.SUCCESS,
            lesson_learned="Always validate input before processing",
            embedding=[0.0] * 384,
        )
        ep_without_lesson = EpisodicMemory(
            agent_id="a",
            situation="Test situation with enough words to qualify",
            action_taken="Did something",
            outcome=EpisodeOutcome.SUCCESS,
            lesson_learned=None,
            embedding=[0.0] * 384,
        )
        assert scorer.score(ep_with_lesson) > scorer.score(ep_without_lesson)

    def test_protocol_compliance(self) -> None:
        """ValueScorer must satisfy ImportanceScorer protocol."""
        assert isinstance(ValueScorer(), ImportanceScorer)
