import sys
from pathlib import Path
from ..conf import PLUGINS_DIR
from .importer import PluginImporter

# Add plugins directory to sys.path
sys.path.insert(0, str(PLUGINS_DIR))

# Agents Loader - maps parrot.agents to project_folder/plugins/agents/
agents_dir = PLUGINS_DIR / "agents"
agents_dir.mkdir(exist_ok=True)

# Create __init__.py if it doesn't exist
init_file = agents_dir / "__init__.py"
if not init_file.exists():
    init_file.touch()

PACKAGE_AGENTS = "parrot.agents"
try:
    sys.meta_path.append(PluginImporter(PACKAGE_AGENTS, str(agents_dir)))
except ImportError as exc:
    print(f"Agent Plugin Error: {exc}")

# Tools Loader - maps parrot.tools to project_folder/plugins/tools/
tools_dir = PLUGINS_DIR / "tools"
tools_dir.mkdir(exist_ok=True)
tools_init = tools_dir / "__init__.py"
if not tools_init.exists():
    tools_init.touch()

PACKAGE_TOOLS = "parrot.tools"
try:
    sys.meta_path.append(PluginImporter(PACKAGE_TOOLS, str(tools_dir)))
except ImportError as exc:
    print(f"Tools Plugin Error: {exc}")
