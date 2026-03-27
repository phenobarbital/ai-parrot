# Brainstorm: AI-Parrot Monorepo Workspace Migration

**Status:** Brainstorm  
**Date:** 2026-03-22  
**Author:** Jesus / Claude  
**Goal:** Split `ai-parrot` into multiple distributable packages (`ai-parrot`, `ai-parrot-tools`, `ai-parrot-loaders`) within a single monorepo using `uv` workspaces, maintaining backward-compatible imports and lazy discovery.

---

## 1. Problem Statement

`ai-parrot` has grown to 100+ tools/toolkits and heavy loaders. A regular user doesn't need all of them, but separating into multiple repos introduces friction (cross-repo PRs, versioning, `uv sources` for local dev). We need modularization without multi-repo pain.

---

## 2. Solution: Monorepo with `uv` Workspaces

### 2.1 Directory Structure

The root directory for sub-packages is called **`packages/`** (not `src/`). Rationale: `src/` is ambiguous — it could mean "source code" of any single package. `packages/` clearly signals "this contains multiple distributable packages."

Each sub-package uses the **`src/` layout internally** because:
- It prevents accidental imports from the working directory (Python won't find `parrot/` without install)
- `uv` and `pip` handle `src/` layout natively via `[tool.setuptools.packages.find]`
- It's the PEP 517/518 recommended layout for distributable packages

```
ai-parrot/                          # repo root
├── pyproject.toml                  # workspace root (NOT a package itself)
├── uv.lock
├── packages/
│   ├── ai-parrot/                  # core package
│   │   ├── pyproject.toml          # name = "ai-parrot"
│   │   └── src/
│   │       └── parrot/
│   │           ├── __init__.py
│   │           ├── clients/
│   │           ├── agents/
│   │           ├── bots/
│   │           ├── registry/
│   │           ├── stores/
│   │           ├── mcp/
│   │           ├── tools/
│   │           │   ├── __init__.py      # PROXY module (see §4)
│   │           │   ├── abstract.py      # AbstractTool, AbstractToolkit (stays in core)
│   │           │   ├── toolkit.py       # AbstractToolkit base
│   │           │   ├── manager.py       # ToolManager (stays in core)
│   │           │   ├── discovery.py     # Multi-source discovery (NEW, see §5)
│   │           │   └── base_tools.py    # Core tools that have zero extra deps (optional)
│   │           └── loaders/
│   │               └── __init__.py      # PROXY module (same pattern as tools)
│   │
│   ├── ai-parrot-tools/            # tools & toolkits package
│   │   ├── pyproject.toml          # name = "ai-parrot-tools"
│   │   └── src/
│   │       └── parrot_tools/
│   │           ├── __init__.py     # TOOL_REGISTRY dict + metadata
│   │           ├── jira/
│   │           │   ├── __init__.py
│   │           │   └── toolkit.py  # JiraToolkit
│   │           ├── slack/
│   │           ├── aws/
│   │           ├── docker/
│   │           ├── git/
│   │           ├── openapi/
│   │           ├── sitesearch/
│   │           ├── pulumi/
│   │           ├── analysis/
│   │           ├── codeinterpreter/
│   │           ├── excel/
│   │           ├── msword/
│   │           ├── sandbox/
│   │           └── ...             # 100+ tools
│   │
│   └── ai-parrot-loaders/          # loaders package
│       ├── pyproject.toml          # name = "ai-parrot-loaders"
│       └── src/
│           └── parrot_loaders/
│               ├── __init__.py     # LOADER_REGISTRY dict
│               ├── youtube/
│               ├── web/
│               ├── pdf/
│               ├── markdown/
│               ├── audio/          # whisperx, pyannote (heavy)
│               └── ...
│
├── plugins/                        # user/deploy-time plugins (existing)
│   └── tools/
├── tests/
├── sdd/
└── agents/
```

### 2.2 Why `packages/` and not `src/`

| Option | Pros | Cons |
|--------|------|------|
| `packages/` | Clear semantics, no ambiguity with inner `src/` | Slightly longer path |
| `src/` | Common in single-package repos | Confusing: `src/ai-parrot/src/parrot/` — two `src/` levels |
| Root-level (flat) | Shortest paths | Messy root directory, hard to manage with >2 packages |

**Decision:** `packages/`

### 2.3 Why inner `src/` layout

Each package uses `packages/<pkg>/src/<import_name>/` because:
1. **Prevents editable-install confusion**: Without `src/`, Python can import from the working directory even without installing, masking missing dependencies
2. **uv native support**: `uv` handles `src/` layout via standard `[tool.setuptools.packages.find]` config
3. **Industry standard**: setuptools, flit, hatch, maturin all support this layout

---

## 3. Workspace Configuration

### 3.1 Root `pyproject.toml`

This file is **not** a package — it only declares the workspace:

```toml
[project]
name = "ai-parrot-workspace"
version = "0.0.0"
requires-python = ">=3.11"

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "mypy>=1.10",
]

# Shared tool configs
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
log_cli = true
log_cli_level = "DEBUG"

[tool.ruff]
line-length = 120

[tool.mypy]
python_version = "3.11"
warn_return_any = true
```

### 3.2 Core Package: `packages/ai-parrot/pyproject.toml`

```toml
[project]
name = "ai-parrot"
version = "0.45.0"
requires-python = ">=3.11"
description = "AI-Parrot: Framework for LLM agents, chatbots, and multi-agent orchestration"
dependencies = [
    # Core deps only — no tool-specific deps
    "aiohttp>=3.9",
    "pydantic>=2.0",
    "asyncpg>=0.29",
    "jinja2>=3.1",
    # ... existing core deps
]

[project.optional-dependencies]
embeddings = [
    "sentence-transformers>=5.0.0",
    "tiktoken>=0.9.0",
    # ...
]
charts = ["matplotlib>=3.7", "cairosvg>=2.7"]
# Keep optional groups that are core-level

[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]

[tool.setuptools.package-data]
parrot = ["py.typed"]

[tool.maturin]
python-source = "src/parrot/yaml_rs"
module-name = "parrot.yaml_rs._yaml_rs"
bindings = "pyo3"
features = ["pyo3/extension-module"]
```

### 3.3 Tools Package: `packages/ai-parrot-tools/pyproject.toml`

```toml
[project]
name = "ai-parrot-tools"
version = "0.45.0"
requires-python = ">=3.11"
description = "Tools and toolkits for AI-Parrot agents"
dependencies = [
    "ai-parrot>=0.45.0",  # core dependency
]

[project.optional-dependencies]
jira = ["jira>=3.10"]
slack = ["slack-sdk>=3.0"]
aws = ["boto3>=1.28"]
docker = ["docker>=7.1"]
git = ["gitpython>=3.1"]
openapi = ["httpx>=0.27"]
analysis = ["pandas>=2.0", "numpy>=1.26"]
excel = ["openpyxl>=3.1", "odfpy>=1.4"]
sandbox = ["docker>=7.1"]
codeinterpreter = ["docker>=7.1"]
pulumi = ["pulumi>=3.0"]
sitesearch = ["beautifulsoup4>=4.12", "html2text>=2024.0"]
office365 = ["msgraph-sdk>=1.8", "azure-identity>=1.18"]
# Meta-group: install everything
all = [
    "ai-parrot-tools[jira,slack,aws,docker,git,openapi,analysis,excel,sandbox,codeinterpreter,pulumi,sitesearch,office365]"
]

[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot_tools*"]

# Local dev: resolve ai-parrot from workspace
[tool.uv.sources]
ai-parrot = { workspace = true }
```

### 3.4 Loaders Package: `packages/ai-parrot-loaders/pyproject.toml`

```toml
[project]
name = "ai-parrot-loaders"
version = "0.45.0"
requires-python = ">=3.11"
description = "Document loaders for AI-Parrot RAG pipelines"
dependencies = [
    "ai-parrot>=0.45.0",
]

[project.optional-dependencies]
youtube = ["pytube>=15.0", "youtube_transcript_api>=1.0", "yt-dlp>=2026.2"]
audio = ["whisperx>=3.4", "pyannote-audio>=3.4", "av>=15.0"]
pdf = ["paddleocr>=3.2"]
web = ["beautifulsoup4>=4.12", "html2text>=2024.0"]
ebook = ["ebooklib>=0.19"]
all = ["ai-parrot-loaders[youtube,audio,pdf,web,ebook]"]

[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot_loaders*"]

[tool.uv.sources]
ai-parrot = { workspace = true }
```

### 3.5 Local Development with `tool.uv.sources`

Yes, `tool.uv.sources` with `workspace = true` is exactly how local dev works. When you run `uv sync` in the workspace root, `uv`:
1. Reads the workspace definition from root `pyproject.toml`
2. Resolves `ai-parrot = { workspace = true }` to `packages/ai-parrot/` (editable)
3. Installs all packages as editable symlinks

For development:
```bash
# Install everything (editable) from workspace root
uv sync --all-packages

# Install specific package with extras
uv sync --package ai-parrot-tools --extra jira --extra slack

# Run tests across workspace
uv run pytest tests/
```

When publishing to PyPI, `tool.uv.sources` is **ignored** — `ai-parrot>=0.45.0` resolves from PyPI normally.

---

## 4. Import Proxy: `parrot/tools/__init__.py`

This is the backward-compatibility layer. Users keep writing `from parrot.tools.jira import JiraToolkit` even though the code lives in `parrot_tools.jira`.

### 4.1 Chain-of-Resolution Proxy

```python
# packages/ai-parrot/src/parrot/tools/__init__.py
"""
Proxy module for backward-compatible tool imports.

Resolution chain:
1. parrot_tools (ai-parrot-tools package — installed)
2. parrot.tools._core (tools that live in core, if any)
3. plugins.tools (user/deploy-time plugins directory)
4. TOOL_REGISTRY (declarative registry from ai-parrot-tools)
"""
import importlib
import sys
from typing import Optional

# Resolution chain: ordered by priority (first match wins)
TOOL_SOURCES = [
    "parrot_tools",       # ai-parrot-tools installed package
    "plugins.tools",      # user plugin directory
]


def _resolve_from_sources(name: str) -> Optional[object]:
    """Try to import `name` from each source in order."""
    for source in TOOL_SOURCES:
        try:
            mod = importlib.import_module(f"{source}.{name}")
            return mod
        except ImportError:
            continue
    return None


def _resolve_from_registry(name: str) -> Optional[object]:
    """Fallback: resolve from TOOL_REGISTRY in parrot_tools."""
    try:
        from parrot_tools import TOOL_REGISTRY
    except ImportError:
        return None

    dotted_path = TOOL_REGISTRY.get(name)
    if not dotted_path:
        return None

    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def __getattr__(name: str):
    # Skip dunder/private names
    if name.startswith("_"):
        raise AttributeError(name)

    # Try source chain first
    result = _resolve_from_sources(name)
    if result is not None:
        # Cache in module to avoid repeated __getattr__ calls
        setattr(sys.modules[__name__], name, result)
        return result

    # Fallback to registry (class-level resolution)
    result = _resolve_from_registry(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result

    raise ImportError(
        f"Tool '{name}' not found. "
        f"Install with: uv pip install ai-parrot-tools  or  "
        f"uv pip install ai-parrot-tools[{name}]"
    )


# Re-export base classes (these stay in core)
from parrot.tools.abstract import AbstractTool  # noqa: F401, E402
from parrot.tools.toolkit import AbstractToolkit  # noqa: F401, E402
from parrot.tools.manager import ToolManager  # noqa: F401, E402
```

### 4.2 Same Pattern for Loaders

```python
# packages/ai-parrot/src/parrot/loaders/__init__.py
"""Proxy module for backward-compatible loader imports."""
import importlib
import sys

LOADER_SOURCES = [
    "parrot_loaders",     # ai-parrot-loaders installed package
    "plugins.loaders",    # user plugin directory
]


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)

    for source in LOADER_SOURCES:
        try:
            mod = importlib.import_module(f"{source}.{name}")
            setattr(sys.modules[__name__], name, mod)
            return mod
        except ImportError:
            continue

    # Fallback to registry
    try:
        from parrot_loaders import LOADER_REGISTRY
        dotted_path = LOADER_REGISTRY.get(name)
        if dotted_path:
            module_path, class_name = dotted_path.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            setattr(sys.modules[__name__], name, cls)
            return cls
    except ImportError:
        pass

    raise ImportError(
        f"Loader '{name}' not found. "
        f"Install with: uv pip install ai-parrot-loaders"
    )
```

### 4.3 Performance Notes

- `__getattr__` only fires when the attribute doesn't exist in the module
- `setattr(sys.modules[__name__], name, result)` caches the result — subsequent accesses bypass `__getattr__` entirely (dict lookup, nanoseconds)
- `importlib.import_module()` caches in `sys.modules` — second import of same module is a dict lookup
- **Net runtime overhead after first access: zero**
- Startup cost: only the tools actually imported are loaded; unused tools never touch disk

---

## 5. ToolManager Multi-Source Discovery

### 5.1 Discovery Module

```python
# packages/ai-parrot/src/parrot/tools/discovery.py
"""
Multi-source tool discovery for ToolManager.

Two strategies:
1. FAST (declarative): Read TOOL_REGISTRY dicts from each source — no imports needed
2. FULL (walk): pkgutil.walk_packages — imports everything, finds all AbstractTool subclasses

Default: FAST for installed packages, FULL for plugins/ only.
"""
import importlib
import pkgutil
import inspect
import logging
from typing import Dict, Optional, Type, Callable, Union

from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger("parrot.tools.discovery")

# Default sources for discovery
DEFAULT_SOURCES = [
    "parrot_tools",       # ai-parrot-tools package
    "plugins.tools",      # user plugins
]

# Sources that use walk_packages (slow but automatic)
WALK_SOURCES = {"plugins.tools"}


def discover_from_registry(
    sources: list[str] | None = None,
) -> Dict[str, str]:
    """
    Fast discovery: read TOOL_REGISTRY dicts from package __init__.py.

    Returns:
        Dict[tool_name, dotted_path_to_class]
    """
    sources = sources or DEFAULT_SOURCES
    registry: Dict[str, str] = {}

    for source in sources:
        if source in WALK_SOURCES:
            continue  # Skip walk-only sources

        try:
            package = importlib.import_module(source)
        except ImportError:
            logger.debug(f"Source '{source}' not installed, skipping")
            continue

        declared = getattr(package, "TOOL_REGISTRY", None)
        if declared and isinstance(declared, dict):
            registry.update(declared)
            logger.debug(
                f"Loaded {len(declared)} tools from {source}.TOOL_REGISTRY"
            )

    return registry


def discover_from_walk(
    sources: list[str] | None = None,
    filter_fn: Callable[[type], bool] | None = None,
) -> Dict[str, Type[Union[AbstractTool, AbstractToolkit]]]:
    """
    Full discovery: walk packages and find all AbstractTool/AbstractToolkit subclasses.
    Used for plugins/ where maintaining a registry is impractical.

    Returns:
        Dict[tool_name, tool_class]
    """
    sources = sources or list(WALK_SOURCES)
    registry: Dict[str, Type] = {}

    for source in sources:
        try:
            package = importlib.import_module(source)
        except ImportError:
            continue

        if not hasattr(package, "__path__"):
            continue

        for _importer, module_name, _is_pkg in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{source}.",
        ):
            try:
                mod = importlib.import_module(module_name)
            except ImportError as e:
                logger.debug(f"Skipping {module_name}: {e}")
                continue

            for attr_name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, (AbstractTool, AbstractToolkit))
                    and obj not in (AbstractTool, AbstractToolkit)
                    and not getattr(obj, "_abstract", False)
                ):
                    if filter_fn and not filter_fn(obj):
                        continue
                    tool_name = getattr(obj, "name", attr_name)
                    registry[tool_name] = obj

    return registry


def discover_all(
    sources: list[str] | None = None,
) -> Dict[str, Union[str, Type]]:
    """
    Combined discovery: fast registry + walk for plugins.

    Returns dict where values are either:
    - str (dotted path, from registry — lazy, not yet imported)
    - Type (class, from walk — already imported)
    """
    registry: Dict[str, Union[str, Type]] = {}

    # Phase 1: Fast declarative registries
    registry.update(discover_from_registry(sources))

    # Phase 2: Walk plugins (slower but automatic)
    walk_sources = [s for s in (sources or DEFAULT_SOURCES) if s in WALK_SOURCES]
    if walk_sources:
        walked = discover_from_walk(walk_sources)
        registry.update({name: cls for name, cls in walked.items()})

    logger.info(f"Discovered {len(registry)} tools total")
    return registry
```

### 5.2 Updated ToolManager

```python
# packages/ai-parrot/src/parrot/tools/manager.py (relevant changes)
from parrot.tools.discovery import discover_all, DEFAULT_SOURCES

class ToolManager:
    """
    Tool manager with multi-source lazy discovery.
    """

    def __init__(
        self,
        sources: list[str] | None = None,
        lazy: bool = True,
    ):
        self._sources = sources or DEFAULT_SOURCES
        self._registry: Dict[str, Union[str, Type]] = {}  # name → dotted_path | class
        self._instances: Dict[str, AbstractTool] = {}
        self._discovered = False
        self._tools: Dict[str, AbstractTool] = {}  # backward compat

        if not lazy:
            self._discover()

    def _discover(self):
        """Run multi-source discovery (idempotent)."""
        if not self._discovered:
            self._registry = discover_all(self._sources)
            self._discovered = True

    def _resolve_class(self, name: str) -> Type[AbstractTool]:
        """Resolve a registry entry to an actual class."""
        entry = self._registry.get(name)
        if entry is None:
            raise KeyError(f"Tool '{name}' not found in registry")

        if isinstance(entry, str):
            # Lazy: dotted path → import now
            module_path, class_name = entry.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            # Replace string with class for future lookups
            self._registry[name] = cls
            return cls
        else:
            # Already a class (from walk discovery)
            return entry

    def get_tool(self, name: str, **kwargs) -> AbstractTool:
        """Get or create a tool instance by name."""
        self._discover()

        if name not in self._instances:
            cls = self._resolve_class(name)
            self._instances[name] = cls(**kwargs)

        return self._instances[name]

    def available_tools(self) -> list[str]:
        """List all discoverable tool names."""
        self._discover()
        return list(self._registry.keys())

    # ... rest of existing ToolManager methods (register_tool, register_toolkit, etc.)
    # remain unchanged — they work on self._tools which is the runtime registry
```

---

## 6. TOOL_REGISTRY & Generation Script

### 6.1 Registry Format

```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
"""
AI-Parrot Tools & Toolkits package.

TOOL_REGISTRY maps tool names to their dotted import paths.
This enables lazy discovery without importing any tool modules at startup.

Auto-generated by: scripts/generate_tool_registry.py
Manual additions are also supported — the script preserves manual entries.
"""

TOOL_REGISTRY: dict[str, str] = {
    # --- Toolkits ---
    "jira": "parrot_tools.jira.toolkit.JiraToolkit",
    "zipcode": "parrot_tools.zipcode.toolkit.ZipcodeAPIToolkit",
    "git": "parrot_tools.git.toolkit.GitToolkit",
    "openapi": "parrot_tools.openapi.toolkit.OpenAPIToolkit",
    "query": "parrot_tools.query.toolkit.QueryToolkit",
    "sitesearch": "parrot_tools.sitesearch.toolkit.SiteSearchToolkit",
    "pulumi": "parrot_tools.pulumi.toolkit.PulumiToolkit",
    "docker": "parrot_tools.docker.toolkit.DockerToolkit",

    # --- Individual Tools ---
    "google_search": "parrot_tools.google.GoogleSearchTool",
    "wikipedia_search": "parrot_tools.wikipedia.WikipediaTool",
    "gvisor_python_sandbox": "parrot_tools.sandbox.sandboxtool.GVisorSandboxTool",
    "code_interpreter": "parrot_tools.codeinterpreter.tool.CodeInterpreterTool",
    "excel_generator": "parrot_tools.excel.ExcelTool",
    "word_generator": "parrot_tools.msword.WordTool",
    "word_to_markdown": "parrot_tools.msword.WordToMarkdownTool",
    # ... auto-generated entries continue
}
```

### 6.2 Generation Script

```python
#!/usr/bin/env python3
"""
scripts/generate_tool_registry.py

Scans parrot_tools/ for AbstractTool and AbstractToolkit subclasses
and generates/updates the TOOL_REGISTRY in parrot_tools/__init__.py.

Usage:
    python scripts/generate_tool_registry.py [--dry-run] [--verbose]

Options:
    --dry-run     Print changes without writing
    --verbose     Show all discovered tools
    --check       Exit with error if registry is out of date (for CI)
"""
import argparse
import importlib
import inspect
import pkgutil
import sys
import re
from pathlib import Path
from typing import Dict, Tuple

# Add packages to path for local dev
REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_PKG_SRC = REPO_ROOT / "packages" / "ai-parrot-tools" / "src"
CORE_PKG_SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
sys.path.insert(0, str(TOOLS_PKG_SRC))
sys.path.insert(0, str(CORE_PKG_SRC))

from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit

INIT_FILE = TOOLS_PKG_SRC / "parrot_tools" / "__init__.py"

# Marker comments in __init__.py
REGISTRY_START = "TOOL_REGISTRY: dict[str, str] = {"
REGISTRY_END = "}"


def scan_tools() -> Dict[str, str]:
    """Walk parrot_tools/ and find all tool/toolkit classes."""
    import parrot_tools

    registry: Dict[str, str] = {}

    for _importer, module_name, _is_pkg in pkgutil.walk_packages(
        parrot_tools.__path__,
        prefix="parrot_tools.",
    ):
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            print(f"  SKIP {module_name}: {e}")
            continue

        for attr_name, obj in inspect.getmembers(mod, inspect.isclass):
            if obj.__module__ != module_name:
                continue  # Skip re-exports

            if not issubclass(obj, (AbstractTool, AbstractToolkit)):
                continue
            if obj in (AbstractTool, AbstractToolkit):
                continue
            if getattr(obj, "_abstract", False):
                continue

            tool_name = getattr(obj, "name", None)
            if not tool_name:
                continue

            dotted_path = f"{module_name}.{attr_name}"
            registry[tool_name] = dotted_path

    return registry


def format_registry(registry: Dict[str, str]) -> str:
    """Format registry as Python dict literal."""
    # Separate toolkits and tools
    toolkits = {}
    tools = {}

    for name, path in sorted(registry.items()):
        if "Toolkit" in path.rsplit(".", 1)[-1]:
            toolkits[name] = path
        else:
            tools[name] = path

    lines = ['TOOL_REGISTRY: dict[str, str] = {']
    lines.append('    # --- Toolkits (auto-generated) ---')
    for name, path in sorted(toolkits.items()):
        lines.append(f'    "{name}": "{path}",')

    lines.append('')
    lines.append('    # --- Individual Tools (auto-generated) ---')
    for name, path in sorted(tools.items()):
        lines.append(f'    "{name}": "{path}",')

    lines.append('}')
    return '\n'.join(lines)


def update_init_file(new_registry_block: str, dry_run: bool = False) -> bool:
    """Replace TOOL_REGISTRY block in __init__.py."""
    content = INIT_FILE.read_text()

    # Find and replace the TOOL_REGISTRY block
    pattern = r'TOOL_REGISTRY: dict\[str, str\] = \{.*?\}'
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("ERROR: Could not find TOOL_REGISTRY block in __init__.py")
        return False

    old_block = match.group(0)
    if old_block.strip() == new_registry_block.strip():
        print("Registry is up to date, no changes needed.")
        return True

    new_content = content[:match.start()] + new_registry_block + content[match.end():]

    if dry_run:
        print("--- DRY RUN: Would write ---")
        print(new_registry_block)
        return False
    else:
        INIT_FILE.write_text(new_content)
        print(f"Updated {INIT_FILE}")
        return True


def main():
    parser = argparse.ArgumentParser(description="Generate TOOL_REGISTRY")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if registry is out of date (CI mode)")
    args = parser.parse_args()

    print("Scanning parrot_tools/ for tools and toolkits...")
    registry = scan_tools()

    if args.verbose:
        for name, path in sorted(registry.items()):
            print(f"  {name}: {path}")

    print(f"\nDiscovered {len(registry)} tools/toolkits")

    new_block = format_registry(registry)
    is_current = update_init_file(new_block, dry_run=args.dry_run or args.check)

    if args.check and not is_current:
        print("ERROR: TOOL_REGISTRY is out of date. Run: python scripts/generate_tool_registry.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 6.3 Git Pre-Commit Hook (Optional)

For those who want automatic registry updates on commit:

```bash
#!/bin/bash
# .githooks/pre-commit

# Check if any tool files changed
TOOL_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep "^packages/ai-parrot-tools/")

