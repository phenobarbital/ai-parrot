"""Unit tests for ContextAssembler — priority-based token budgeting."""

import hashlib

import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.dynamics.models import MemoryRef
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryCandidate, MemoryConfig


def _scope(*, user_id: str | None = "user-1") -> MemoryRequestScope:
    """Build a deterministic runtime scope for context tests."""
    return MemoryRequestScope(
        tenant_id="tenant-1",
        agent_id="agent-1",
        user_id=user_id,
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


def _candidate(
    scope: MemoryRequestScope,
    *,
    memory_id: str,
    text: str,
    source: str = "episodic",
    candidate_type: str = "episodic",
    relevance: float = 0.5,
    ranking_score: float | None = None,
    lane: str = "warning",
) -> MemoryCandidate:
    """Build a candidate with explicit identity and version metadata."""
    return MemoryCandidate(
        scope=scope,
        memory_id=memory_id,
        content_version="v1",
        source=source,
        text=text,
        relevance=relevance,
        ranking_score=ranking_score,
        candidate_type=candidate_type,
        lane=lane,
    )


def test_assembler_splits_episodic_lanes_within_one_budget() -> None:
    """Warnings pack first; recalls use their shared remaining budget."""
    scope = _scope()
    assembler = ContextAssembler(
        MemoryConfig(
            max_context_tokens=100,
            enable_skills=False,
            enable_conversation=False,
            episodic_weight=1.0,
            skill_weight=0.0,
            conversation_weight=0.0,
        )
    )
    candidates = [
        _candidate(scope, memory_id="warning", text="W" * 200, relevance=0.1),
        _candidate(scope, memory_id="recall", text="R" * 159, relevance=0.9, lane="recall"),
        _candidate(scope, memory_id="dropped", text="D" * 4, relevance=0.8, lane="recall"),
    ]

    context = assembler.assemble_candidates(candidates, scope=scope)

    assert context.episodic_warnings == "W" * 200
    assert context.episodic_recall == "R" * 159
    assert context.tokens_used == 90
    assert context.delivered_refs == ("episodic:warning:v1", "episodic:recall:v1")
    assert "episodic:dropped:v1" not in context.delivered_refs


def test_user_section_cap_applies_after_normalization_and_rollover() -> None:
    """Normalization and rollover cannot raise the user ceiling."""
    scope = _scope()
    assembler = ContextAssembler(
        MemoryConfig(
            max_context_tokens=1000,
            enable_skills=False,
            enable_conversation=False,
            enable_user_memory=True,
            user_context_tokens=600,
            user_weight=0.2,
        )
    )
    candidate = _candidate(
        scope,
        memory_id="oversized-profile",
        text="U" * 3200,
        source="user",
        candidate_type="user",
    )

    context = assembler.assemble_candidates([candidate], scope=scope)

    assert context.user_knowledge == ""
    assert context.delivered_refs == ()
    assert context.tokens_used == 0


def test_user_section_cap_zero_and_legacy_none() -> None:
    """Zero suppresses even tiny records and refs; None adds no user-specific cap."""
    scope = _scope()
    candidate = _candidate(scope, memory_id="tiny", text="abc", source="user", candidate_type="user")
    base_config = dict(
        enable_episodic=False,
        enable_skills=False,
        enable_conversation=False,
        enable_user_memory=True,
        episodic_weight=0.0,
        skill_weight=0.0,
        conversation_weight=1.0,
        user_weight=1.0,
    )

    zero_context = ContextAssembler(MemoryConfig(**base_config, user_context_tokens=0)).assemble_candidates(
        [candidate], scope=scope
    )
    legacy_context = ContextAssembler(MemoryConfig(**base_config, user_context_tokens=None)).assemble_candidates(
        [candidate], scope=scope
    )

    assert zero_context.user_knowledge == ""
    assert zero_context.delivered_refs == ()
    assert legacy_context.user_knowledge == "abc"
    assert legacy_context.delivered_refs == ("user:tiny:v1",)


def test_user_priority_high_reserves_ceiling_before_weighted_sections() -> None:
    """At configured 400/effective 360, high admits 125 profile tokens; normal has 108."""
    scope = _scope()
    common = dict(
        max_context_tokens=400,
        enable_skills=False,
        enable_conversation=False,
        enable_user_memory=True,
        episodic_weight=0.7,
        skill_weight=0.0,
        conversation_weight=0.3,
        user_weight=0.3,
        user_context_tokens=125,
    )
    candidates = [
        _candidate(scope, memory_id="episode", text="E" * 1004),
        _candidate(scope, memory_id="large-profile", text="L" * 500, source="user", candidate_type="user", relevance=1.0),
        _candidate(scope, memory_id="small-profile", text="S" * 432, source="user", candidate_type="user", relevance=0.5),
    ]

    normal = ContextAssembler(MemoryConfig(**common, user_priority="normal")).assemble_candidates(
        candidates, scope=scope
    )
    high = ContextAssembler(MemoryConfig(**common, user_priority="high")).assemble_candidates(candidates, scope=scope)

    assert normal.user_knowledge == "S" * 432
    assert normal.tokens_used == 359
    assert high.user_knowledge == "L" * 500
    assert high.tokens_used == 125
    assert normal.tokens_used <= 360
    assert high.tokens_used <= 360


def test_user_priority_modes_agree_when_weighted_share_reaches_ceiling() -> None:
    """Content, refs and digests agree when both allocations admit the same records."""
    scope = _scope()
    config = dict(
        max_context_tokens=2400,
        enable_skills=False,
        enable_conversation=False,
        enable_user_memory=True,
        episodic_weight=0.7,
        skill_weight=0.0,
        conversation_weight=0.3,
        user_weight=0.3,
        user_context_tokens=400,
    )
    candidates = [
        _candidate(scope, memory_id="episode", text="E" * 6044),
        _candidate(scope, memory_id="profile", text="P" * 1600, source="user", candidate_type="user"),
    ]

    normal = ContextAssembler(MemoryConfig(**config, user_priority="normal")).assemble_candidates(candidates, scope=scope)
    high = ContextAssembler(MemoryConfig(**config, user_priority="high")).assemble_candidates(candidates, scope=scope)

    assert normal.model_dump() == high.model_dump()
    assert normal.delivered_refs == ("episodic:episode:v1", "user:profile:v1")
    assert normal.tokens_used == 1911


def test_packed_original_refs_follow_complete_candidate_content() -> None:
    """Only fully accepted candidates carry original refs through the token budget."""
    scope = _scope()
    namespace = MemoryNamespace(
        tenant_id=scope.tenant_id, agent_id=scope.agent_id, user_id=scope.user_id, session_id="old"
    )
    candidates = []
    for identity, text in [("fits", "short lesson"), ("dropped", "x" * 1000)]:
        data = _candidate(scope, memory_id=identity, text=text).model_dump()
        data["memory_ref"] = MemoryRef(namespace=namespace, kind="episode", memory_id=identity, content_version="v1")
        candidates.append(MemoryCandidate.model_validate(data))
    context = ContextAssembler(MemoryConfig(max_context_tokens=40)).assemble_candidates(candidates, scope=scope)
    assert context.delivered_refs == ("episodic:fits:v1",)
    assert context.memory_refs == (candidates[0].memory_ref,)
    assert context.memory_refs[0].namespace.session_id == "old"


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate_type": "user"},
        {"source": "user_knowledge"},
        {"memory_id": "different"},
        {"content_version": "different"},
        {"scope": _scope(user_id="foreign")},
    ],
)
def test_candidate_rejects_inconsistent_original_ref(changes: dict) -> None:
    """A typed ref cannot turn foreign or non-episodic content into review evidence."""
    scope = _scope()
    data = _candidate(scope, memory_id="episode", text="lesson").model_dump()
    data["memory_ref"] = MemoryRef(
        namespace=MemoryNamespace(tenant_id=scope.tenant_id, agent_id=scope.agent_id, user_id=scope.user_id),
        kind="episode",
        memory_id="episode",
        content_version="v1",
    )
    data.update(changes)
    with pytest.raises(ValueError, match="candidate memory ref"):
        MemoryCandidate.model_validate(data)


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
            relevant_skills="B" * 200,  # 50 tokens
            conversation="C" * 200,  # 50 tokens
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

    def test_whole_block_budget_and_digest(self):
        """Structured packing keeps complete blocks and hashes delivered text."""
        scope = _scope()
        assembler = ContextAssembler(
            MemoryConfig(
                max_context_tokens=80,
                episodic_weight=0.6,
                skill_weight=0.2,
                conversation_weight=0.2,
            )
        )
        candidates = [
            _candidate(scope, memory_id="episode-1", text="Use the authenticated endpoint.", relevance=0.9),
            _candidate(
                scope,
                memory_id="skill-1",
                text="Use the schema tool before querying.",
                source="skill",
                candidate_type="skill",
                relevance=0.8,
            ),
        ]

        context = assembler.assemble_candidates(candidates, scope=scope)

        assert context.episodic_warnings == "Use the authenticated endpoint."
        assert context.relevant_skills == "Use the schema tool before querying."
        assert context.tokens_used <= context.tokens_budget
        assert context.delivered_refs == (
            "episodic:episode-1:v1",
            "skill:skill-1:v1",
        )
        assert context.packed_digest == hashlib.sha256(context.to_prompt_string().encode("utf-8")).hexdigest()

    def test_trimmed_candidates_are_uncitable(self):
        """A candidate that cannot fit as a whole block has no delivered ref."""
        scope = _scope()
        assembler = ContextAssembler(
            MemoryConfig(
                max_context_tokens=20,
                episodic_weight=1.0,
                skill_weight=0.0,
                conversation_weight=0.0,
            )
        )
        candidates = [
            _candidate(scope, memory_id="too-large", text="X" * 200, relevance=1.0),
            _candidate(scope, memory_id="fits", text="A useful warning", relevance=0.5),
        ]

        context = assembler.assemble_candidates(candidates, scope=scope)

        assert "X" * 200 not in context.episodic_warnings
        assert context.delivered_refs == ("episodic:fits:v1",)
        assert "episodic:too-large:v1" not in context.delivered_refs

    def test_legacy_assemble_and_user_priority(self):
        """Scope filtering and user-context packing do not use experiential grades."""
        scope = _scope()
        other_scope = _scope(user_id="other-user")
        assembler = ContextAssembler(
            MemoryConfig(
                max_context_tokens=120,
                enable_user_memory=True,
                episodic_weight=0.3,
                skill_weight=0.2,
                conversation_weight=0.5,
                user_weight=0.3,
            )
        )
        context = assembler.assemble_candidates(
            [
                _candidate(
                    scope,
                    memory_id="user-fact",
                    text="The user prefers dark mode.",
                    source="user",
                    candidate_type="user",
                    relevance=0.9,
                    ranking_score=0.0,
                ),
                _candidate(
                    other_scope,
                    memory_id="cross-scope",
                    text="Do not deliver this.",
                    relevance=1.0,
                    ranking_score=1.0,
                ),
            ],
            scope=scope,
        )
        legacy = assembler.assemble(episodic_warnings="legacy warning")

        assert context.user_knowledge == "The user prefers dark mode."
        assert context.delivered_refs == ("user:user-fact:v1",)
        assert "cross-scope" not in context.to_prompt_string()
        assert legacy.episodic_warnings == "legacy warning"
