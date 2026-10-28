"""Unit tests for the in-connection E2E screencast recorder (FEAT-762 M1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from parrot.e2e import screencast
from parrot.e2e.errors import E2EScreencastError


class FakeCDPSession:
    """Record CDP commands and deliver synthetic screencast frame events."""

    def __init__(self, *, fail_method: Optional[str] = None) -> None:
        self.fail_method = fail_method
        self.calls: list[tuple[str, Optional[dict[str, Any]]]] = []
        self.handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self.detached = False

    async def send(self, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Record a command and optionally fail it."""
        self.calls.append((method, params))
        if method == self.fail_method:
            raise RuntimeError(f"configured failure: {method}")
        return {}

    def on(self, event: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """Register an event callback."""
        self.handlers[event] = handler

    async def detach(self) -> None:
        """Record detachment from the page."""
        self.calls.append(("detach", None))
        self.detached = True
        if self.fail_method == "detach":
            raise RuntimeError("configured failure: detach")

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        """Deliver a synthetic CDP event."""
        self.handlers[event](payload)


class FakeContext:
    """Return the configured CDP session for the exact supplied page."""

    def __init__(self, cdp: FakeCDPSession) -> None:
        self.cdp = cdp
        self.pages: list[Any] = []
        self.requested_page: Optional[FakePage] = None

    async def new_cdp_session(self, page: "FakePage") -> FakeCDPSession:
        """Open a fake page-scoped CDP session."""
        self.requested_page = page
        return self.cdp


class FakePage:
    """Minimal existing page that tracks whether the recorder closes it."""

    def __init__(self, cdp: FakeCDPSession, *, closed: bool = False) -> None:
        self.context = FakeContext(cdp)
        self.context.pages.append(self)
        self._closed = closed
        self.close_calls = 0
        self.handlers: dict[str, list[Callable[[Any], None]]] = {}

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        """Register a page event listener."""
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler: Callable[[Any], None]) -> None:
        """Remove a page event listener."""
        self.handlers[event].remove(handler)

    def emit(self, event: str, payload: Any) -> None:
        """Deliver a page event to a stable snapshot of its listeners."""
        for handler in list(self.handlers.get(event, [])):
            handler(payload)

    def is_closed(self) -> bool:
        """Return the page's current closed state."""
        return self._closed

    async def close(self) -> None:
        """Track accidental page ownership violations."""
        self.close_calls += 1
        self._closed = True


def _frame(session_id: int = 1, timestamp: float = 1.0) -> dict[str, Any]:
    """Build one valid synthetic screencast event."""
    return {
        "data": "anBlZw==",
        "metadata": {"timestamp": timestamp},
        "sessionId": session_id,
    }


async def _inline_worker(function: Callable[..., int], *args: Any) -> int:
    """Run a worker function inline so monkeypatched callables need not pickle."""
    return function(*args)


def _successful_encoder(frames: list[tuple[int, bytes]], out_path: str) -> int:
    """Write a small stand-in artifact and report the encoded frame count."""
    Path(out_path).write_bytes(b"webm")
    return len(frames)


async def test_start_screencast_existing_page_succeeds(tmp_path: Path) -> None:
    """Capture starts on the caller's exact existing page."""
    cdp = FakeCDPSession()
    page = FakePage(cdp)

    session = await screencast.start_screencast(page, tmp_path)

    assert session.page is page
    assert page.context.requested_page is page
    assert cdp.calls == [("Page.startScreencast", {"format": "jpeg", "quality": 70, "everyNthFrame": 1})]
    assert page.context.pages == [page]
    assert page.close_calls == 0


async def test_start_screencast_closed_page_raises(tmp_path: Path) -> None:
    """A closed page fails before opening a CDP session."""
    page = FakePage(FakeCDPSession(), closed=True)

    with pytest.raises(E2EScreencastError, match="closed") as raised:
        await screencast.start_screencast(page, tmp_path)

    assert raised.value.reason_code == "page_closed"
    assert page.context.requested_page is None


