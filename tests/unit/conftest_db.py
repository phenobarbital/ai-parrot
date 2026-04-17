"""Shared import helpers for FEAT-082 database tests.

Handles the circular import issue: the worktree's cache.py does
``from .models import ...`` which triggers ``parrot.bots.database.__init__``
which imports ``abstract.py`` which has broken imports.  We pre-load a clean
package stub to break the cycle.

Usage::

    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from conftest_db import setup_worktree_imports
    setup_worktree_imports()
"""
import importlib
import importlib.util
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_WT_SRC = os.path.normpath(
    os.path.join(_HERE, os.pardir, os.pardir, "packages", "ai-parrot", "src")
)

_SETUP_DONE = False


def _stub_broken_imports() -> None:
    """Stub modules with broken imports in the codebase."""
    for path, cls_name in [
        ("parrot.tools.database.pg", "PgSchemaSearchTool"),
        ("parrot.tools.database.bq", "BQSchemaSearchTool"),
    ]:
        if path not in sys.modules:
            stub = types.ModuleType(path)
            setattr(stub, cls_name, type(cls_name, (), {}))
            sys.modules[path] = stub


def _load_wt(module_name: str, rel_path: str) -> types.ModuleType:
    """Load a module from the worktree source tree."""
    filepath = os.path.join(_WT_SRC, *rel_path.split("/"))
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Not found: {filepath}")
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_pkg(pkg_name: str, rel_dir: str) -> None:
    """Register a package in sys.modules."""
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(_WT_SRC, *rel_dir.split("/"))]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg


def setup_worktree_imports() -> None:
    """Idempotent: load worktree modules for FEAT-082 tests.

    Handles circular import by pre-registering the ``parrot.bots.database``
    package as a clean stub before loading individual submodules.
    """
    global _SETUP_DONE
    if _SETUP_DONE:
        return
    _SETUP_DONE = True

    _stub_broken_imports()

    # ---- Break the circular import chain ----
    # Ensure parrot.bots.database package is registered as a clean package
    # BEFORE we load cache.py (which does `from .models import ...`).
    # This prevents __init__.py from running and triggering abstract.py.
    _db_pkg_name = "parrot.bots.database"
    _db_pkg_dir = os.path.join(_WT_SRC, "parrot", "bots", "database")

    # Only create a clean package if it hasn't been loaded yet
    if _db_pkg_name not in sys.modules:
        pkg = types.ModuleType(_db_pkg_name)
        pkg.__path__ = [_db_pkg_dir]
        pkg.__package__ = _db_pkg_name
        sys.modules[_db_pkg_name] = pkg
    else:
        # If already loaded, just ensure it has the right path
        existing = sys.modules[_db_pkg_name]
        if hasattr(existing, "__path__"):
            existing.__path__ = [_db_pkg_dir]

    # Load models first (unchanged, but needed by cache.py)
    _load_wt("parrot.bots.database.models", "parrot/bots/database/models.py")

    # Load retries (unchanged, needed by toolkits)
    _load_wt("parrot.bots.database.retries", "parrot/bots/database/retries.py")

    # Load router (may be extended)
    _load_wt("parrot.bots.database.router", "parrot/bots/database/router.py")

    # cache.py (TASK-568 — rewritten)
    _load_wt("parrot.bots.database.cache", "parrot/bots/database/cache.py")

    # toolkits subpackage (TASK-569+)
    _ensure_pkg("parrot.bots.database.toolkits", "parrot/bots/database/toolkits")

    for mod_name, rel_path in [
        ("parrot.bots.database.toolkits.base", "parrot/bots/database/toolkits/base.py"),
        ("parrot.bots.database.toolkits.sql", "parrot/bots/database/toolkits/sql.py"),
        ("parrot.bots.database.toolkits.postgres", "parrot/bots/database/toolkits/postgres.py"),
        ("parrot.bots.database.toolkits._crud", "parrot/bots/database/toolkits/_crud.py"),
        ("parrot.bots.database.toolkits.bigquery", "parrot/bots/database/toolkits/bigquery.py"),
        ("parrot.bots.database.toolkits.influx", "parrot/bots/database/toolkits/influx.py"),
        ("parrot.bots.database.toolkits.elastic", "parrot/bots/database/toolkits/elastic.py"),
        ("parrot.bots.database.toolkits.documentdb", "parrot/bots/database/toolkits/documentdb.py"),
    ]:
        filepath = os.path.join(_WT_SRC, *rel_path.split("/"))
        if os.path.isfile(filepath):
            _load_wt(mod_name, rel_path)
