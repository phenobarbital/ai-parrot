"""Packaging guard — ai-parrot-integrations must NOT ship parrot/integrations/__init__.py.

Both ``ai-parrot`` (core) and ``ai-parrot-integrations`` (satellite) contribute
to the ``parrot.integrations`` package. The core owns the package's
``__init__.py`` (lazy ``__getattr__`` dispatch that exposes
``IntegrationBotManager`` and friends). The satellite only adds concrete
submodules (``manager.py``, ``whatsapp/``, ...).

If the satellite were to ship its own ``parrot/integrations/__init__.py``, both
wheels would write the same path into site-packages and the last one installed
would silently overwrite the other — wheel install is last-writer-wins at the
file level, NOT a namespace merge. When the satellite installs after the core,
its (empty) stub clobbers the core's lazy dispatch and
``from parrot.integrations import IntegrationBotManager`` breaks at runtime even
though ``manager.py`` is present.

This test fails fast if anyone re-introduces that stub, so the regression can
never reach a published wheel.
"""
from __future__ import annotations

from pathlib import Path


def _satellite_src_root() -> Path:
    """Return the satellite's ``src/`` root regardless of CWD.

    Walks up from this test file to the ``ai-parrot-integrations`` package
    directory and returns its ``src`` folder.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "src" / "parrot" / "integrations"
        if candidate.is_dir():
            return parent / "src"
    raise AssertionError(
        "Could not locate the ai-parrot-integrations src/ root from "
        f"{here}; test layout assumption broken."
    )


def test_satellite_does_not_ship_integrations_init() -> None:
    """The satellite must not own parrot/integrations/__init__.py.

    Ownership of that file belongs exclusively to the core ai-parrot
    distribution, whose lazy ``__getattr__`` governs the namespace.
    """
    offending = (
        _satellite_src_root() / "parrot" / "integrations" / "__init__.py"
    )
    assert not offending.exists(), (
        f"{offending} exists. ai-parrot-integrations must NOT ship "
        "parrot/integrations/__init__.py — it collides with the core's "
        "lazy-dispatch __init__ when both wheels unpack into the same "
        "site-packages (last writer wins), breaking "
        "`from parrot.integrations import IntegrationBotManager`. "
        "Delete this file; the core ai-parrot package owns the package init."
    )


def test_satellite_still_ships_concrete_submodules() -> None:
    """Sanity: removing the init must not have removed the real modules.

    Guards against an over-zealous fix that deletes the whole package
    directory instead of just the stub.
    """
    integrations = _satellite_src_root() / "parrot" / "integrations"
    assert (integrations / "manager.py").is_file(), (
        "parrot/integrations/manager.py is missing from the satellite — "
        "the package must still ship its concrete submodules."
    )
    assert (integrations / "version.py").is_file(), (
        "parrot/integrations/version.py is missing — the build reads the "
        "version from it via the setuptools attr directive."
    )