async def test_start_screencast_failure_releases_resources(tmp_path: Path) -> None:
    """A failed start stops and detaches its partially opened CDP session."""
    cdp = FakeCDPSession(fail_method="Page.startScreencast")
    page = FakePage(cdp)

    with pytest.raises(E2EScreencastError) as raised:
        await screencast.start_screencast(page, tmp_path)

    assert raised.value.reason_code == "capture_failed"
    assert cdp.calls == [
        ("Page.startScreencast", {"format": "jpeg", "quality": 70, "everyNthFrame": 1}),
        ("Page.stopScreencast", None),
        ("detach", None),
    ]
    assert page.close_calls == 0


async def test_stop_screencast_finalizes_and_preserves_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop follows lifecycle order and publishes without owning the page."""
    cdp = FakeCDPSession()
    page = FakePage(cdp)
    monkeypatch.setattr(screencast, "_run_in_worker", _inline_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 1)
    session = await screencast.start_screencast(page, tmp_path)
    cdp.emit("Page.screencastFrame", _frame())
    await asyncio.sleep(0)

    result = await screencast.stop_screencast(session)

    assert result == tmp_path / "screencast.webm"
    assert result.read_bytes() == b"webm"
    assert cdp.calls == [
        ("Page.startScreencast", {"format": "jpeg", "quality": 70, "everyNthFrame": 1}),
        ("Page.screencastFrameAck", {"sessionId": 1}),
        ("Page.stopScreencast", None),
        ("detach", None),
    ]
    assert not page.is_closed()
    assert page.close_calls == 0
    assert page.context.pages == [page]


async def test_stop_screencast_invalid_output_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty capture and undecodable output both fail without publication."""
    monkeypatch.setattr(screencast, "_run_in_worker", _inline_worker)
    empty_session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path / "empty")
    with pytest.raises(E2EScreencastError) as empty_error:
        await screencast.stop_screencast(empty_session)
    assert empty_error.value.reason_code == "invalid_output"

    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 0)
    invalid_dir = tmp_path / "invalid"
    invalid_session = await screencast.start_screencast(FakePage(FakeCDPSession()), invalid_dir)
    invalid_session.cdp.emit("Page.screencastFrame", _frame())
    with pytest.raises(E2EScreencastError) as invalid_error:
        await screencast.stop_screencast(invalid_session)
    assert invalid_error.value.reason_code == "invalid_output"
    assert not invalid_session.out_path.exists()
    assert not list(invalid_dir.glob(".screencast.*.webm.tmp"))


async def test_stop_screencast_refuses_overwrite_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing output is refused and a successful stop is cached."""
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    existing = existing_dir / "screencast.webm"
    existing.write_bytes(b"keep")
    with pytest.raises(E2EScreencastError) as existing_error:
        await screencast.start_screencast(FakePage(FakeCDPSession()), existing_dir)
    assert existing_error.value.reason_code == "output_exists"
    assert existing.read_bytes() == b"keep"

    monkeypatch.setattr(screencast, "_run_in_worker", _inline_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 1)
    raced_dir = tmp_path / "raced"
    raced_session = await screencast.start_screencast(FakePage(FakeCDPSession()), raced_dir)
    raced_session.cdp.emit("Page.screencastFrame", _frame())
    raced_session.out_path.write_bytes(b"concurrent")
    with pytest.raises(E2EScreencastError) as raced_error:
        await screencast.stop_screencast(raced_session)
    assert raced_error.value.reason_code == "output_exists"
    assert raced_session.out_path.read_bytes() == b"concurrent"

    worker_calls: list[str] = []

    async def counted_worker(function: Callable[..., int], *args: Any) -> int:
        worker_calls.append(function.__name__)
        return function(*args)

    monkeypatch.setattr(screencast, "_run_in_worker", counted_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 1)
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path / "success")
    session.cdp.emit("Page.screencastFrame", _frame())
    first = await screencast.stop_screencast(session)
    second = await screencast.stop_screencast(session)
    assert second == first
    assert worker_calls == ["_successful_encoder", "<lambda>"]


async def test_frame_buffer_overflow_is_explicit_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Overflow stops capture once, stops acking, and never publishes truncation."""
    worker_called = False

    async def unexpected_worker(function: Callable[..., int], *args: Any) -> int:
        nonlocal worker_called
        worker_called = True
        return 0

    monkeypatch.setattr(screencast, "_run_in_worker", unexpected_worker)
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path, max_frames=1)
    session.cdp.emit("Page.screencastFrame", _frame(1, 1.0))
    session.cdp.emit("Page.screencastFrame", _frame(2, 2.0))
    session.cdp.emit("Page.screencastFrame", _frame(3, 3.0))

    with pytest.raises(E2EScreencastError) as raised:
        await screencast.stop_screencast(session)

    assert raised.value.reason_code == "frame_overflow"
    assert len(session.ack_tasks) == 2  # one ack + one stop at overflow; later frames ignored
    assert not worker_called
    assert not session.out_path.exists()
    assert [call for call in session.cdp.calls if call[0] == "Page.screencastFrameAck"] == [
        ("Page.screencastFrameAck", {"sessionId": 1}),
    ]


