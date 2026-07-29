"""SPK-1 (throwaway): playwright (chromium) rasterization benchmark.

Feeds the SAME materialized HTML as the weasyprint spike (imported from
``spike_weasyprint.build_html``) to chromium's ``page.pdf()`` three times and reports
size/latency/determinism. Chromium DOES run JS, but we use the same static-SVG HTML so
the comparison is apples-to-apples.

Run:  python artifacts/spikes/spk1-rasterization/spike_playwright.py
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from spike_weasyprint import FIXTURE, OUT, build_html


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(exist_ok=True)
    raw = json.loads(FIXTURE.read_text())
    document = build_html(raw)

    pdf_hashes, sizes, latencies = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for run in range(3):
            page = browser.new_page()
            page.set_content(document, wait_until="load")
            t0 = time.perf_counter()
            pdf = page.pdf(print_background=True)
            latencies.append((time.perf_counter() - t0) * 1000)
            sizes.append(len(pdf))
            pdf_hashes.append(_sha(pdf))
            (OUT / f"playwright_run{run}.pdf").write_bytes(pdf)
            page.close()
        browser.close()

    identical = len(set(pdf_hashes)) == 1
    from importlib.metadata import version

    print("playwright version:", version("playwright"))
    print("pdf sizes:", sizes)
    print("latencies_ms:", [round(x, 1) for x in latencies])
    print("pdf byte-identical across 3 runs:", identical)
    print("pdf sha256 per run:", pdf_hashes)


if __name__ == "__main__":
    main()
