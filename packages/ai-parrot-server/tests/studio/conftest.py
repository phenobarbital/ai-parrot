"""Shared fixtures for ``handlers/studio/*`` tests (FEAT-467 TASK-2511)."""

from __future__ import annotations

import pytest
from aiohttp import web
from parrot.handlers.studio import setup_studio_routes


@pytest.fixture
def studio_app() -> web.Application:
    """A bare aiohttp Application with ``setup_studio_routes`` applied.

    TASK-2511 registers no concrete endpoints yet — later tasks
    (TASK-2512..TASK-2521) add their own ``add_view`` calls inside
    ``setup_studio_routes``. This fixture exists so later Studio test
    suites can build on it without re-deriving the wiring pattern.
    """
    app = web.Application()
    setup_studio_routes(app)
    return app
