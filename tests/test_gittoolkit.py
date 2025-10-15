import sys
from pathlib import Path
import os
import types
import logging

import asyncio
import pytest

os.environ.setdefault("LAZY_LOAD", "True")
sys.path.append(str(Path(__file__).resolve().parents[2]))

dummy_config = types.SimpleNamespace(
    debug=False,
    get=lambda *args, **kwargs: kwargs.get("fallback"),
    getboolean=lambda *args, **kwargs: kwargs.get("fallback"),
    getint=lambda *args, **kwargs: kwargs.get("fallback"),
)

dummy_navconfig = types.ModuleType("navconfig")
dummy_navconfig.config = dummy_config
dummy_navconfig.BASE_DIR = Path(__file__).resolve().parents[2]
sys.modules.setdefault("navconfig", dummy_navconfig)

dummy_navconfig_logging = types.ModuleType("navconfig.logging")
dummy_navconfig_logging.logging = logging
sys.modules.setdefault("navconfig.logging", dummy_navconfig_logging)

dummy_navigator = types.ModuleType("navigator")
dummy_navigator_conf = types.ModuleType("navigator.conf")
dummy_navigator_conf.default_dsn = ""
dummy_navigator_conf.CACHE_HOST = "localhost"
dummy_navigator_conf.CACHE_PORT = 6379
dummy_navigator.conf = dummy_navigator_conf
sys.modules.setdefault("navigator", dummy_navigator)
sys.modules.setdefault("navigator.conf", dummy_navigator_conf)

parrot_pkg = types.ModuleType("parrot")
parrot_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "parrot")]
sys.modules.setdefault("parrot", parrot_pkg)

tools_pkg = types.ModuleType("parrot.tools")
tools_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "parrot" / "tools")]
sys.modules.setdefault("parrot.tools", tools_pkg)

sys.modules.setdefault("folium", types.ModuleType("folium"))
sys.modules.setdefault("altair", types.ModuleType("altair"))
sys.modules.setdefault("plotly", types.ModuleType("plotly"))
sys.modules.setdefault("plotly.express", types.ModuleType("plotly.express"))

from parrot.tools.gittoolkit import GitPatchFile, GitToolkit, GitToolkitError


def test_generate_patch_for_modified_file():
    toolkit = GitToolkit()
    change = GitPatchFile(
        path="app/example.py",
        original="print('hi')\n",
        updated="print('hello world')\n",
    )

    result = asyncio.run(toolkit.generate_git_apply_patch(files=[change]))

    assert "print('hello world')" in result["patch"]
    assert result["git_apply"].startswith("cat <<'PATCH'")
    assert not result["skipped"]


def test_generate_patch_skips_identical_content():
    toolkit = GitToolkit()
    change = GitPatchFile(
        path="README.md",
        original="hello\n",
        updated="hello\n",
    )

    with pytest.raises(GitToolkitError):
        asyncio.run(toolkit.generate_git_apply_patch(files=[change]))

