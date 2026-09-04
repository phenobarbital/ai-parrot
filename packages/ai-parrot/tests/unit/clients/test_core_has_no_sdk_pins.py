"""TASK-2854: core's ``pyproject.toml`` no longer pins any SDK a satellite
now owns exclusively, and ``llms`` resolves to all 15 satellites.
"""
import pathlib
import tomllib

# .../packages/ai-parrot/tests/unit/clients/test_core_has_no_sdk_pins.py
# parents[3] == .../packages/ai-parrot
_CORE_PYPROJECT = pathlib.Path(__file__).resolve().parents[3] / "pyproject.toml"


def test_core_pins():
    py = tomllib.loads(_CORE_PYPROJECT.read_text())
    deps = " ".join(py["project"]["dependencies"])
    for sdk in ("anthropic", "google-genai", "groq", "xai-sdk", "zai-sdk", "aioboto3", "claude-agent-sdk"):
        assert sdk not in deps
    assert "openai" in deps and "tiktoken" in deps
    assert len(py["project"]["optional-dependencies"]["llms"]) == 15
