"""In-connection operational screencast recorder for E2E exploration (FEAT-762 M1).

Obscura isolates pages per CDP connection, so recording must use a CDPSession
opened on the SAME Playwright connection that owns the page (spike evidence:
sdd/state/FEAT-762/screencast-spike.md). Output is operational, never gate evidence.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from parrot.e2e.errors import E2EScreencastError

if TYPE_CHECKING:  # playwright is not a dependency of ai-parrot-server
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

SCREENCAST_FILENAME = "screencast.webm"
_CDP_TIMEOUT_S = 10.0
_EXTRA_HINT = "install the optional extra: pip install 'ai-parrot-server[screencast]'"


def _encode_webm(frames: list[tuple[int, bytes]], out_path: str) -> int:
    """Encode timestamped JPEG frames to VP8 WebM in a worker process.

    Args:
        frames: Frames ordered by timestamp, relative to the first frame.
        out_path: Destination temporary file.

    Returns:
        Number of frames encoded.
    """
    import av
    from PIL import Image

    with av.open(out_path, "w", format="webm") as container:
        stream = container.add_stream("libvpx", rate=10)
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.width, stream.height = 1280, 720
        last_pts = -1
        for timestamp_ms, jpeg_data in frames:
            image = Image.open(io.BytesIO(jpeg_data)).convert("RGB").resize((1280, 720))
            frame = av.VideoFrame.from_image(image)
            frame.pts = max(timestamp_ms, last_pts + 1)
            frame.time_base = stream.time_base
            last_pts = frame.pts
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return len(frames)


def _validate_webm(path: str) -> int:
    """Decode ``path`` fully and return the number of decoded frames."""
    import av

    with av.open(path) as container:
        return sum(1 for _ in container.decode(video=0))


async def _run_in_worker(function: Callable[..., int], *args: Any) -> int:
    """Run one picklable encoder operation in an isolated worker process."""
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, function, *args)


@dataclass
class ScreencastSession:
    """Runtime recorder handle owning capture state but not the caller's page."""

    page: Any
    cdp: Any
    out_dir: Path
    max_frames: int
    frames: list[tuple[int, bytes]] = field(default_factory=list)
    ack_tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    overflow: bool = False
    result: Optional[Path] = None
    error: Optional[E2EScreencastError] = None
    stopped: bool = False

    @property
    def out_path(self) -> Path:
        """Return the final published WebM path."""
        return self.out_dir / SCREENCAST_FILENAME


