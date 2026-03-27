#!/usr/bin/env python3
"""
Tests for Product Advisor components.

Run with: pytest tests/test_product_advisor.py -v
"""
from unittest.mock import AsyncMock
import pytest
from parrot.conf import STATIC_DIR  # pylint: disable=C0415
from parrot.advisors import (
    ProductCatalog,
    SelectionStateManager,
    QuestionSet,
    DiscriminantQuestion,
    AnswerType,
    QuestionCategory,
)
from parrot.advisors.tools import (
    StartSelectionTool,
    ApplyCriteriaTool,
    UndoSelectionTool,
    create_advisor_tools,
)
from parrot.advisors.models import (
    ProductSpec,
    ProductDimensions
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_products():
    """Create sample products for testing."""
    return [
        ProductSpec(
            product_id="shed-001",
            name="Compact Storage Shed",
            category="sheds",
            price=999.99,
            dimensions=ProductDimensions(width=6, depth=8, height=7),
            use_cases=["storage", "garden"],
            unique_selling_points=["Easy assembly", "Weather resistant"],
        ),
        ProductSpec(
            product_id="shed-002",
            name="Workshop Shed",
            category="sheds",
            price=2499.99,
            dimensions=ProductDimensions(width=10, depth=12, height=9),
            use_cases=["workshop", "storage"],
            unique_selling_points=["Extra headroom", "Built-in workbench"],
        ),
        ProductSpec(
            product_id="shed-003",
            name="Premium Garden House",
            category="sheds",
            price=4999.99,
            dimensions=ProductDimensions(width=12, depth=16, height=10),
            use_cases=["workshop", "office", "studio"],
            unique_selling_points=["Insulated", "Windows included"],
        ),
    ]


@pytest.fixture
def sample_questions():
    """Create sample question set for testing."""
    questions = [
        DiscriminantQuestion(
            question_id="q_use_case_0",
            question_text="What will you primarily use this for?",
            question_text_voice="What's the main purpose?",
            category=QuestionCategory.USE_CASE,
            answer_type=AnswerType.SINGLE_CHOICE,
            options=[
                {"label": "Storage", "value": "storage"},
                {"label": "Workshop", "value": "workshop"},
                {"label": "Office/Studio", "value": "office"},
            ],
            maps_to_feature="use_case",
            priority=90,
            discrimination_power=0.7,
        ),
        DiscriminantQuestion(
            question_id="q_budget_1",
            question_text="What's your budget range?",
            question_text_voice="What's your budget?",
            category=QuestionCategory.BUDGET,
            answer_type=AnswerType.SINGLE_CHOICE,
            options=[
                {"label": "Under $1500", "value": "budget"},
                {"label": "$1500-$3000", "value": "mid"},
                {"label": "Over $3000", "value": "premium"},
            ],
            maps_to_feature="max_price",
            priority=70,
            discrimination_power=0.5,
        ),
    ]
    return QuestionSet(
        catalog_id="test",
        questions=questions,
        total_products=3,
    )


@pytest.fixture
def mock_catalog(sample_products):
    """Create mock catalog."""
    catalog = AsyncMock(spec=ProductCatalog)
    catalog.catalog_id = "test"
    catalog.get_all_products.return_value = sample_products
    catalog.get_all_product_ids.return_value = [p.product_id for p in sample_products]
    catalog.get_products.return_value = sample_products
    catalog.filter_products.return_value = (
        [p.product_id for p in sample_products[:2]],
        {"shed-003": "Over budget"}
    )
    return catalog


@pytest.fixture
def mock_state_manager():
    """Create mock state manager."""
    manager = AsyncMock(spec=SelectionStateManager)
    manager.can_undo.return_value = True
    manager.can_redo.return_value = False
    return manager


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestQuestionSet:
    """Tests for QuestionSet functionality."""

    def test_get_next_question(self, sample_questions):
        """Test getting next unanswered question."""
        # First question
        q = sample_questions.get_next_question([], {}, 3)
        assert q is not None
        assert q.question_id == "q_use_case_0"

        # After answering first
        q = sample_questions.get_next_question(["q_use_case_0"], {"use_case": "storage"}, 2)
        assert q is not None
        assert q.question_id == "q_budget_1"

        # After answering all
        q = sample_questions.get_next_question(
            ["q_use_case_0", "q_budget_1"],
            {"use_case": "storage", "max_price": 1500},
            1
        )
        assert q is None

    def test_question_parsing(self, sample_questions):
        """Test parsing user responses."""
        q = sample_questions.get_question("q_use_case_0")

        # Direct match
        result = q.parse_response("storage")
        assert result == {"use_case": "storage"}

        # Case insensitive
        result = q.parse_response("WORKSHOP")
        assert result == {"use_case": "workshop"}


class TestStartSelectionTool:
    """Tests for StartSelectionTool."""

    @pytest.mark.asyncio
    async def test_start_selection(self, mock_catalog, mock_state_manager, sample_questions):
        """Test starting a selection session."""
        from parrot.advisors.state import SelectionState, SelectionPhase

        # Mock state creation
        mock_state_manager.create_state.return_value = SelectionState(
            session_id="test_session",
            user_id="test_user",
            catalog_id="test",
            phase=SelectionPhase.INTAKE,
            all_product_ids=["shed-001", "shed-002", "shed-003"],
            candidate_ids=["shed-001", "shed-002", "shed-003"],
        )
        mock_state_manager.get_state.return_value = None  # No existing session

        tool = StartSelectionTool(
            catalog=mock_catalog,
            state_manager=mock_state_manager,
            question_set=sample_questions,
        )

        result = await tool.execute(
            user_id="test_user",
            session_id="test_session",
        )

        assert result.status == "success"
        assert "3 options" in result.result
        mock_state_manager.create_state.assert_called_once()


class TestApplyCriteriaTool:
    """Tests for ApplyCriteriaTool."""

    @pytest.mark.asyncio
    async def test_apply_criteria(self, mock_catalog, mock_state_manager, sample_questions):
        """Test applying criteria filters products."""
        from parrot.advisors.state import SelectionState, SelectionPhase

        # Mock current state
        current_state = SelectionState(
            session_id="test_session",
            user_id="test_user",
            catalog_id="test",
            phase=SelectionPhase.QUESTIONING,
            all_product_ids=["shed-001", "shed-002", "shed-003"],
            candidate_ids=["shed-001", "shed-002", "shed-003"],
        )
        mock_state_manager.get_state.return_value = current_state

        # Mock state after applying criteria
        updated_state = SelectionState(
            session_id="test_session",
            user_id="test_user",
            catalog_id="test",
            phase=SelectionPhase.QUESTIONING,
            all_product_ids=["shed-001", "shed-002", "shed-003"],
            candidate_ids=["shed-001", "shed-002"],
            criteria={"use_case": "storage"},
        )
        mock_state_manager.apply_criteria.return_value = (updated_state, 1)

        tool = ApplyCriteriaTool(
            catalog=mock_catalog,
            state_manager=mock_state_manager,
            question_set=sample_questions,
        )

        result = await tool.execute(
            user_id="test_user",
            session_id="test_session",
            user_response="I need it for storage",
            question_id="q_use_case_0",
        )

        assert result.status == "success"
        assert "narrows" in result.result.lower() or "2 products" in result.result


class TestUndoTool:
    """Tests for UndoSelectionTool."""

    @pytest.mark.asyncio
    async def test_undo(self, mock_state_manager):
        """Test undo restores previous state."""
        from parrot.advisors.state import SelectionState, SelectionPhase

        previous_state = SelectionState(
            session_id="test_session",
            user_id="test_user",
            catalog_id="test",
            phase=SelectionPhase.QUESTIONING,
            candidate_ids=["shed-001", "shed-002", "shed-003"],
        )
        mock_state_manager.undo.return_value = (previous_state, "Applied use_case=storage")

        tool = UndoSelectionTool(state_manager=mock_state_manager)

        result = await tool.execute(
            user_id="test_user",
            session_id="test_session",
        )

        assert result.status == "success"
        assert "undone" in result.result.lower()
        assert "3 products" in result.result


class TestToolFactory:
    """Tests for create_advisor_tools factory."""

    def test_creates_all_tools(self, mock_catalog, mock_state_manager, sample_questions):
        """Test factory creates all expected tools."""
        tools = create_advisor_tools(
            state_manager=mock_state_manager,
            catalog=mock_catalog,
            question_set=sample_questions,
        )

        assert len(tools) == 8  # All 8 tools

        tool_names = {t.name for t in tools}
        expected_names = {
            "start_product_selection",
            "get_next_question",
            "apply_selection_criteria",
            "compare_products",
            "undo_selection",
            "redo_selection",
            "get_selection_state",
            "recommend_product",
        }
        assert tool_names == expected_names


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests (require real database)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestIntegration:
    """Integration tests requiring PostgreSQL and Redis."""

    @pytest.mark.asyncio
    async def test_full_selection_flow(self):
        """Test complete selection flow with real database."""
        # This test requires:
        # - PostgreSQL with gorillashed.products table
        # - Redis running
        pytest.skip("Requires database setup")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
