"""Local conftest for parrot.eval tests.

Provides shared fixtures for the evaluation harness test suite.
This conftest installs minimal stubs for broken optional dependencies
(navconfig, navigator) that the global conftest would normally handle.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

# Ensure the parrot source tree is importable when running tests directly.
SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Also make ai-parrot-tools importable.
TOOLS_SRC = Path(__file__).resolve().parents[5] / "ai-parrot-tools" / "src"
if TOOLS_SRC.exists() and str(TOOLS_SRC) not in sys.path:
    sys.path.insert(0, str(TOOLS_SRC))


def _install_navconfig_stub() -> None:
    """Install minimal navconfig stubs so parrot.bots can import."""
    if "navconfig" in sys.modules:
        return

    class _Config:
        def __call__(self, key, default=None, fallback=None):
            import os
            v = fallback if fallback is not None else default
            return os.environ.get(key, v)

        def get(self, key, default=None, fallback=None):
            return self(key, default=default, fallback=fallback)

        def getboolean(self, key, fallback=False):
            import os
            val = os.environ.get(key)
            if val is None:
                return bool(fallback)
            return val.lower() in ("1", "true", "yes", "on")

    navconfig_module = types.ModuleType("navconfig")
    navconfig_module.config = _Config()
    navconfig_module.BASE_DIR = SRC.parent
    navconfig_module.DEBUG = False

    # navconfig.logging
    NOTICE_LEVEL = 25
    logging.addLevelName(NOTICE_LEVEL, "NOTICE")

    def _notice(self, message, *args, **kwargs):
        if self.isEnabledFor(NOTICE_LEVEL):
            self._log(NOTICE_LEVEL, message, args, **kwargs)

    if not hasattr(logging.Logger, "notice"):
        logging.Logger.notice = _notice  # type: ignore[attr-defined]

    logging_module = types.ModuleType("navconfig.logging")
    logging_module.logging = logging
    logging_module.Logger = logging.Logger
    logging_module.loglevel = logging.INFO
    logging_module.LOGLEVEL = "INFO"
    navconfig_module.logging = logging_module

    exceptions_module = types.ModuleType("navconfig.exceptions")

    class _ConfigError(Exception):
        pass

    exceptions_module.ConfigError = _ConfigError
    exceptions_module.NavConfigException = _ConfigError

    sys.modules.setdefault("navconfig", navconfig_module)
    sys.modules.setdefault("navconfig.logging", logging_module)
    sys.modules.setdefault("navconfig.exceptions", exceptions_module)

    # Stub out navconfig.utils.* that are broken in the venv
    for mod_name in (
        "navconfig.utils",
        "navconfig.utils.functions",
        "navconfig.utils.uvl",
    ):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            stub.strtobool = lambda v: bool(v)
            stub.install_uvloop = lambda: None
            sys.modules[mod_name] = stub


def _install_navigator_stubs() -> None:
    """Stub out navigator packages that are broken in the test venv."""
    for mod_name in (
        "navigator",
        "navigator.utils",
        "navigator.utils.file",
        "navigator.utils.file.abstract",
        "navigator.applications",
        "navigator.applications.base",
        "navigator.types",
    ):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)


_install_navconfig_stub()
_install_navigator_stubs()