async def _send(cdp: Any, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Send one bounded CDP command."""
    return await asyncio.wait_for(cdp.send(method, params), timeout=_CDP_TIMEOUT_S)


async def _detach(cdp: Any) -> None:
    """Detach one CDP session within the recorder timeout."""
    await asyncio.wait_for(cdp.detach(), timeout=_CDP_TIMEOUT_S)


async def start_screencast(page: "Page", out_dir: Path, *, max_frames: int = 600) -> ScreencastSession:
    """Begin capture of the caller's existing page without changing its state."""
    if page.is_closed():
        raise E2EScreencastError("Cannot record a closed page.", reason_code="page_closed")
    if max_frames < 1:
        raise E2EScreencastError("Screencast frame capacity must be positive.", reason_code="frame_overflow")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / SCREENCAST_FILENAME
    if out_path.exists():
        raise E2EScreencastError(f"Screencast output already exists: {out_path}", reason_code="output_exists")

    cdp: Any = None
    session: Optional[ScreencastSession] = None
    try:
        cdp = await asyncio.wait_for(page.context.new_cdp_session(page), timeout=_CDP_TIMEOUT_S)
        session = ScreencastSession(page=page, cdp=cdp, out_dir=out_dir, max_frames=max_frames)

        def on_frame(event: dict[str, Any]) -> None:
            ack = asyncio.create_task(_send(cdp, "Page.screencastFrameAck", {"sessionId": event["sessionId"]}))
            session.ack_tasks.append(ack)
            if len(session.frames) >= session.max_frames:
                session.overflow = True
                return
            timestamp_ms = int(event["metadata"]["timestamp"] * 1000)
            session.frames.append((timestamp_ms, base64.b64decode(event["data"])))

        cdp.on("Page.screencastFrame", on_frame)
        await _send(
            cdp,
            "Page.startScreencast",
            {"format": "jpeg", "quality": 70, "everyNthFrame": 1},
        )
        return session
    except Exception as exc:
        if cdp is not None:
            try:
                await _send(cdp, "Page.stopScreencast")
            except Exception:
                logger.debug("Failed to stop screencast after startup failure.", exc_info=True)
            try:
                await _detach(cdp)
            except Exception:
                logger.debug("Failed to detach CDP session after startup failure.", exc_info=True)
            if session is not None and session.ack_tasks:
                await asyncio.gather(*session.ack_tasks, return_exceptions=True)
        raise E2EScreencastError("Failed to start page screencast.", reason_code="capture_failed") from exc


async def stop_screencast(session: ScreencastSession) -> Path:
    """Stop, encode, validate, and atomically publish a page screencast."""
    if session.stopped:
        if session.error is not None:
            raise session.error
        if session.result is not None:
            return session.result
        raise E2EScreencastError("Screencast stopped without a result.", reason_code="invalid_output")

    session.stopped = True
    temp_path = session.out_dir / f".screencast.{uuid.uuid4().hex}.webm.tmp"
    try:
        cleanup_errors: list[BaseException] = []
        try:
            await _send(session.cdp, "Page.stopScreencast")
        except Exception as exc:
            cleanup_errors.append(exc)
        try:
            await _detach(session.cdp)
        except Exception as exc:
            cleanup_errors.append(exc)
        if session.ack_tasks:
            ack_results = await asyncio.gather(*session.ack_tasks, return_exceptions=True)
            cleanup_errors.extend(result for result in ack_results if isinstance(result, BaseException))
        if cleanup_errors:
            raise E2EScreencastError(
                "Failed to finalize CDP capture.", reason_code="capture_failed"
            ) from cleanup_errors[0]

        if session.overflow:
            raise E2EScreencastError("Screencast frame buffer overflowed.", reason_code="frame_overflow")
        if not session.frames:
            raise E2EScreencastError("Screencast produced no frames.", reason_code="invalid_output")

        first_timestamp = session.frames[0][0]
        frames = [(timestamp - first_timestamp, data) for timestamp, data in session.frames]
        try:
            encoded_count = await _run_in_worker(_encode_webm, frames, str(temp_path))
            decoded_count = await _run_in_worker(_validate_webm, str(temp_path))
        except ImportError as exc:
            raise E2EScreencastError(
                f"Screencast encoder unavailable; {_EXTRA_HINT}.",
                reason_code="encoder_unavailable",
            ) from exc
        except E2EScreencastError:
            raise
        except Exception as exc:
            raise E2EScreencastError("Failed to encode or validate screencast.", reason_code="invalid_output") from exc

        if encoded_count < 1 or decoded_count < 1 or not temp_path.is_file() or temp_path.stat().st_size < 1:
            raise E2EScreencastError("Screencast output is empty or invalid.", reason_code="invalid_output")
        if session.out_path.exists():
            raise E2EScreencastError(
                f"Screencast output already exists: {session.out_path}",
                reason_code="output_exists",
            )
        os.replace(temp_path, session.out_path)
        session.result = session.out_path
        return session.result
    except E2EScreencastError as exc:
        session.error = exc
        raise
    except Exception as exc:
        error = E2EScreencastError("Failed to publish screencast output.", reason_code="capture_failed")
        session.error = error
        raise error from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()


class AnomalyRecorder:
    """Async context manager starting capture at the first console error / HTTP 5xx."""

    def __init__(self, page: "Page", out_dir: Path, *, run_id: str, max_frames: int = 600) -> None:
        """Bind to the caller's page; nothing is recorded until an anomaly occurs."""
        self.page = page
        self.out_dir = out_dir
        self.run_id = run_id
        self.max_frames = max_frames
        self.triggered: bool = False
        self.path: Optional[Path] = None
        self.error: Optional[E2EScreencastError] = None
        self._session: Optional[ScreencastSession] = None
        self._start_task: Optional[asyncio.Task[None]] = None

    def _on_console(self, message: Any) -> None:
        """Trigger on console messages of type ``error``."""
        if message.type == "error":
            self._trigger("console error")

    def _on_response(self, response: Any) -> None:
        """Trigger on HTTP responses with status >= 500."""
        if response.status >= 500:
            self._trigger(f"HTTP {response.status}")

    def _trigger(self, reason: str) -> None:
        """Schedule start_screencast exactly once."""
        if self.triggered:
            return
        self.triggered = True
        logger.info("Starting anomaly screencast for run %s after %s.", self.run_id, reason)
        self._start_task = asyncio.create_task(self._start())

    async def _start(self) -> None:
        """Start capture and retain any recorder failure for the caller."""
        try:
            self._session = await start_screencast(self.page, self.out_dir, max_frames=self.max_frames)
        except E2EScreencastError as exc:
            self.error = exc
            logger.warning("Unable to start anomaly screencast for run %s: %s", self.run_id, exc)
        except Exception:
            self.error = E2EScreencastError(
                "Unexpected failure starting anomaly screencast.",
                reason_code="capture_failed",
            )
            logger.exception("Unexpected failure starting anomaly screencast for run %s.", self.run_id)

    def _record_unexpected_error(self, action: str, exc: Exception) -> None:
        """Store and log an unexpected recorder lifecycle failure."""
        if self.error is None:
            self.error = E2EScreencastError(
                f"Unexpected failure {action} anomaly screencast.",
                reason_code="capture_failed",
            )
        logger.exception("Unexpected failure %s anomaly screencast for run %s.", action, self.run_id, exc_info=exc)

    async def __aenter__(self) -> "AnomalyRecorder":
        """Register page listeners."""
        self.page.on("console", self._on_console)
        self.page.on("response", self._on_response)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """Remove listeners, stop capture on every exit path, never mask the body's exception."""
        for event, handler in (("console", self._on_console), ("response", self._on_response)):
            try:
                self.page.remove_listener(event, handler)
            except Exception as listener_error:
                self._record_unexpected_error("removing listeners from", listener_error)

        if self._start_task is not None:
            try:
                await self._start_task
            except Exception as start_error:
                self._record_unexpected_error("starting", start_error)

        if self._session is not None:
            try:
                self.path = await stop_screencast(self._session)
            except E2EScreencastError as stop_error:
                self.error = stop_error
                logger.warning("Unable to stop anomaly screencast for run %s: %s", self.run_id, stop_error)
            except Exception as stop_error:
                self._record_unexpected_error("stopping", stop_error)
        return False


def record_on_anomaly(page: "Page", out_dir: Path, *, run_id: str, max_frames: int = 600) -> AnomalyRecorder:
    """Return an :class:`AnomalyRecorder` for ``async with`` use (spec §2 Public contract)."""
    return AnomalyRecorder(page, out_dir, run_id=run_id, max_frames=max_frames)