async def test_missing_encoder_extra_is_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing optional encoder dependency produces the documented error."""

    def missing_encoder(frames: list[tuple[int, bytes]], out_path: str) -> int:
        raise ModuleNotFoundError("av")

    monkeypatch.setattr(screencast, "_run_in_worker", _inline_worker)
    monkeypatch.setattr(screencast, "_encode_webm", missing_encoder)
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path)
    session.cdp.emit("Page.screencastFrame", _frame())

    with pytest.raises(E2EScreencastError, match=r"ai-parrot-server\[screencast\]") as raised:
        await screencast.stop_screencast(session)

    assert raised.value.reason_code == "encoder_unavailable"
    assert not session.out_path.exists()
    with pytest.raises(E2EScreencastError) as repeated:
        await screencast.stop_screencast(session)
    assert repeated.value is raised.value


async def test_record_on_anomaly_clean_run_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean run never starts a session or creates an output directory."""
    page = FakePage(FakeCDPSession())
    start_calls = 0

    async def unexpected_start(page: FakePage, out_dir: Path, *, max_frames: int) -> screencast.ScreencastSession:
        nonlocal start_calls
        start_calls += 1
        raise AssertionError("clean run started capture")

    monkeypatch.setattr(screencast, "start_screencast", unexpected_start)

    async with screencast.record_on_anomaly(page, tmp_path / "clean", run_id="clean-run") as recorder:
        page.emit("console", type("Message", (), {"type": "warning"})())
        page.emit("response", type("Response", (), {"status": 499})())

    assert start_calls == 0
    assert not recorder.triggered
    assert recorder.path is None
    assert recorder.error is None
    assert not (tmp_path / "clean").exists()
    assert page.handlers == {"console": [], "response": []}


async def test_record_on_anomaly_starts_once_on_first_anomaly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent console and response anomalies start and stop one capture."""
    page = FakePage(FakeCDPSession())
    session = object()
    start_calls: list[tuple[FakePage, Path, int]] = []
    stop_calls: list[object] = []
    result = tmp_path / "anomaly" / screencast.SCREENCAST_FILENAME

    async def fake_start(page: FakePage, out_dir: Path, *, max_frames: int) -> Any:
        start_calls.append((page, out_dir, max_frames))
        await asyncio.sleep(0)
        return session

    async def fake_stop(received: object) -> Path:
        stop_calls.append(received)
        return result

    monkeypatch.setattr(screencast, "start_screencast", fake_start)
    monkeypatch.setattr(screencast, "stop_screencast", fake_stop)

    async with screencast.record_on_anomaly(
        page, tmp_path / "anomaly", run_id="anomaly-run", max_frames=12
    ) as recorder:
        page.emit("response", type("Response", (), {"status": 503})())
        page.emit("console", type("Message", (), {"type": "error"})())
        page.emit("response", type("Response", (), {"status": 504})())

    assert recorder.triggered
    assert recorder.path == result
    assert recorder.error is None
    assert start_calls == [(page, tmp_path / "anomaly", 12)]
    assert stop_calls == [session]


@pytest.mark.parametrize("body_error", [RuntimeError("body failed"), asyncio.CancelledError("cancelled")])
async def test_record_on_anomaly_stops_on_exception_and_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body_error: BaseException
) -> None:
    """Recorder stop failures never replace body exceptions or cancellation."""
    page = FakePage(FakeCDPSession())
    session = object()
    stop_calls: list[object] = []
    stop_error = E2EScreencastError("encoder failed", reason_code="invalid_output")

    async def fake_start(page: FakePage, out_dir: Path, *, max_frames: int) -> Any:
        return session

    async def fake_stop(received: object) -> Path:
        stop_calls.append(received)
        raise stop_error

    monkeypatch.setattr(screencast, "start_screencast", fake_start)
    monkeypatch.setattr(screencast, "stop_screencast", fake_stop)

    with pytest.raises(type(body_error)) as raised:
        async with screencast.record_on_anomaly(page, tmp_path, run_id="failed-run") as recorder:
            page.emit("console", type("Message", (), {"type": "error"})())
            raise body_error

    assert raised.value is body_error
    assert recorder.triggered
    assert recorder.path is None
    assert recorder.error is stop_error
    assert stop_calls == [session]
    assert page.handlers == {"console": [], "response": []}


async def test_stop_screencast_keeps_buffered_frames_when_finalize_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late detach/stop failure with buffered frames still publishes the recording."""
    monkeypatch.setattr(screencast, "_run_in_worker", _inline_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 1)
    session = await screencast.start_screencast(FakePage(FakeCDPSession(fail_method="detach")), tmp_path)
    session.cdp.emit("Page.screencastFrame", _frame())
    assert await screencast.stop_screencast(session) == session.out_path
    assert session.out_path.exists()


