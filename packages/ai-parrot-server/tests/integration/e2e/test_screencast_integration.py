"""Real-Obscura integration test for record_on_anomaly (FEAT-762 M2)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from parrot.e2e.screencast import record_on_anomaly
from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager


def _last_frame_sample(path: Path) -> tuple[int, int, int]:
    """Decode a WebM and return the final frame's lower-center RGB sample."""
    import av

    samples: list[tuple[int, int, int]] = []
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            image = frame.to_image().convert("RGB")
            samples.append(image.getpixel((image.width // 2, image.height - 10)))
    assert samples, "screencast contains no decodable frames"
    return samples[-1]


async def test_record_on_anomaly_real_obscura(unused_tcp_port: int, tmp_path: Path) -> None:
    """Anomaly page yields a playable WebM showing the post-trigger change; clean page yields none."""
    binary = os.environ.get("OBSCURA_BINARY") or shutil.which("obscura")
    if not binary:
        pytest.skip("No Obscura binary configured (set OBSCURA_BINARY or install 'obscura').")
    pytest.importorskip("playwright.async_api")
    pytest.importorskip("av")
    pytest.importorskip("PIL")
    from playwright.async_api import async_playwright

    manager = ObscuraProcessManager(
        ObscuraProcessConfig(binary_path=binary, port=unused_tcp_port, allow_private_network=False)
    )
    try:
        endpoint = await manager.start()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(endpoint)
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()

                clean_page = await context.new_page()
                clean_dir = tmp_path / "clean"
                async with record_on_anomaly(clean_page, clean_dir, run_id="clean") as clean_recorder:
                    await clean_page.goto("data:text/html,<style>html,body{height:100%;background:white}</style>")
                assert not clean_recorder.triggered
                assert clean_recorder.path is None
                assert clean_recorder.error is None
                assert not clean_dir.exists()

                # Obscura 0.2.2 only lets the most recently created page evaluate JavaScript.
                anomaly_page = await context.new_page()
                await anomaly_page.goto("data:text/html,<style>html,body{height:100%;background:white}</style>")
                anomaly_dir = tmp_path / "anomaly"
                async with record_on_anomaly(anomaly_page, anomaly_dir, run_id="anomaly") as recorder:
                    await anomaly_page.evaluate("console.error('controlled anomaly')")
                    assert await recorder.wait_started(timeout=5.0), recorder.error
                    assert recorder.recording
                    await asyncio.sleep(1)  # capture some white frames before the change
                    await anomaly_page.evaluate(
                        "document.documentElement.style.background = 'red'; " "document.body.style.background = 'red'"
                    )
                    await asyncio.sleep(2)

                assert recorder.error is None
                assert recorder.path == anomaly_dir / "screencast.webm"
                assert recorder.path.is_file()
                last_sample = await asyncio.to_thread(_last_frame_sample, recorder.path)
                assert last_sample[0] > 200 and last_sample[1] < 80 and last_sample[2] < 80, last_sample
                assert not anomaly_page.is_closed()
                assert anomaly_page in context.pages
                assert browser.is_connected()
            finally:
                await browser.close()
    finally:
        await manager.stop()
