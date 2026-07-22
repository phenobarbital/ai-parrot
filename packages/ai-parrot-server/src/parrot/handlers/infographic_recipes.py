"""REST handler + scheduler callback for FEAT-324 infographic recipes (Module 8).

Provides REST endpoints for recipe CRUD + on-demand replay:

    GET    /api/v1/infographic_recipes              - list recipes (owner-scoped)
    GET    /api/v1/infographic_recipes/{name}        - full recipe
    PUT    /api/v1/infographic_recipes/{name}        - create/overwrite a recipe
    DELETE /api/v1/infographic_recipes/{name}        - delete a recipe
    POST   /api/v1/infographic_recipes/{name}/run    - replay (RecipeRunner.run())

Plus a ``run_infographic_recipe`` scheduler callback registered on the
EXISTING ``CALLBACK_REGISTRY`` (``parrot.scheduler.functions`` —
``AgentSchedulerManager`` already ships jobs + callbacks; no new scheduler is
created here, per spec Non-Goal). Scheduled replays run under the recipe's
stored ``schedule.principal`` (spec G8) — a missing/unset principal fails the
job outright, NEVER falling back to a server identity.

**Wiring note**: scheduler callback objects are built by
``build_scheduler_callback(definition, logger=...)`` from static, JSON-
serializable job config ONLY (see ``scheduler/functions/__init__.py``) — they
have no access to the aiohttp ``app`` or any live singleton. Call
:func:`configure_recipe_runner` once at server startup (alongside
:func:`register_recipe_routes`) so ``run_infographic_recipe`` jobs have a
``RecipeRunner`` to use.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.conf import AUTH_SESSION_OBJECT
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from pydantic import ValidationError

from parrot.auth.permission import PermissionContext, UserSession
from parrot.outputs.a2ui.recipes.models import InfographicRecipe
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore, RecipeNotFoundError
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

from ..scheduler.functions import CALLBACK_REGISTRY, BaseSchedulerCallback

__all__ = [
    "RecipeHandler",
    "RunInfographicRecipeCallback",
    "configure_recipe_runner",
    "get_recipe_runner",
    "register_recipe_routes",
]

logger = logging.getLogger("Parrot.RecipeHandler")

# Process-wide RecipeRunner used by the scheduler callback (see module
# docstring's Wiring note). The REST handler prefers `app["recipe_runner"]`
# and falls back to this singleton so both triggers can share one runner.
_default_recipe_runner: Optional[RecipeRunner] = None


def configure_recipe_runner(runner: RecipeRunner) -> None:
    """Set the process-wide ``RecipeRunner`` used by the scheduler callback.

    Args:
        runner: The configured ``RecipeRunner`` (store + dataset manager).
    """
    global _default_recipe_runner
    _default_recipe_runner = runner


def get_recipe_runner() -> Optional[RecipeRunner]:
    """Return the process-wide ``RecipeRunner`` set via :func:`configure_recipe_runner`."""
    return _default_recipe_runner


def register_recipe_routes(
    app: web.Application,
    *,
    recipe_store: AbstractRecipeStore,
    recipe_runner: Optional[RecipeRunner] = None,
    dataset_manager: Any = None,
    artifact_store: Any = None,
) -> RecipeRunner:
    """Configure the recipe store/runner for ``RecipeHandler`` and the scheduler callback.

    Routes themselves are registered unconditionally in
    ``manager.py`` (mirroring the ``DatasetManagerHandler`` precedent) — this
    function ONLY wires the store/runner onto ``app`` (so ``RecipeHandler``
    resolves them) and onto the process-wide singleton the
    ``run_infographic_recipe`` scheduler callback reads (callback objects are
    built from static JSON job config only — see the module docstring's
    Wiring note — so they cannot reach ``app`` directly).

    Args:
        app: The aiohttp application.
        recipe_store: The configured ``AbstractRecipeStore``.
        recipe_runner: A pre-built ``RecipeRunner``; takes precedence over
            ``dataset_manager`` (below) if both are given.
        dataset_manager: Used to build a ``RecipeRunner`` when
            ``recipe_runner`` is not supplied directly.
        artifact_store: Forwarded to the built ``RecipeRunner`` (only used
            when building one from ``dataset_manager``).

    Returns:
        The ``RecipeRunner`` now wired on ``app["recipe_runner"]`` and as the
        scheduler callback's process-wide runner.

    Raises:
        ValueError: If neither ``recipe_runner`` nor ``dataset_manager`` is given.
    """
    if recipe_runner is None:
        if dataset_manager is None:
            raise ValueError(
                "register_recipe_routes requires either recipe_runner or dataset_manager"
            )
        recipe_runner = RecipeRunner(recipe_store, dataset_manager, artifact_store=artifact_store)

    app["recipe_store"] = recipe_store
    app["recipe_runner"] = recipe_runner
    configure_recipe_runner(recipe_runner)

    return recipe_runner


async def _get_user_id(request: web.Request) -> Optional[str]:
    """Extract the authenticated user's id from the request/session.

    Mirrors ``handlers/artifacts.py``'s ``_get_user_id`` helper.
    """
    user = getattr(request, "user", None)
    if user:
        uid = getattr(user, "user_id", None) or getattr(user, "id", None)
        if uid:
            return str(uid)
    try:
        session = await get_session(request)
    except Exception:  # noqa: BLE001
        return None
    if session:
        userinfo = session.get(AUTH_SESSION_OBJECT, {})
        if isinstance(userinfo, dict):
            user_id = userinfo.get("user_id")
            if user_id:
                return str(user_id)
        user_id = session.get("user_id")
        if user_id:
            return str(user_id)
    return None


@is_authenticated()
@user_session()
class RecipeHandler(BaseView):
    """CRUD + run REST handler for infographic recipes (FEAT-324, Module 8)."""

    _logger_name: str = "Parrot.RecipeHandler"

    def post_init(self, *args, **kwargs) -> None:
        self.logger = logging.getLogger(self._logger_name)

    @property
    def store(self) -> AbstractRecipeStore:
        store = self.request.app.get("recipe_store")
        if store is None:
            raise RuntimeError("recipe_store is not configured in app")
        return store

    @property
    def runner(self) -> RecipeRunner:
        runner = self.request.app.get("recipe_runner") or get_recipe_runner()
        if runner is None:
            raise RuntimeError("recipe_runner is not configured in app")
        return runner

    def _error_response(self, message: str, status: int = 400) -> web.Response:
        return self.json_response({"status": "error", "message": message}, status=status)

    async def get(self) -> web.Response:
        """List recipes, or fetch one by name.

        Endpoints:
            GET /api/v1/infographic_recipes
            GET /api/v1/infographic_recipes/{name}
        """
        name = self.request.match_info.get("name")
        owner = await _get_user_id(self.request)
        try:
            if name:
                recipe = await self.store.get(name, owner=owner)
                return self.json_response(
                    {"status": "success", "recipe": recipe.model_dump(mode="json")}
                )
            recipes = await self.store.list(owner=owner)
            return self.json_response(
                {"status": "success", "count": len(recipes), "recipes": recipes}
            )
        except RecipeNotFoundError as exc:
            return self._error_response(str(exc), status=404)
        except RuntimeError as exc:
            return self._error_response(str(exc), status=500)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("RecipeHandler GET failed: %s", exc, exc_info=True)
            return self._error_response(str(exc), status=500)

    async def put(self) -> web.Response:
        """Create or overwrite a recipe.

        Endpoint:
            PUT /api/v1/infographic_recipes/{name}
        """
        name = self.request.match_info.get("name")
        if not name:
            return self._error_response("recipe name is required in the URL", status=400)
        try:
            data = await self.request.json()
        except Exception:  # noqa: BLE001
            return self._error_response("Invalid JSON body", status=400)
        if not isinstance(data, dict):
            return self._error_response("Request body must be a JSON object", status=400)

        owner = await _get_user_id(self.request)
        payload = dict(data)
        payload["name"] = name
        payload.setdefault("owner", owner)
        # `updated_at` is store-owned (overwrite semantics, spec G5) — the
        # store's save() replaces it regardless, but the model has no
        # default (TASK-1865), so a PUT body that omits it must not 422.
        payload.setdefault("updated_at", datetime.now(timezone.utc).isoformat())

        try:
            recipe = InfographicRecipe.model_validate(payload)
        except ValidationError as exc:
            return self.json_response(
                {"status": "error", "message": "Invalid recipe", "errors": exc.errors()},
                status=422,
            )

        try:
            await self.store.save(recipe)
        except RuntimeError as exc:
            return self._error_response(str(exc), status=500)
        return self.json_response(
            {"status": "success", "recipe": recipe.model_dump(mode="json")}
        )

    async def delete(self) -> web.Response:
        """Delete a recipe.

        Endpoint:
            DELETE /api/v1/infographic_recipes/{name}
        """
        name = self.request.match_info.get("name")
        if not name:
            return self._error_response("recipe name is required in the URL", status=400)
        owner = await _get_user_id(self.request)
        try:
            await self.store.delete(name, owner=owner)
        except RecipeNotFoundError as exc:
            return self._error_response(str(exc), status=404)
        except RuntimeError as exc:
            return self._error_response(str(exc), status=500)
        return self.json_response({"status": "success"})

    async def post(self) -> web.Response:
        """Replay a recipe.

        Endpoint:
            POST /api/v1/infographic_recipes/{name}/run
        """
        name = self.request.match_info.get("name")
        if not name:
            return self._error_response("recipe name is required in the URL", status=400)
        if not self.request.path.endswith("/run"):
            return self._error_response("Unsupported action", status=404)

        try:
            body: Dict[str, Any] = await self.request.json()
        except Exception:  # noqa: BLE001
            body = {}
        params = body.get("params") if isinstance(body, dict) else None

        try:
            runner = self.runner
        except RuntimeError as exc:
            return self._error_response(str(exc), status=500)

        try:
            artifact = await runner.run(name, params=params)
        except RecipeRunException as exc:
            return self.json_response(
                {"status": "error", **exc.error.model_dump()}, status=422
            )
        except RecipeNotFoundError as exc:
            return self._error_response(str(exc), status=404)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("RecipeHandler run failed: %s", exc, exc_info=True)
            return self._error_response(str(exc), status=500)

        return self.json_response(
            {
                "status": "success",
                "artifact": {
                    "artifact_id": artifact.artifact_id,
                    "filename": artifact.filename,
                    "mime_type": artifact.mime_type,
                    "size": len(artifact.content) if artifact.content else None,
                    "storage_ref": str(artifact.path) if artifact.path else None,
                },
            }
        )


class RunInfographicRecipeCallback(BaseSchedulerCallback):
    """Scheduler callback replaying a saved recipe (FEAT-324, spec G6/G8).

    Config:
        recipe_name (str, required): Recipe to replay.
        params (dict, optional): Override values for the recipe's declared params.

    The targeted recipe MUST have ``schedule.principal`` set. It is resolved
    into a minimal ``PermissionContext`` (the principal is treated as a
    ``user_id``; full multi-tenant/role resolution is a documented follow-up
    — NOT required by spec G8's core acceptance criterion, which is simply
    "never fall back to a server identity"). A missing principal, or a
    missing runner, fails the job outright rather than silently widening
    access.
    """

    callback_name = "run_infographic_recipe"
    description = (
        "Replay a saved infographic recipe deterministically under its stored "
        "schedule.principal (no LLM in the loop); never falls back to a server identity."
    )

    async def run(
        self, result: Any, *, schedule_id: str, agent_name: str, **kwargs
    ) -> Dict[str, Any]:
        recipe_name = self.config.get("recipe_name")
        if not recipe_name:
            raise ValueError("run_infographic_recipe requires config.recipe_name")

        runner = get_recipe_runner()
        if runner is None:
            raise RuntimeError(
                "run_infographic_recipe: no RecipeRunner configured on the server "
                "(call configure_recipe_runner()/register_recipe_routes() at startup)."
            )

        recipe = await runner.store.get(recipe_name)
        principal = recipe.schedule.principal if recipe.schedule else None
        if not principal:
            raise RuntimeError(
                f"run_infographic_recipe: recipe {recipe_name!r} has no "
                "schedule.principal configured; scheduled replays REQUIRE an "
                "explicit principal (spec G8) — refusing to run under a server identity."
            )

        pctx = PermissionContext(
            session=UserSession(user_id=principal, tenant_id=principal, roles=frozenset()),
            channel="scheduler",
        )
        artifact = await runner.run(recipe_name, params=self.config.get("params"), pctx=pctx)
        return {
            "status": "ok",
            "artifact_id": artifact.artifact_id,
            "mime_type": artifact.mime_type,
            "filename": artifact.filename,
        }


# Import side effect: registers this callback so it is discoverable via
# `list_supported_callbacks()` / `SchedulerCallbacksHandler`'s GET listing.
CALLBACK_REGISTRY[RunInfographicRecipeCallback.callback_name] = RunInfographicRecipeCallback
