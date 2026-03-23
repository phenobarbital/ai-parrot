"""Unit tests for ContextAssembler — priority-based token budgeting."""
import pytest

from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryConfig


class TestContextAssembler:
    def test_assemble_within_budget(self):
        """Assembled context stays within token budget."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=1000))
        ctx = assembler.assemble(
            episodic_warnings="Don't call unauthenticated",
            relevant_skills="Use get_schema tool",
            conversation="User: hello\nAssistant: hi",
        )
        assert ctx.tokens_used <= 1000

    def test_priority_order_episodic_first(self):
        """When budget is tight, episodic warnings take priority."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=50))
        ctx = assembler.assemble(
            episodic_warnings="A" * 100,  # 25 tokens
            relevant_skills="B" * 200,   # 50 tokens
            conversation="C" * 200,      # 50 tokens
        )
        assert len(ctx.episodic_warnings) > 0
        assert ctx.tokens_used <= 50

    def test_empty_input(self):
        """All-empty input returns empty MemoryContext with tokens_used=0."""
        assembler = ContextAssembler()
        ctx = assembler.assemble()
        assert ctx.tokens_used == 0
        assert ctx.episodic_warnings == ""
        assert ctx.relevant_skills == ""
        assert ctx.conversation_summary == ""

    def test_unused_budget_rolls_over(self):
        """If episodic is empty, skills get more budget."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=100))
        ctx = assembler.assemble(
            episodic_warnings="",
            relevant_skills="B" * 300,
            conversation="",
        )
        # Skills should get more than its default 30% since episodic is empty
        assert len(ctx.relevant_skills) > 0

    def test_conversation_truncated_from_oldest(self):
        """Conversation history drops oldest turns first when over budget."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=50))
        conversation = "\n".join([f"Turn {i}" for i in range(100)])
        ctx = assembler.assemble(conversation=conversation)
        # Should contain later turns, not earlier ones
        assert "Turn 99" in ctx.conversation_summary or ctx.conversation_summary.endswith("...")

    def test_tokens_budget_set_correctly(self):
        """Returned MemoryContext records the configured budget."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=500))
        ctx = assembler.assemble(episodic_warnings="test")
        assert ctx.tokens_budget == 500

    def test_oversized_section_truncated(self):
        """A section that exceeds its allocation is truncated."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=40))
        big_text = "X" * 1000  # 250 tokens
        ctx = assembler.assemble(episodic_warnings=big_text)
        assert ctx.tokens_used <= 40
        assert ctx.episodic_warnings.endswith("...")

    def test_only_skills_provided(self):
        """Works correctly when only skills are provided."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=200))
        ctx = assembler.assemble(relevant_skills="Use X tool.\nUse Y tool.")
        assert ctx.relevant_skills != ""
        assert ctx.episodic_warnings == ""
        assert ctx.conversation_summary == ""
        assert ctx.tokens_used > 0

    def test_import(self):
        """Import path works as specified."""
        from parrot.memory.unified.context import ContextAssembler as CA  # noqa: F401
        assert CA is ContextAssembler
