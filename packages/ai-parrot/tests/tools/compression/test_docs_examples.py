"""Doc-example validation test (TASK-1962).

Ensures the copy-pasteable `.parrot/compressors.toml` example in
`docs/tools/compression.md` actually parses and validates against the
shipped `CompressorConfig` schema — a stale doc example is worse than no
example.
"""
import re
import tomllib
from pathlib import Path

import parrot.tools.compression.codecs  # noqa: F401 — registers built-in codecs
from parrot.tools.compression.config import CompressorConfig


def _docs_root() -> Path:
    # packages/ai-parrot/tests/tools/compression/test_docs_examples.py
    # -> repo root is 5 levels up (compression, tools, tests, ai-parrot, packages)
    return Path(__file__).resolve().parents[5] / "docs"


def test_doc_toml_example_validates():
    """The copy-pasteable example in the docs must actually parse and
    validate against the shipped Pydantic schema."""
    doc = (_docs_root() / "tools" / "compression.md").read_text()
    match = re.search(r"```toml\n(.*?)```", doc, re.S)
    assert match, "expected at least one ```toml fenced block in the doc"
    block = match.group(1)

    parsed = tomllib.loads(block)
    cfg = CompressorConfig(**parsed)

    # Sanity: the example demonstrates BOTH an exact-match entry AND the
    # wildcard fallback, with a codec that is actually registered.
    assert "*" in cfg.compressor
    assert cfg.compressor["*"].codec == "json_compact"
