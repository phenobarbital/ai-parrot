import types
import importlib
import importlib.util
import importlib.abc
from importlib.machinery import SourceFileLoader
import os


class PluginImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """A custom importer to load plugins from a specified directory."""
    def __init__(self, package_name, plugins_path):
        self.package_name = package_name
        self.plugins_path = plugins_path

    def _resolve_path(self, fullname):
        """Resolve a fully-qualified module name to a filesystem path.

        Returns:
            tuple: (file_path, is_package) or (None, False) if not found.
        """
        # Get the relative part after the package_name prefix
        suffix = fullname[len(self.package_name) + 1:]  # e.g. "nextstop" or "nextstop.store"
        parts = suffix.split(".")
        # Build the filesystem path from parts
        rel_path = os.path.join(self.plugins_path, *parts)

        # Check if it's a package (directory with __init__.py)
        pkg_init = os.path.join(rel_path, "__init__.py")
        if os.path.isdir(rel_path) and os.path.exists(pkg_init):
            return pkg_init, True

        # Check if it's a module file
        module_file = rel_path + ".py"
        if os.path.exists(module_file):
            return module_file, False

        return None, False

    def find_spec(self, fullname, path, target=None):
        if fullname.startswith(self.package_name):
            # Handle submodules
            if fullname.startswith(self.package_name + "."):
                file_path, is_package = self._resolve_path(fullname)
                if file_path is not None:
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
                loader = SourceFileLoader(fullname, init_path)
                loaded = types.ModuleType(fullname)
                loader.exec_module(loaded)
                module.__dict__.update(loaded.__dict__)
                # Append plugins_path to __path__ instead of replacing it
                # This allows both main directory and plugins directory to coexist
                if not hasattr(module, '__path__'):
                    module.__path__ = []
                if self.plugins_path not in module.__path__:
                    module.__path__.append(self.plugins_path)

        # Handle individual component files and sub-packages
        else:
            file_path, is_package = self._resolve_path(fullname)
            if file_path is not None:
                component_name = fullname.split(".")[-1]
                if is_package:
                    # It's a sub-package: set __path__ so further imports work
                    pkg_dir = os.path.dirname(file_path)
                    module.__path__ = [pkg_dir]
                    module.__package__ = fullname
                loader = SourceFileLoader(fullname, file_path)
                loaded = types.ModuleType(fullname)
                loaded.__name__ = fullname
                if is_package:
                    loaded.__path__ = module.__path__
                    loaded.__package__ = fullname
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