if [ -n "$TOOL_FILES" ]; then
    echo "Tool files changed, checking TOOL_REGISTRY..."
    python scripts/generate_tool_registry.py --check
    if [ $? -ne 0 ]; then
        echo ""
        echo "Run: python scripts/generate_tool_registry.py"
        echo "Then: git add packages/ai-parrot-tools/src/parrot_tools/__init__.py"
        exit 1
    fi
fi
```

Setup:
```bash
git config core.hooksPath .githooks
```

### 6.4 CI Check

Add to CI pipeline (GitHub Actions, etc.):

```yaml
- name: Check TOOL_REGISTRY is up to date
  run: uv run python scripts/generate_tool_registry.py --check
```

---

## 7. Migration Strategy

### Phase 1: Workspace Setup (no code moves yet)
1. Create `packages/` directory structure
2. Create root workspace `pyproject.toml`
3. Move existing `parrot/` to `packages/ai-parrot/src/parrot/`
4. Create empty `packages/ai-parrot-tools/` and `packages/ai-parrot-loaders/`
5. Verify `uv sync` works with single package
6. Run all tests — nothing should break

### Phase 2: Tools Migration (incremental)
1. Create `parrot_tools/__init__.py` with empty TOOL_REGISTRY
2. Move tools one-by-one (start with a simple one like `zipcode/`)
3. Add proxy `__getattr__` to `parrot/tools/__init__.py`
4. Update imports in moved tools: `from parrot.tools.abstract import ...` stays unchanged (core)
5. Run tests after each tool move
6. Run `generate_tool_registry.py` after each batch
7. Update existing `ToolkitRegistry` (`parrot/tools/registry.py`) to delegate to new discovery

### Phase 3: Loaders Migration
1. Same pattern as tools
2. Move `parrot/loaders/` contents to `parrot_loaders/`
3. Add proxy to `parrot/loaders/__init__.py`
4. Update `_get_loader()` in `parrot/handlers/chat.py` to use new resolution

### Phase 4: Cleanup
1. Remove old empty directories from core
2. Update CI to run `generate_tool_registry.py --check`
3. Update documentation / README
4. Optionally set up git pre-commit hook

---

## 8. User Experience

### Install scenarios

```bash
# Minimal: just core framework
uv pip install ai-parrot

