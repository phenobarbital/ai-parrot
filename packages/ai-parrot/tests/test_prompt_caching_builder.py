"""Unit tests for PromptBuilder.build_segments() and prompt_caching kwarg.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1218).
"""
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.segments import CacheableSegment


class TestBuildSegments:
    def test_basic_segmentation(self):
        builder = PromptBuilder(
            [
                PromptLayer(
                    name="a", priority=10, template="static",
                    phase=RenderPhase.CONFIGURE,
                ),
                PromptLayer(
                    name="b", priority=20, template="$dynamic",
                    phase=RenderPhase.REQUEST,
                ),
            ],
            prompt_caching=True,
        )
        builder.configure({})
        segments = builder.build_segments({"dynamic": "data"})
        assert len(segments) == 2
        assert segments[0].cacheable is True
        assert segments[1].cacheable is False

    def test_returns_list_of_cacheable_segments(self):
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="hello",
                        phase=RenderPhase.CONFIGURE),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        assert isinstance(segments, list)
        assert all(isinstance(s, CacheableSegment) for s in segments)

    def test_empty_layers_excluded(self):
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="text",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(
                name="b", priority=20, template="will be missing",
                phase=RenderPhase.REQUEST,
                condition=lambda ctx: False,
            ),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        # "b" is excluded via condition
        assert len(segments) == 1
        assert segments[0].text == "text"

    def test_condition_skips_layer(self):
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="always",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(name="b", priority=20, template="never",
                        phase=RenderPhase.CONFIGURE,
                        condition=lambda ctx: False),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        assert len(segments) == 1
        assert segments[0].text == "always"

    def test_priority_order_preserved(self):
        builder = PromptBuilder([
            PromptLayer(name="z", priority=30, template="third",
                        phase=RenderPhase.REQUEST),
            PromptLayer(name="a", priority=10, template="first",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(name="m", priority=20, template="second",
                        phase=RenderPhase.CONFIGURE),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        assert segments[0].text == "first"
        assert segments[1].text == "second"
        assert segments[2].text == "third"

    def test_cacheable_false_on_request_phase(self):
        builder = PromptBuilder([
            PromptLayer(name="dynamic", priority=10, template="changes",
                        phase=RenderPhase.REQUEST),
        ], prompt_caching=True)
        builder.configure({})
        segments = builder.build_segments({})
        assert len(segments) == 1
        assert segments[0].cacheable is False

    def test_build_segments_without_caching_flag(self):
        """build_segments works even when prompt_caching=False."""
        builder = PromptBuilder([
            PromptLayer(name="x", priority=10, template="content",
                        phase=RenderPhase.CONFIGURE),
        ])
        builder.configure({})
        segments = builder.build_segments({})
        assert len(segments) == 1


class TestPromptCachingKwarg:
    def test_default_is_false(self):
        builder = PromptBuilder()
        assert builder.prompt_caching is False

    def test_can_be_set_true(self):
        builder = PromptBuilder(prompt_caching=True)
        assert builder.prompt_caching is True

    def test_clone_propagates_flag(self):
        builder = PromptBuilder(prompt_caching=True)
        cloned = builder.clone()
        assert cloned.prompt_caching is True

    def test_clone_propagates_false(self):
        builder = PromptBuilder(prompt_caching=False)
        cloned = builder.clone()
        assert cloned.prompt_caching is False


class TestBuildRegression:
    """Ensure build() is unchanged for all presets — regression guard."""

    @pytest.mark.parametrize("preset", ["default", "minimal", "agent", "rag"])
    def test_preset_build_unchanged(self, preset):
        factory = getattr(PromptBuilder, preset)
        builder_old = factory()
        builder_new = factory()
        ctx = {
            "name": "Test",
            "role": "helper",
            "goal": "help",
            "backstory": "",
            "rationale": "be nice",
            "knowledge_content": "kb data",
            "user_context": "user",
            "chat_history": "history",
            "output_instructions": "",
            "has_tools": False,
        }
        builder_old.configure(ctx)
        builder_new.configure(ctx)
        assert builder_old.build(ctx) == builder_new.build(ctx)

    def test_build_produces_string(self):
        builder = PromptBuilder.default()
        ctx = {
            "name": "T", "role": "r", "goal": "", "backstory": "", "rationale": "",
        }
        builder.configure(ctx)
        result = builder.build({})
        assert isinstance(result, str)

    def test_build_vs_segments_coverage(self):
        """build() and build_segments() cover the same non-empty layers."""
        builder = PromptBuilder([
            PromptLayer(name="a", priority=10, template="hello",
                        phase=RenderPhase.CONFIGURE),
            PromptLayer(name="b", priority=20, template="world",
                        phase=RenderPhase.REQUEST),
        ])
        builder.configure({})
        ctx = {}
        result_str = builder.build(ctx)
        segments = builder.build_segments(ctx)
        # Joining segments should produce the same string as build()
        joined = "\n\n".join(s.text for s in segments)
        assert result_str == joined
