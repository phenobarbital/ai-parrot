import sys
import contextlib
from importlib import import_module
from navconfig.logging import Logger
from parrot.conf import PLUGINS_DIR
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

def setup_plugin_importer(package_name: str, plugin_subdir: str):
    """
    Configures a PluginImporter for any package to extend its search path.

    This allows modules in both core package and plugins folder to be imported
    with the same syntax.

    Args:
        package_name: Full package name (e.g., 'parrot.agents', 'parrot.tools')
        plugin_subdir: Subdirectory name in plugins folder (e.g., 'agents', 'tools')

    Example:
        # In parrot/agents/__init__.py:
        from parrot.plugins import setup_plugin_importer
        setup_plugin_importer('parrot.agents', 'agents')

        # Now you can do:
        from parrot.agents import MyPluginAgent  # Works for both core and plugin agents
    """
    try:
        # Path to plugin subdirectory
        plugin_dir = PLUGINS_DIR / plugin_subdir

        # Create directory if it doesn't exist
        plugin_dir.mkdir(parents=True, exist_ok=True)

        # Ensure __init__.py exists
        init_file = plugin_dir / "__init__.py"
        if not init_file.exists():
            init_file.touch()

        # Register the importer to extend the package search path
        sys.meta_path.append(
            PluginImporter(package_name, str(plugin_dir))
        )

        return True
    except Exception:
        # During package build, dependencies might not be available
        # This is fine - plugins just won't be available until runtime
        return False


def dynamic_import_helper(package_name: str, attr_name: str):
    """
    Helper for __getattr__ to dynamically import plugin modules.

    Args:
        package_name: Package name (e.g., 'parrot.agents')
        attr_name: Attribute being accessed (e.g., 'HRAgent')

    Returns:
        The imported class/module if found

    Raises:
        AttributeError: If the attribute cannot be found

    Example:
        # In parrot/agents/__init__.py:
        def __getattr__(name):
            from parrot.plugins import dynamic_import_helper
            return dynamic_import_helper(__name__, name)
    """
    with contextlib.suppress(ImportError):
        # Try to import as a submodule (lowercase convention)
        module = import_module(f".{attr_name.lower()}", package_name)

        # Look for a class with the original name (usually CamelCase)
        if hasattr(module, attr_name):
            return getattr(module, attr_name)

    # If not found, raise the appropriate error
    raise AttributeError(
        f"module '{package_name}' has no attribute '{attr_name}'"
    )