async def test_malformed_frame_event_is_ignored_and_acked(tmp_path: Path) -> None:
    """An event missing metadata is dropped without raising, but its session is still acked."""
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path)
    session.cdp.emit("Page.screencastFrame", {"sessionId": 7, "data": "AAAA"})

    assert session.frames == []
    assert len(session.ack_tasks) == 1
    await asyncio.gather(*session.ack_tasks)
    assert ("Page.screencastFrameAck", {"sessionId": 7}) in session.cdp.calls


def _jpeg_frame(color: tuple[int, int, int]) -> bytes:
    """Encode one small solid-color JPEG frame with Pillow."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _jpeg_event(color: tuple[int, int, int], timestamp: float) -> dict[str, Any]:
    """Build a CDP screencast event carrying a real JPEG frame."""
    import base64

    return {
        "data": base64.b64encode(_jpeg_frame(color)).decode("ascii"),
        "metadata": {"timestamp": timestamp},
        "sessionId": 1,
    }


def test_real_encoder_roundtrip_in_process(tmp_path: Path) -> None:
    """The real PyAV/libvpx encoder writes a WebM that decodes back to frames."""
    pytest.importorskip("av")
    pytest.importorskip("PIL")
    frames = [(0, _jpeg_frame((255, 0, 0))), (100, _jpeg_frame((0, 255, 0))), (200, _jpeg_frame((0, 0, 255)))]
    out_path = tmp_path / "roundtrip.webm"

    assert screencast._encode_webm(frames, str(out_path)) == 3
    assert out_path.stat().st_size > 0
    assert screencast._validate_webm(str(out_path)) >= 1


async def test_stop_screencast_real_worker_publishes_playable_webm(tmp_path: Path) -> None:
    """Stop runs the real encoder and validator in the spawned worker process."""
    pytest.importorskip("av")
    pytest.importorskip("PIL")
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path)
    session.cdp.emit("Page.screencastFrame", _jpeg_event((255, 0, 0), 1.0))
    session.cdp.emit("Page.screencastFrame", _jpeg_event((0, 0, 255), 1.2))

    published = await screencast.stop_screencast(session)

    assert published == tmp_path / "screencast.webm"
    assert screencast._validate_webm(str(published)) >= 1
    assert not list(tmp_path.glob(".screencast.*"))


async def test_concurrent_stop_screencast_is_single_flight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A concurrent second stop waits for the first and returns the same path."""
    gate = asyncio.Event()
    entered = asyncio.Event()
    worker_calls: list[str] = []

    async def gated_worker(function: Callable[..., int], *args: Any) -> int:
        worker_calls.append(function.__name__)
        entered.set()
        await gate.wait()
        return function(*args)

    monkeypatch.setattr(screencast, "_run_in_worker", gated_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 1)
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path)
    session.cdp.emit("Page.screencastFrame", _frame())

    first = asyncio.create_task(screencast.stop_screencast(session))
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    second = asyncio.create_task(screencast.stop_screencast(session))
    await asyncio.sleep(0)
    assert not second.done()

    gate.set()
    results = await asyncio.gather(first, second)

    assert results == [session.out_path, session.out_path]
    assert worker_calls == ["_successful_encoder", "<lambda>"]


