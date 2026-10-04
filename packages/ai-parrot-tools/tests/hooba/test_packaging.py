"""FEAT-602 TASK-3745 — registry and packaging."""

import importlib
import tomllib
from pathlib import Path

from parrot_tools import TOOL_REGISTRY

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_registry_entry_resolves():
    module, cls = TOOL_REGISTRY["hooba"].rsplit(".", 1)
    mod = importlib.import_module(module)
    assert hasattr(mod, cls)
    assert getattr(mod, cls) is not None


def test_hooba_extra_and_package_data_declared():
    data = tomllib.loads(PYPROJECT.read_text())
    extras = data["project"]["optional-dependencies"]
    assert "hooba" in extras
    assert "ai-parrot-tools[business_automation,excel,scraping]" in extras["hooba"]
    assert "pyyaml>=6.0" in extras["hooba"]
    assert "hooba" in extras["all"][0]
    package_data = data["tool"]["setuptools"]["package-data"]
    assert "parrot_tools.hooba.spec" in package_data
    assert "parrot_tools.hooba.rules" in package_data
