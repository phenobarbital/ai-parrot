"""Unit tests for CacheableSegment dataclass and PromptLayer.cacheable field.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1217).
"""
import pytest
from parrot.bots.prompts.segments import CacheableSegment
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase


class TestCacheableSegment:
    def test_creation(self):
        seg = CacheableSegment(text="hello", cacheable=True)
        assert seg.text == "hello"
        assert seg.cacheable is True
        assert seg.ttl_hint is None

    def test_ttl_hint(self):
        seg = CacheableSegment(text="x", cacheable=True, ttl_hint="long")
        assert seg.ttl_hint == "long"

    def test_ttl_hint_short(self):
        seg = CacheableSegment(text="x", cacheable=False, ttl_hint="short")
        assert seg.ttl_hint == "short"

    def test_frozen(self):
        seg = CacheableSegment(text="x", cacheable=True)
        with pytest.raises(AttributeError):
            seg.text = "y"  # type: ignore[misc]

    def test_not_cacheable(self):
        seg = CacheableSegment(text="dynamic", cacheable=False)
        assert seg.cacheable is False


class TestPromptLayerCacheable:
    def test_configure_phase_default_cacheable_true(self):
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x",
            phase=RenderPhase.CONFIGURE,
        )
        assert layer.cacheable is True

    def test_request_phase_default_cacheable_false(self):
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x",
            phase=RenderPhase.REQUEST,
        )
        assert layer.cacheable is False

    def test_default_phase_is_request(self):
        """Phase defaults to REQUEST when not specified."""
        layer = PromptLayer(name="test", priority=10, template="hi")
        assert layer.phase == RenderPhase.REQUEST
        assert layer.cacheable is False

    def test_explicit_override_configure_to_not_cacheable(self):
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x",
            phase=RenderPhase.CONFIGURE,
            cacheable=False,
        )
        assert layer.cacheable is False

    def test_explicit_override_request_to_cacheable(self):
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x",
            phase=RenderPhase.REQUEST,
            cacheable=True,
        )
        assert layer.cacheable is True

    def test_partial_render_propagates_cacheable_true(self):
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x $y",
            phase=RenderPhase.CONFIGURE,
            cacheable=True,
        )
        rendered = layer.partial_render({"x": "hello"})
        assert rendered.cacheable is True

    def test_partial_render_propagates_cacheable_false(self):
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x $y",
            phase=RenderPhase.CONFIGURE,
            cacheable=False,
        )
        rendered = layer.partial_render({"x": "hello"})
        assert rendered.cacheable is False

    def test_partial_render_phase_becomes_request(self):
        """partial_render always returns a REQUEST-phase layer."""
        layer = PromptLayer(
            name="test",
            priority=10,
            template="$x",
            phase=RenderPhase.CONFIGURE,
        )
        rendered = layer.partial_render({"x": "val"})
        assert rendered.phase == RenderPhase.REQUEST

    def test_builtin_layers_still_have_correct_cacheable(self):
        """All 8 built-in layers derive cacheable correctly from phase."""
        from parrot.bots.prompts.layers import (
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            OUTPUT_LAYER, BEHAVIOR_LAYER,
        )
        # CONFIGURE-phase layers should be cacheable
        assert IDENTITY_LAYER.cacheable is True
        assert PRE_INSTRUCTIONS_LAYER.cacheable is True
        assert SECURITY_LAYER.cacheable is True
        assert TOOLS_LAYER.cacheable is True
        assert BEHAVIOR_LAYER.cacheable is True
        # REQUEST-phase layers should NOT be cacheable
        assert KNOWLEDGE_LAYER.cacheable is False
        assert USER_SESSION_LAYER.cacheable is False
        assert OUTPUT_LAYER.cacheable is False


class TestImport:
    def test_cacheable_segment_importable_from_package(self):
        from parrot.bots.prompts import CacheableSegment
        seg = CacheableSegment(text="test", cacheable=True)
        assert seg.text == "test"
