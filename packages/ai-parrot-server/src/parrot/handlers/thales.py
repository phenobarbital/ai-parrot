"""HTTP handler for the "Thales" research flow (FEAT-425 Module 6).

POST + polling surface (resolved in brainstorm — explicitly NOT SSE/
WebSocket):

- ``POST /api/v1/thales``                    — launch a run, returns ``run_id``
- ``GET  /api/v1/thales/{run_id}``            — status document / full result
- ``GET  /api/v1/thales/{run_id}/artifacts``  — artifact list with public URLs

Routes are registered by :func:`setup_thales_routes`. Run state lives in the
module-level :class:`RunRegistry` (in-memory; a redis backend is a spec §8
open question — this class is the seam for that later swap, per the task's
"keep the seam" instruction).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated
from parrot.flows.thales import ThalesRunner
from parrot.flows.thales.models import ThalesConfig, ThalesResult
from pydantic import ValidationError

logger = logging.getLogger(__name__)

#: Number of most-recent node events kept in a status document response.
_MAX_STATUS_EVENTS = 20

#: Valid `sources` entries (mirrors `ThalesConfig.sources`'s default list /
#: `parrot.flows.thales.definition._SOURCE_LABELS` keys). An unrecognized
#: value used to be silently dropped by the definition-assembly filter
#: instead of surfaced as a 400 (code-review finding).
_KNOWN_SOURCES = {"web", "deep_research", "arxiv"}


@dataclass
class _RunEntry:
    """In-memory state for one Thales run."""

    run_id: str
    runner: ThalesRunner
    task: "asyncio.Task[None]"
    status: str = "pending"
    events: List[Dict[str, Any]] = field(default_factory=list)
    result: Optional[ThalesResult] = None
    error: Optional[str] = None


class RunRegistry:
    """In-memory registry of Thales runs, keyed by ``run_id``.

    Deliberately minimal so a redis-backed implementation can later expose
    the same interface (``attach``/``get``/``record_event``/``complete``/
    ``fail``) without touching the handler classes.
    """

    def __init__(self) -> None:
        self._runs: Dict[str, _RunEntry] = {}

    def attach(self, run_id: str, *, runner: ThalesRunner, task: "asyncio.Task[None]") -> None:
        """Register a newly-launched run."""
        self._runs[run_id] = _RunEntry(run_id=run_id, runner=runner, task=task)

    def get(self, run_id: str) -> Optional[_RunEntry]:
        """Look up a run's entry, or ``None`` when unknown."""
        return self._runs.get(run_id)

    def record_event(
        self, run_id: str, event: str, node_id: str, info: Dict[str, Any],
    ) -> None:
        """Append one ``AgentsFlow`` node event to a run's status document."""
        entry = self._runs.get(run_id)
        if entry is None:
            return
        entry.events.append({"event": event, "node_id": node_id, "info": info})
        if event == "flow_started" and entry.status == "pending":
            entry.status = "running"

    def complete(self, run_id: str, result: ThalesResult) -> None:
        """Mark a run completed with its final ``ThalesResult``."""
        entry = self._runs.get(run_id)
        if entry is not None:
            entry.status = "completed"
            entry.result = result

    def fail(self, run_id: str, error: BaseException) -> None:
        """Mark a run failed, capturing the error summary (never re-raised)."""
        entry = self._runs.get(run_id)
        if entry is not None:
            entry.status = "failed"
            entry.error = str(error)


#: Module-level singleton — one process-wide run registry (in-memory seam).
_run_registry = RunRegistry()


def get_run_registry() -> RunRegistry:
    """Return the module-level :class:`RunRegistry` singleton (test seam)."""
    return _run_registry


