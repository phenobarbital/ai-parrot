"""Unit tests for ``load_transformer_module`` (FEAT-528 TASK-2871)."""
from __future__ import annotations

import textwrap

import pytest

from parrot.outputs.a2ui.recipes.transformers import transformer_registry
from parrot.tools.infographic_recipes import load_transformer_module


def _write_pkg(tmp_path):
    """Write a synthetic package (parent NOT named ``agents``) with a
    relative import, mirroring the shape TASK-2872 needs to load."""
    pkg = tmp_path / "hostpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "helpers.py").write_text("def double(x):\n    return 2 * x\n")
    (pkg / "transformers.py").write_text(
        textwrap.dedent(
            '''
            from parrot.outputs.a2ui.recipes.transformers import infographic_transformer
            from .helpers import double


            @infographic_transformer(name="t_2871_probe")
            def probe(inputs, params):
                return {"v": double(1)}
            '''
        )
    )
    return pkg / "transformers.py"


def test_load_transformer_module_registers(tmp_path):
    mod = load_transformer_module(_write_pkg(tmp_path))
    registered = transformer_registry.get("t_2871_probe")
    assert registered is not None
    # Idempotent: loading the same path again returns the same module object
    # and does not re-register (register() would raise on a DIFFERENT func).
    assert load_transformer_module(mod.__file__) is mod


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_transformer_module(tmp_path / "nope.py")


def test_load_transformer_module_bare_file(tmp_path):
    """A module with no sibling ``__init__.py`` loads directly (no package)."""
    mod_path = tmp_path / "bare_transformers.py"
    mod_path.write_text(
        textwrap.dedent(
            '''
            from parrot.outputs.a2ui.recipes.transformers import infographic_transformer


            @infographic_transformer(name="t_2871_bare_probe")
            def bare_probe(inputs, params):
                return {"v": 1}
            '''
        )
    )
    load_transformer_module(mod_path)
    assert transformer_registry.get("t_2871_bare_probe") is not None
