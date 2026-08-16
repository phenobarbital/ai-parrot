"""Unit tests for the compression contract primitives (TASK-1947)."""
import pytest

from parrot.tools.compression import (
    CompressionOutcome,
    FilterLevel,
    ResultCompressor,
    get_codec,
    known_codecs,
    register_codec,
)
from parrot.tools.compression.levels import cap


class TestFilterLevel:
    def test_default_is_minimal(self):
        assert FilterLevel("minimal") is FilterLevel.MINIMAL

    def test_str_enum_serializes_to_toml_value(self):
        assert FilterLevel.AGGRESSIVE == "aggressive"

    @pytest.mark.parametrize("level,ceiling,expected", [
        (FilterLevel.AGGRESSIVE, FilterLevel.MINIMAL, FilterLevel.MINIMAL),
        (FilterLevel.NONE, FilterLevel.AGGRESSIVE, FilterLevel.NONE),
        (FilterLevel.NORMAL, FilterLevel.NORMAL, FilterLevel.NORMAL),
    ])
    def test_cap(self, level, ceiling, expected):
        assert cap(level, ceiling) is expected

    def test_cap_all_16_pairs(self):
        levels = [
            FilterLevel.NONE,
            FilterLevel.MINIMAL,
            FilterLevel.NORMAL,
            FilterLevel.AGGRESSIVE,
        ]
        order = {lvl: i for i, lvl in enumerate(levels)}
        for level in levels:
            for ceiling in levels:
                result = cap(level, ceiling)
                expected = level if order[level] <= order[ceiling] else ceiling
                assert result is expected


class TestCodecRegistry:
    def test_register_and_get(self):
        @register_codec
        class _Dummy:
            codec_name = "dummy_test"

            def compress(self, result, *, level, params):
                return CompressionOutcome(
                    payload=result, lossy=False, bytes_before=1,
                    bytes_after=1, est_tokens_saved=0, codec_name="dummy_test",
                )
        try:
            assert get_codec("dummy_test") is _Dummy
            assert "dummy_test" in known_codecs()
            assert isinstance(_Dummy(), ResultCompressor)
        finally:
            from parrot.tools.compression.protocol import _CODEC_REGISTRY
            _CODEC_REGISTRY.pop("dummy_test", None)

    def test_duplicate_name_raises(self):
        @register_codec
        class _Clash:
            codec_name = "dummy_clash"

            def compress(self, result, *, level, params):
                ...
        try:
            with pytest.raises(ValueError, match="dummy_clash"):
                @register_codec
                class _Clash2:
                    codec_name = "dummy_clash"

                    def compress(self, result, *, level, params):
                        ...
        finally:
            from parrot.tools.compression.protocol import _CODEC_REGISTRY
            _CODEC_REGISTRY.pop("dummy_clash", None)

    def test_unknown_codec_returns_none(self):
        assert get_codec("nope-not-registered") is None


def test_no_import_cycle_with_manager():
    """compression must be importable without pulling in ToolManager."""
    import subprocess
    import sys
    code = (
        "import parrot.tools.compression, sys;"
        "assert 'parrot.tools.manager' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code])
    assert result.returncode == 0