# Core + specific tools
uv pip install ai-parrot ai-parrot-tools[jira,slack]

# Core + all tools
uv pip install ai-parrot ai-parrot-tools[all]

# Core + heavy loaders
uv pip install ai-parrot ai-parrot-loaders[youtube,audio]

# Everything
uv pip install ai-parrot ai-parrot-tools[all] ai-parrot-loaders[all]
```

### Import experience (unchanged)

```python
# All of these keep working:
from parrot.tools.jira import JiraToolkit
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager

# Direct import also works:
from parrot_tools.jira.toolkit import JiraToolkit

# Loaders:
from parrot.loaders.youtube import YoutubeLoader
from parrot_loaders.youtube import YoutubeLoader  # also works
```

### Error experience (improved)

```python
# If ai-parrot-tools not installed:
>>> from parrot.tools.jira import JiraToolkit
ImportError: Tool 'jira' not found. Install with: uv pip install ai-parrot-tools[jira]

# If tool installed but missing optional dep:
>>> toolkit = JiraToolkit(server_url="...")
ImportError: JiraToolkit requires 'jira' package. Install with: uv pip install ai-parrot-tools[jira]
```

---

## 9. Open Questions

1. **Maturin/Rust extension**: The `yaml_rs` Rust extension currently lives in `parrot/yaml_rs`. Does it stay in core or move to its own package? **Recommendation:** stays in core since it's a performance optimization for YAML parsing used everywhere.

2. **Shared test fixtures**: Tests that exercise tools need `ai-parrot-tools` installed. Use a `conftest.py` at workspace root that conditionally imports. Or separate test directories per package.

3. **Version synchronization**: Should all three packages share the same version? **Recommendation:** yes, simplest approach. The generation script can enforce this.

4. **`parrot/tools/registry.py` (ToolkitRegistry)**: This existing registry has hardcoded imports. Migrate it to delegate to the new `discover_from_registry()` or deprecate in favor of `ToolManager` discovery: ToolManager discovery will discover toolkits, we can deprecate ToolkitRegistry.

5. **`handlers/chat.py` loader resolution**: The `_get_loader()` method currently uses `importlib.import_module('parrot.loaders')`. After migration, the proxy in `parrot/loaders/__init__.py` handles this transparently — but verify with integration tests.