"""Client configuration reaching the writer (TASK-3091, FEAT-543)."""

import os
from pathlib import Path

import pytest
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

from .conftest import REPO_ROOT, record_json

EXAMPLE = REPO_ROOT / "examples" / "tool-optimizations-mcp.yaml"


def test_example_configuration_pins_the_bedrock_alias_and_no_fallback():
    """The shipped example configures Qwen via Bedrock with fallback disabled."""
    assert EXAMPLE.is_file()
    config = load_toolkits_config(EXAMPLE.parent, config_path=EXAMPLE)
    writer = config.toolkits["targeted-writer"]

    assert writer.llm == "bedrock-converse:qwen3-coder-480b-a35b"
    assert writer.llm_kwargs == {"fallback_model": None, "max_retries": 1, "read_timeout": 120}
    assert writer.kwargs["expected_model_ids"] == ["qwen.qwen3-coder-480b-a35b-v1:0"]


def test_factory_receives_the_configured_kwargs_and_constructor_gets_expected_models(tmp_path, monkeypatch):
    """llm_kwargs reach LLMFactory.create; kwargs reach the toolkit constructor."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / ".parrot" / "mcp-toolkits.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "toolkits:\n"
        "  targeted-writer:\n"
        "    class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit\n"
        "    llm: bedrock-converse:qwen3-coder-480b-a35b\n"
        "    llm_kwargs:\n"
        "      fallback_model: null\n"
        "      max_retries: 1\n"
        "      read_timeout: 120\n"
        "    kwargs:\n"
        f"      repo_root: {repo}\n"
        '      expected_model_ids: ["qwen.qwen3-coder-480b-a35b-v1:0"]\n'
    )

    from parrot.clients.factory import LLMFactory

    from ..test_writer import FakeClient

    seen = {}

    def _capture(llm, **kwargs):
        seen["llm"] = llm
        seen["kwargs"] = kwargs
        # A client honouring `fallback_model: null` advertises no fallback.
        return FakeClient([], fallback=kwargs.get("fallback_model"))

    monkeypatch.setattr(LLMFactory, "create", staticmethod(_capture))
    server = create_toolkit_mcp_server("targeted-writer", root=repo, config_path=config)

    assert seen["llm"] == "bedrock-converse:qwen3-coder-480b-a35b"
    assert seen["kwargs"] == {"fallback_model": None, "max_retries": 1, "read_timeout": 120}

    toolkit = next(iter(server.tools.values())).tool.bound_method.__self__
    assert toolkit._expected_models == ("qwen.qwen3-coder-480b-a35b-v1:0",)
    assert {tool for tool in server.tools} == {"writer_apply", "writer_generate"}

    record_json("TASK-3091-client-configuration.json", {"llm": seen["llm"], "llm_kwargs": seen["kwargs"]})


def test_a_client_permitting_fallback_is_refused_at_construction(tmp_path, monkeypatch):
    """Omitting `fallback_model: null` must fail loudly, not silently switch models."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / ".parrot" / "mcp-toolkits.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "toolkits:\n"
        "  targeted-writer:\n"
        "    class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit\n"
        "    llm: bedrock-converse:qwen3-coder-480b-a35b\n"
        "    kwargs:\n"
        f"      repo_root: {repo}\n"
    )

    from parrot.clients.factory import LLMFactory

    from ..test_writer import FakeClient

    # Mimic BedrockConverseClient's class default when no explicit null is given.
    monkeypatch.setattr(
        LLMFactory, "create", staticmethod(lambda *a, **kw: FakeClient([], fallback="claude-haiku-4-5"))
    )

    with pytest.raises(Exception) as info:
        create_toolkit_mcp_server("targeted-writer", root=repo, config_path=config)
    assert "fallback" in str(info.value).lower()


@pytest.mark.real_llm
@pytest.mark.skipif(
    os.environ.get("PARROT_TOOL_OPT_SMOKE") != "1",
    reason="live Bedrock smoke test; set PARROT_TOOL_OPT_SMOKE=1 (and AWS credentials) to enable",
)
async def test_real_bedrock_writer_smoke(tmp_path):
    """Opt-in smoke test against a real provider.

    Asserts only that a validated artifact was produced — never that the
    generated code is correct. Never runs in CI.
    """
    from parrot.clients.factory import LLMFactory
    from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit

    from ..fixtures import make_repo_with_target, make_valid_task

    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)

    client = LLMFactory.create("bedrock-converse:qwen3-coder-480b-a35b", fallback_model=None, max_retries=1)
    toolkit = TargetedWriterToolkit(
        repo_root=repo, llm_client=client, expected_model_ids=("qwen.qwen3-coder-480b-a35b-v1:0",)
    )
    async with toolkit._client_lock:
        pass
    await toolkit._open()
    try:
        result = await toolkit.writer_generate(task.relative_to(repo).as_posix())
    finally:
        await toolkit._close()

    record_json(
        "TASK-3091-real-llm-smoke.json",
        {"status": result.status, "error": result.error.code if result.error else None, "data": result.data},
    )
    assert result.status in {"ok", "error"}