@is_authenticated()
class ThalesRunHandler(BaseView):
    """``POST /api/v1/thales`` — launch a Thales research run.

    Request body (JSON): ``{"thesis": str, "num_decks"?: int,
    "sources"?: list[str], "llm"?: str}``. ``output_dir`` is deliberately
    NOT an accepted field — see the security note in :meth:`post`.
    """

    async def post(self) -> web.Response:
        """Validate the request, launch the run in the background, return ``run_id``.

        Returns:
            202 ``{"run_id": ...}`` on success.
            400 when ``thesis`` is missing or ``num_decks`` is below the
            spec's minimum of 10.
        """
        try:
            body = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        thesis = body.get("thesis")
        if not thesis:
            return self.error("'thesis' is required.", status=400)

        num_decks = body.get("num_decks", 10)
        sources = body.get("sources")

        if sources is not None:
            unknown = set(sources) - _KNOWN_SOURCES
            if unknown:
                return self.error(
                    f"Invalid request: unknown source(s) {sorted(unknown)!r} — "
                    f"valid sources are {sorted(_KNOWN_SOURCES)!r}.",
                    status=400,
                )

        try:
            ThalesConfig(thesis=thesis, num_decks=num_decks, sources=sources or ["web", "deep_research", "arxiv"])
        except ValidationError:
            return self.error(
                f"Invalid request: 'num_decks' must be >= 10 (got {num_decks!r}) — "
                "Thales requires a minimum of 10 research angles per run.",
                status=400,
            )

        run_id = str(uuid.uuid4())
        # SECURITY: `output_dir` is intentionally NOT accepted from the
        # request body — ThalesRunner/`_mirror_to_output_dir` writes
        # `deck-*.json`/`slide-*.html`/`manifest.json` directly to whatever
        # path is given (`Path(output_dir).mkdir(parents=True, ...)`), and
        # this endpoint has no safe-base-directory confinement to validate
        # a client-supplied path against. HTTP-launched runs persist via
        # `ArtifactStore` (public URLs) only; local filesystem mirroring
        # remains available through the Python API (`ThalesRunner(...,
        # output_dir=...)`), where the caller controls their own trusted path.
        runner = ThalesRunner(
            thesis=thesis,
            num_decks=num_decks,
            sources=sources,
            llm=body.get("llm"),
        )
        runner.add_progress_listener(
            lambda event, node_id, info: _run_registry.record_event(run_id, event, node_id, info)
        )

        async def _run_in_background() -> None:
            try:
                result = await runner.run()
                _run_registry.complete(run_id, result)
            except Exception as exc:  # captured into the registry, never raised (matches mcp_helper.py precedent)
                logger.error("Thales run %s failed: %s", run_id, exc, exc_info=True)
                _run_registry.fail(run_id, exc)

        task = asyncio.create_task(_run_in_background())
        _run_registry.attach(run_id, runner=runner, task=task)

        return self.json_response({"run_id": run_id}, status=202)


@is_authenticated()
class ThalesStatusHandler(BaseView):
    """``GET /api/v1/thales/{run_id}`` — poll a run's status / final result."""

    async def get(self) -> web.Response:
        """Return the run's status document.

        Returns:
            200 with ``{"run_id", "status", "node_events", ...}``; includes
            ``"result"`` (the full ``ThalesResult``) when ``status ==
            "completed"``, or ``"error"`` when ``status == "failed"``.
            404 when ``run_id`` is unknown.
        """
        run_id = self.request.match_info.get("run_id", "")
        entry = _run_registry.get(run_id)
        if entry is None:
            return self.error(f"Unknown run_id: {run_id!r}", status=404)

        doc: Dict[str, Any] = {
            "run_id": run_id,
            "status": entry.status,
            "node_events": entry.events[-_MAX_STATUS_EVENTS:],
        }
        if entry.status == "completed" and entry.result is not None:
            doc["result"] = entry.result.model_dump(mode="json")
        elif entry.status == "failed":
            doc["error"] = entry.error

        return self.json_response(doc)


@is_authenticated()
class ThalesArtifactsHandler(BaseView):
    """``GET /api/v1/thales/{run_id}/artifacts`` — list a run's artifacts."""

    async def get(self) -> web.Response:
        """Return the run's artifact list with public URLs.

        Returns:
            200 with ``{"run_id", "artifacts": [ArtifactRef, ...]}``
            (empty list before the run completes). 404 when ``run_id`` is
            unknown.
        """
        run_id = self.request.match_info.get("run_id", "")
        entry = _run_registry.get(run_id)
        if entry is None:
            return self.error(f"Unknown run_id: {run_id!r}", status=404)

        if entry.result is None:
            return self.json_response({"run_id": run_id, "artifacts": []})

        refs = [entry.result.final_document, entry.result.final_pdf, *entry.result.slides]
        artifacts = [ref.model_dump(mode="json") for ref in refs if ref is not None]

        return self.json_response({"run_id": run_id, "artifacts": artifacts})


def setup_thales_routes(app: web.Application) -> None:
    """Register the Thales HTTP routes on the aiohttp application.

    Registers three routes:
    - ``POST /api/v1/thales`` → :class:`ThalesRunHandler`
    - ``GET  /api/v1/thales/{run_id}`` → :class:`ThalesStatusHandler`
    - ``GET  /api/v1/thales/{run_id}/artifacts`` → :class:`ThalesArtifactsHandler`

    Args:
        app: The aiohttp :class:`~aiohttp.web.Application` instance.
    """
    base = "/api/v1/thales"
    app.router.add_route("POST", base, ThalesRunHandler)
    app.router.add_route("GET", f"{base}/{{run_id}}", ThalesStatusHandler)
    app.router.add_route("GET", f"{base}/{{run_id}}/artifacts", ThalesArtifactsHandler)
