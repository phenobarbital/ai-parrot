import asyncio
import importlib
import importlib.abc  # Ensure importlib exposes ABC helpers used during plugin import
import logging
from pathlib import Path
import sys
import types

import pytest


def _install_navconfig_logging_stub() -> None:
    project_root = Path(__file__).resolve().parents[1]

    navconfig_logging = sys.modules.get(
        "navconfig.logging", types.ModuleType("navconfig.logging")
    )
    navconfig_logging.Logger = getattr(navconfig_logging, "Logger", logging.getLoggerClass())
    navconfig_logging.logging = getattr(navconfig_logging, "logging", logging)
    sys.modules["navconfig.logging"] = navconfig_logging

    class _Config:
        def get(self, _key: str, fallback=None):
            return fallback

        def getint(self, _key: str, fallback: int = 0) -> int:
            return int(fallback)

        def getboolean(self, _key: str, fallback: bool = False) -> bool:
            return bool(fallback)

    navconfig_module = sys.modules.get("navconfig", types.ModuleType("navconfig"))
    navconfig_module.config = getattr(navconfig_module, "config", _Config())
    navconfig_module.BASE_DIR = getattr(navconfig_module, "BASE_DIR", project_root)
    navconfig_module.logging = navconfig_logging
    sys.modules["navconfig"] = navconfig_module

    navigator_conf = sys.modules.get(
        "navigator.conf", types.ModuleType("navigator.conf")
    )
    navigator_conf.default_dsn = getattr(
        navigator_conf, "default_dsn", "postgresql://user:pass@localhost/db"
    )
    navigator_conf.CACHE_HOST = getattr(navigator_conf, "CACHE_HOST", "localhost")
    navigator_conf.CACHE_PORT = getattr(navigator_conf, "CACHE_PORT", 6379)
    sys.modules.setdefault("navigator", types.ModuleType("navigator"))
    sys.modules["navigator.conf"] = navigator_conf


def _import_real_jiratoolkit():
    """Load the real ``parrot.tools.jiratoolkit`` module instead of the test stub."""

    _install_navconfig_logging_stub()
    jira_module = types.ModuleType("jira")
    jira_module.JIRA = type("JIRA", (), {})
    sys.modules.setdefault("jira", jira_module)
    for module_name in list(sys.modules):
        if module_name.startswith("parrot.tools"):
            sys.modules.pop(module_name)
    return importlib.import_module("parrot.tools.jiratoolkit")


def test_quote_jql_value_escapes_special_characters():
    module = _import_real_jiratoolkit()
    _quote_jql_value = module._quote_jql_value

    assert _quote_jql_value("user@example.com") == '"user@example.com"'
    assert _quote_jql_value('"quoted"') == '"\\"quoted\\""'
    assert _quote_jql_value("line\\break\n") == '"line\\\\break\\n"'


def test_build_assignee_jql_quotes_email_and_project():
    module = _import_real_jiratoolkit()
    build_assignee_jql = module._build_assignee_jql

    assert (
        build_assignee_jql(
            "jesuslarag@gmail.com", project=None, default_project="NAV"
        )
        == 'project=NAV AND (assignee="jesuslarag@gmail.com")'
    )
