"""Route registration for the JSON REST surface of parrot-formdesigner.

Hard-imports navigator-auth: any consumer that does not have the package
installed will fail at import time. This is intentional — see FEAT-152.

Public API:

    setup_form_api(app, registry, *, client=None, submission_storage=None,
                   forwarder=None, base_path="/api/v1") -> None
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING

from aiohttp import web

# HARD navigator-auth import — package fails to import without it.
# See FEAT-152 §1 Goals: "Promote navigator-auth to a hard dependency".
from navigator_auth.decorators import is_authenticated, user_session

from ..services.registry import FormRegistry
from . import controls as controls_module
from . import operations as operations_module
from . import render as render_module
from .handlers import FormAPIHandler


if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

    from ..services.forwarder import SubmissionForwarder
    from ..services.submissions import FormSubmissionStorage


logger = logging.getLogger(__name__)


_Handler = Callable[[web.Request], Awaitable[web.Response]]


def _wrap_auth(handler: _Handler) -> _Handler:
    """Wrap a handler with navigator-auth ``is_authenticated`` + ``user_session``.

    Mirrors the previous ``handlers/routes.py:_wrap_auth`` shape, but without
    the ``_AUTH_AVAILABLE`` fallback — navigator-auth is a hard dep here.

    Args:
        handler: A bound async coroutine accepting ``request: web.Request``.

    Returns:
        The decorated handler.
    """

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        # user_session's _func_wrapper injects session= and user= kwargs.
        # Our handlers don't accept those — consume them here so they
        # don't cause a TypeError, then call the original handler.
        return await handler(request)

    decorated = user_session()(_inner)
    decorated = is_authenticated(content_type="application/json")(decorated)
    return decorated


def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    base_path: str = "/api/v1",
) -> None:
    """Mount the JSON REST surface on ``app`` under ``base_path``.

    Every route is wrapped with navigator-auth's ``is_authenticated`` +
    ``user_session`` decorators. Telegram webhook routes do NOT belong here
    — see ``parrot_formdesigner.ui.setup_form_ui`` for those.

    Args:
        app: aiohttp application to register routes on.
        registry: Pre-built ``FormRegistry`` shared across requests.
        client: Optional LLM client for natural language form creation.
        submission_storage: Optional storage backend for submissions.
        forwarder: Optional submission forwarder.
        base_path: URL prefix for all routes (default ``"/api/v1"``).
    """
    # Stash the registry on the app for the dispatcher / operations handler.
    app["form_registry"] = registry

    # Seed the renderer registry with the V1 default renderers.
    render_module._seed_default_renderers()

    handler = FormAPIHandler(
        registry=registry,
        client=client,
        submission_storage=submission_storage,
        forwarder=forwarder,
    )

    bp = base_path.rstrip("/")

    # CRUD + listing
    app.router.add_get(f"{bp}/forms", _wrap_auth(handler.list_forms))
    app.router.add_post(f"{bp}/forms", _wrap_auth(handler.create_form))
    app.router.add_post(f"{bp}/forms/from-db", _wrap_auth(handler.load_from_db))
    app.router.add_get(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.get_form))
    app.router.add_put(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.update_form))
    app.router.add_patch(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.patch_form))

    # Contract endpoints (schema, style)
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/schema", _wrap_auth(handler.get_schema)
    )
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/style", _wrap_auth(handler.get_style)
    )

    # Render dispatcher (path-param format)
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/render/{{format}}",
        _wrap_auth(render_module.handle_render),
    )

    # Validation + submissions
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/validate", _wrap_auth(handler.validate)
    )
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/data", _wrap_auth(handler.submit_data)
    )

    # Form-controls toolbar metadata
    app.router.add_get(
        f"{bp}/form-controls",
        _wrap_auth(controls_module.handle_form_controls),
    )

    # Atomic batched-edit endpoint (Wave 2d replaces the stub body)
    app.router.add_patch(
        f"{bp}/forms/{{form_id}}/operations",
        _wrap_auth(operations_module.handle_operations),
    )

    logger.info("setup_form_api: mounted on %s", bp)
