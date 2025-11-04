"""
Parrot Agents - Core and Plugin Agents
"""
from importlib import import_module
from parrot.plugins import setup_plugin_importer, dynamic_import_helper

setup_plugin_importer('parrot.agents', 'agents')

# Enable dynamic imports
def __getattr__(name):
    """
    Getattr with dynamic import.
    First, search in PLUGINS_DIR, if doesn't exists,
    then look on parrot.bots package.
    """
    try:
        return dynamic_import_helper(__name__, name)
    except AttributeError:
        # try to import from parrot.bots
        try:
            module = import_module(f"parrot.bots.{name.lower()}")
            if hasattr(module, name):
                return getattr(module, name)
        except (ImportError, ModuleNotFoundError):
            pass
    raise AttributeError(
        f"module '{__name__}' has no attribute '{name}'"
    )
