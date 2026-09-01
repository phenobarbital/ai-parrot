"""Configuration models and loader for local MCP toolkit servers.

FEAT-485: Toolkit configuration is read from `.parrot/mcp-toolkits.yaml` if present,
and merged over built-in defaults for `scraping`, `browsing`, and `memory`.
Each section names a toolkit class via dotted path and provides instantiation kwargs,
optional tool filtering via include/exclude, and optional LLM wiring.

The loader enforces Pydantic validation with clear error messages naming the file
and offending section/key.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ToolkitSection(BaseModel):
    """Configuration for a single exposable toolkit.

    Attributes:
        class_path: Dotted path to the AbstractToolkit subclass (e.g.,
            "parrot_tools.scraping.toolkit.WebScrapingToolkit"). Aliased as "class"
            in YAML and file dictionaries.
        enabled: Whether this toolkit is available for serving. Defaults to True.
            Disabled toolkits are retained in the config but not exposed by runners
            or installers.
        kwargs: Constructor keyword arguments for the toolkit instance.
            File sections replace the built-in kwargs dict wholesale (not merged).
        include: Optional whitelist of tool names to expose. If set, only these
            tools are exposed (exclude is ignored).
        exclude: Optional blacklist of tool names to exclude. Only used when
            include is None.
        llm: Optional LLM identifier string (e.g., "openai:gpt-4o", "anthropic:claude-3-opus").
            When set, the runner passes an LLMFactory-created client to the toolkit
            constructor as `llm_client`. When unset, tools named in the toolkit's
            `llm_dependent_tools` metadata are automatically excluded from exposure.
        env: Dictionary of environment variables to pass to the toolkit server process
            (via installer entries). Useful for API keys or secrets.
    """

    class_path: str = Field(..., alias="class")
    enabled: bool = True
    kwargs: dict[str, Any] = Field(default_factory=dict)
    include: list[str] | None = None
    exclude: list[str] | None = None
    llm: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class MCPToolkitsConfig(BaseModel):
    """Root configuration for all exposable toolkits.

    Attributes:
        toolkits: Dictionary mapping toolkit names to their configuration sections.
    """

    toolkits: dict[str, ToolkitSection] = Field(default_factory=dict)


BUILTIN_TOOLKITS: dict[str, ToolkitSection] = {
    "scraping": ToolkitSection(
        class_path="parrot_tools.scraping.toolkit.WebScrapingToolkit",
        kwargs={"headless": True, "plans_dir": ".parrot/scraping_plans"},
    ),
    "browsing": ToolkitSection(
        class_path="parrot_tools.browsing.toolkit.WebBrowsingToolkit",
        kwargs={"catalog_dir": ".parrot/browsing_catalog", "headless": True},
    ),
    "memory": ToolkitSection(
        class_path="parrot.tools.working_memory.tool.WorkingMemoryToolkit",
        kwargs={},
    ),
}


def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig:
    """Load and merge toolkit configuration.

    Reads `.parrot/mcp-toolkits.yaml` from the project root if present,
    and deep-merges sections over BUILTIN_TOOLKITS (file sections take precedence).

    For each section:
    - A file section with a built-in name replaces the built-in completely
      (kwargs and other fields are not merged — file kwargs replace builtin kwargs).
    - New sections in the file are appended to the config.
    - Disabled sections (enabled: false) are retained in the config for inspection
      and control; they are filtered by consumers (runners, installers).

    Args:
        root: Project root directory.
        config_path: Optional explicit config file path (the `parrot
            mcp-local --config` override). When given it is used instead of
            `<root>/.parrot/mcp-toolkits.yaml`, and — unlike the default
            path, whose absence silently falls back to the built-ins — a
            missing explicit file raises ValueError: an operator who named
            a file expects it to be read.

    Returns:
        MCPToolkitsConfig with merged sections.

    Raises:
        ValueError: If the file exists but is malformed YAML, contains unknown
            top-level keys, or has a non-mapping `toolkits:` value — or if an
            explicit `config_path` does not exist. Error message names the
            file path and the offending section/key.
    """
    explicit = config_path is not None
    if config_path is None:
        config_path = root / ".parrot" / "mcp-toolkits.yaml"
    else:
        config_path = Path(config_path)

    # Start with built-in defaults (these will be overridden by file sections)
    merged: dict[str, ToolkitSection] = {name: section.model_copy() for name, section in BUILTIN_TOOLKITS.items()}

    # If file does not exist: builtins only for the default path; an
    # explicitly named file that is absent is operator error.
    if not config_path.exists():
        if explicit:
            raise ValueError(f"Toolkit config file not found: {config_path}")
        return MCPToolkitsConfig(toolkits=merged)

    # Load and parse YAML
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML at {config_path}: {e}") from e

    # Handle empty/None YAML document
    if data is None:
        data = {}

    # Validate root structure
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML at {config_path} to be a mapping (dict), " f"got {type(data).__name__}")

    # Check for unknown top-level keys
    unknown_keys = set(data.keys()) - {"toolkits"}
    if unknown_keys:
        raise ValueError(f"Unknown top-level keys in {config_path}: {unknown_keys}. " f"Expected only 'toolkits'.")

    # Extract and validate toolkits section
    toolkits_data = data.get("toolkits", {})
    if toolkits_data is None:
        toolkits_data = {}

    if not isinstance(toolkits_data, dict):
        raise ValueError(
            f"Expected 'toolkits:' at {config_path} to be a mapping (dict), " f"got {type(toolkits_data).__name__}"
        )

    # Parse and merge file sections
    for toolkit_name, toolkit_dict in toolkits_data.items():
        try:
            # Allow both 'class' (YAML-style) and 'class_path' (Python-style)
            section = ToolkitSection.model_validate(toolkit_dict)
            merged[toolkit_name] = section
        except Exception as e:
            raise ValueError(f"Failed to validate toolkit '{toolkit_name}' in {config_path}: {e}") from e

    return MCPToolkitsConfig(toolkits=merged)
