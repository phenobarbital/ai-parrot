import types
import importlib
from importlib.machinery import SourceFileLoader
import os


class PluginImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """A custom importer to load plugins from a specified directory."""
    def __init__(self, package_name, plugins_path):
        self.package_name = package_name
        self.plugins_path = plugins_path

    def find_spec(self, fullname, path, target=None):
        if fullname.startswith(self.package_name):
            # Handle exact package match
            if fullname == self.package_name:
                init_path = os.path.join(self.plugins_path, "__init__.py")
                if os.path.exists(init_path):
                    return importlib.util.spec_from_loader(fullname, self)

            # Handle submodules
            elif fullname.startswith(self.package_name + "."):
                component_name = fullname.split(".")[-1]
                component_path = os.path.join(self.plugins_path, f"{component_name}.py")

                if os.path.exists(component_path):
                    return importlib.util.spec_from_loader(fullname, self)

        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        fullname = module.__name__

        # Handle package __init__.py loading
        if fullname == self.package_name:
            init_path = os.path.join(self.plugins_path, "__init__.py")
            if os.path.exists(init_path):
                loader = SourceFileLoader("__init__", init_path)
                loaded = types.ModuleType(loader.name)
                loader.exec_module(loaded)
                module.__dict__.update(loaded.__dict__)
                module.__path__ = [self.plugins_path]

        # Handle individual component files
        else:
            component_name = fullname.split(".")[-1]
            component_path = os.path.join(self.plugins_path, f"{component_name}.py")
            if os.path.exists(component_path):
                loader = SourceFileLoader(component_name, component_path)
                loaded = types.ModuleType(loader.name)
                loader.exec_module(loaded)
                module.__dict__.update(loaded.__dict__)

def list_plugins(plugin_subdir: str) -> list[str]:
    """
    List all available plugins in a subdirectory.

    Args:
        plugin_subdir: Subdirectory name (e.g., 'agents', 'tools')

    Returns:
        List of plugin module names (without .py extension)
    """
    try:
        from ..conf import PLUGINS_DIR
        plugin_dir = PLUGINS_DIR / plugin_subdir

        if not plugin_dir.exists():
            return []

        return [
            f.stem for f in plugin_dir.glob("*.py")
            if f.stem != "__init__"
        ]
    except (ImportError, Exception):
        return []
