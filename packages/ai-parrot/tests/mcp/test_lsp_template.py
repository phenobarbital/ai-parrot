"""Packaged `lsp` toolkit template and operator documentation (FEAT-580, M4).

Spec §3 Module 4 / §4 "Unit Tests" (`test_template_is_explicit_and_root_scoped`):
the template must be discoverable, explicit (no implicit resolution), root
scoped through the same `{{repo_root}}` mechanism as every other packaged
template, and must never spawn Pyright or scan source during import, listing
or installation. `examples/lsp-mcp.yaml` must independently reproduce the
same class/config shape with a safe sentinel default.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections
from parrot_tools.lsp.models import OPERATOR_UNCONFIGURED_ENVIRONMENT_ID, LSPConfig
from parrot_tools.lsp.toolkit import LSPToolkit

_EXPECTED_TOOL_NAMES = {"lsp_definition", "lsp_references", "lsp_diagnostics", "lsp_diagnostic_delta"}

_EXAMPLE_PATH = Path(__file__).resolve().parents[4] / "examples" / "lsp-mcp.yaml"


def test_template_is_explicit_and_root_scoped(tmp_path):
    """`lsp` is packaged, explicit, requires no LLM, and renders {{repo_root}}."""
    assert "lsp" in available_templates()

    template = load_template("lsp")
    assert template.requires_llm is False
    assert template.requires_dist == ("parrot_tools",)
    assert "{{repo_root}}" in template.body
    assert "class: parrot_tools.lsp.toolkit.LSPToolkit" in template.body
    assert f"environment_id: {OPERATOR_UNCONFIGURED_ENVIRONMENT_ID}" in template.body

    # Nothing is resolved implicitly: the section only exists once seeded.
    empty_cfg = load_toolkits_config(tmp_path)
    assert "lsp" not in empty_cfg.toolkits

    result = seed_toolkit_sections(tmp_path, ["lsp"])
    assert result.added == ["lsp"]
    assert "{{repo_root}}" not in (tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8")

    cfg = load_toolkits_config(tmp_path)
    section = cfg.toolkits["lsp"]
    assert section.class_path == "parrot_tools.lsp.toolkit.LSPToolkit"
    assert section.llm is None

    # Nested kwargs.config.repo_root is rendered to THIS worktree/tmp_path, not
    # left as a placeholder and not copied from anywhere else.
    rendered_config = section.kwargs["config"]
    assert rendered_config["repo_root"] == str(tmp_path)
    assert rendered_config["environment_id"] == OPERATOR_UNCONFIGURED_ENVIRONMENT_ID

    # A second seed request is a no-op (existing sections are never rewritten).
    second = seed_toolkit_sections(tmp_path, ["lsp"])
    assert second.skipped == ["lsp"]
    assert second.added == []


def test_lsp_template_no_startup_on_install_or_list(tmp_path, monkeypatch):
    """Import, template listing, installation and construction never spawn a process."""

    async def _forbidden_subprocess_exec(*args, **kwargs):  # noqa: ANN001 - test guard
        raise AssertionError(f"unexpected subprocess spawn during install/list: {args!r}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _forbidden_subprocess_exec)

    # Listing/discovery never touches the guarded subprocess hook.
    assert "lsp" in available_templates()
    load_template("lsp")

    # Installation renders and validates the section but never instantiates
    # the toolkit class, let alone starts a server.
    result = seed_toolkit_sections(tmp_path, ["lsp"])
    assert result.added == ["lsp"]

    cfg = load_toolkits_config(tmp_path)
    section = cfg.toolkits["lsp"]

    # Constructing the toolkit only validates the trusted LSPConfig in memory
    # (spec §2 "New Public Interfaces": construction never spawns a server,
    # opens a file, or probes an executable).
    toolkit = LSPToolkit(**section.kwargs)
    tools = toolkit.get_tools()
    assert {tool.name for tool in tools} == _EXPECTED_TOOL_NAMES

    # Adversarial: an operator-unconfigured environment_id must still resolve
    # to a valid LSPConfig without ever reaching the guarded subprocess hook.
    assert toolkit._config.environment_id == OPERATOR_UNCONFIGURED_ENVIRONMENT_ID


def test_example_configuration_and_tool_names(tmp_path):
    """`examples/lsp-mcp.yaml` mirrors the packaged template with a safe sentinel."""
    assert _EXAMPLE_PATH.is_file(), f"expected example file at {_EXAMPLE_PATH}"

    text = _EXAMPLE_PATH.read_text(encoding="utf-8")
    rendered = text.replace("{{repo_root}}", str(tmp_path))
    data = yaml.safe_load(rendered)

    assert "toolkits" in data
    lsp_section = data["toolkits"]["lsp"]
    assert lsp_section["class"] == "parrot_tools.lsp.toolkit.LSPToolkit"

    config = lsp_section["kwargs"]["config"]
    assert config["repo_root"] == str(tmp_path)
    # Safe sentinel default: an operator copying this example verbatim never
    # accidentally starts a real Pyright process.
    assert config["environment_id"] == OPERATOR_UNCONFIGURED_ENVIRONMENT_ID

    # The example's config resolves to a valid LSPConfig...
    lsp_config = LSPConfig(**config)
    assert lsp_config.repo_root == tmp_path

    # ...and constructing the toolkit from it exposes exactly the four
    # documented tools, matching the hash/column-convention doc's table.
    toolkit = LSPToolkit(config=lsp_config)
    assert {tool.name for tool in toolkit.get_tools()} == _EXPECTED_TOOL_NAMES

    # Adversarial: a malformed example (missing repo_root) must fail loudly,
    # not silently default somewhere unexpected.
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, exact type not load-bearing here
        LSPConfig(**{k: v for k, v in config.items() if k != "repo_root"})