async def test_concurrent_stop_screencast_shares_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A concurrent second stop re-raises the first call's typed error, not a misleading one."""
    gate = asyncio.Event()

    async def gated_worker(function: Callable[..., int], *args: Any) -> int:
        await gate.wait()
        return function(*args)

    monkeypatch.setattr(screencast, "_run_in_worker", gated_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 0)
    session = await screencast.start_screencast(FakePage(FakeCDPSession()), tmp_path)
    session.cdp.emit("Page.screencastFrame", _frame())

    first = asyncio.create_task(screencast.stop_screencast(session))
    await asyncio.sleep(0)
    second = asyncio.create_task(screencast.stop_screencast(session))
    await asyncio.sleep(0)
    gate.set()
    errors = await asyncio.gather(first, second, return_exceptions=True)

    assert isinstance(errors[0], E2EScreencastError)
    assert errors[0].reason_code == "invalid_output"
    assert errors[1] is errors[0]
    assert not session.out_path.exists()


async def test_record_on_anomaly_cancel_during_aexit_records_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling while __aexit__ is encoding re-raises and leaves a typed recorder error."""
    entered = asyncio.Event()

    async def blocked_worker(function: Callable[..., int], *args: Any) -> int:
        entered.set()
        await asyncio.Event().wait()  # never released: only cancellation ends it
        return function(*args)

    monkeypatch.setattr(screencast, "_run_in_worker", blocked_worker)
    cdp = FakeCDPSession()
    page = FakePage(cdp)
    recorders: list[screencast.AnomalyRecorder] = []

    async def body() -> None:
        async with screencast.record_on_anomaly(page, tmp_path, run_id="cancelled-run") as recorder:
            recorders.append(recorder)
            page.emit("console", type("Message", (), {"type": "error"})())
            assert await recorder.wait_started(timeout=1.0)
            cdp.emit("Page.screencastFrame", _frame())

    task = asyncio.create_task(body())
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    recorder = recorders[0]
    assert recorder.path is None
    assert isinstance(recorder.error, E2EScreencastError)
    assert recorder.error.reason_code == "capture_failed"
    assert recorder._session is not None and recorder._session.finished.is_set()
    assert page.handlers == {"console": [], "response": []}
    assert not list(tmp_path.glob(".screencast.*"))
    assert not (tmp_path / "screencast.webm").exists()


async def test_wait_started_reports_recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """wait_started is False before any trigger and True once capture is running."""
    monkeypatch.setattr(screencast, "_run_in_worker", _inline_worker)
    monkeypatch.setattr(screencast, "_encode_webm", _successful_encoder)
    monkeypatch.setattr(screencast, "_validate_webm", lambda path: 1)
    cdp = FakeCDPSession()
    page = FakePage(cdp)

    async with screencast.record_on_anomaly(page, tmp_path, run_id="waited-run") as recorder:
        assert await recorder.wait_started(timeout=0.01) is False
        assert not recorder.recording
        page.emit("response", type("Response", (), {"status": 503})())
        assert await recorder.wait_started(timeout=1.0) is True
        assert recorder.recording
        cdp.emit("Page.screencastFrame", _frame())

    assert recorder.error is None
    assert recorder.path == tmp_path / "screencast.webm"


async def test_wait_started_is_false_when_start_fails(tmp_path: Path) -> None:
    """A failed start completes wait_started with False and a typed error."""
    page = FakePage(FakeCDPSession(), closed=True)

    async with screencast.record_on_anomaly(page, tmp_path, run_id="closed-run") as recorder:
        page.emit("console", type("Message", (), {"type": "error"})())
        assert await recorder.wait_started(timeout=1.0) is False
        assert not recorder.recording

    assert recorder.error is not None
    assert recorder.error.reason_code == "page_closed"
