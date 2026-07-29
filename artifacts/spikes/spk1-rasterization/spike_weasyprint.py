"""SPK-1 (throwaway): weasyprint rasterization benchmark.

Loads the fixture envelope (validated through the TASK-1720 serialization layer to keep
it honest), materializes ONE self-contained HTML document with a *static SVG* bar chart
(weasyprint runs no JS — this demonstrates the ECharts→static-SVG companion constraint),
then rasterizes to PDF + email-safe HTML three times and reports size/latency/determinism.

Run:  python artifacts/spikes/spk1-rasterization/spike_weasyprint.py
"""

from __future__ import annotations

import hashlib
import html
import json
import time
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"
FIXTURE = HERE / "fixture_infographic_envelope.json"


def check_fixture_parses_with_a2ui_models() -> dict:
    """Fixture loads through the A2UI serialization layer (keeps the envelope honest)."""
    from parrot.outputs.a2ui.serialization import deserialize

    raw = json.loads(FIXTURE.read_text())
    msg = deserialize(raw)
    assert msg.__class__.__name__ == "CreateSurface"
    return raw


def _static_svg_bar_chart(rows: list[dict]) -> str:
    """Deterministic static SVG bar chart (no JS) — the weasyprint chart path."""
    width, height, pad = 400, 200, 30
    max_v = max((r["revenue"] for r in rows), default=1) or 1
    bar_w = (width - 2 * pad) / max(len(rows), 1)
    bars = []
    for i, row in enumerate(rows):
        h = (height - 2 * pad) * row["revenue"] / max_v
        x = pad + i * bar_w
        y = height - pad - h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w * 0.7:.1f}" height="{h:.1f}" fill="#3b7dd8"/>'
            f'<text x="{x:.1f}" y="{height - pad + 14:.1f}" font-size="10">{html.escape(str(row["region"]))}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        + "".join(bars)
        + "</svg>"
    )


def build_html(raw: dict) -> str:
    """Build one self-contained (inline CSS, static SVG, no JS, no external fetch) HTML doc."""
    info = raw["components"][0]["properties"]
    rows = raw["dataModel"]["charts"]["blk-000"]
    kpis = info["sections"][0]["components"]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-label">{html.escape(k["properties"]["label"])}</div>'
        f'<div class="kpi-value">{html.escape(str(k["properties"]["value"]))} '
        f'{html.escape(k["properties"].get("unit", ""))}</div></div>'
        for k in kpis
    )
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<style>body{font-family:sans-serif;margin:24px;color:#1a1a1a}"
        "h1{font-size:22px}h2{font-size:16px}.kpis{display:flex;gap:16px}"
        ".kpi{border:1px solid #ddd;border-radius:8px;padding:12px}"
        ".kpi-label{color:#666;font-size:12px}.kpi-value{font-size:20px;font-weight:700}"
        "</style></head><body>"
        f"<h1>{html.escape(info['title'])}</h1><p>{html.escape(info['subtitle'])}</p>"
        f"<h2>{html.escape(info['sections'][0]['heading'])}</h2>"
        f"<div class='kpis'>{kpi_html}</div>"
        f"<h2>{html.escape(info['sections'][1]['heading'])}</h2>"
        f"{_static_svg_bar_chart(rows)}"
        "</body></html>"
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    from weasyprint import HTML

    OUT.mkdir(exist_ok=True)
    raw = check_fixture_parses_with_a2ui_models()
    document = build_html(raw)

    # Email-safe HTML output (self-contained already).
    (OUT / "weasyprint_email.html").write_text(document)
    # Self-contained: no scripts, no external resource loads (SVG xmlns URIs are
    # namespace declarations, not fetches, so they are allowed).
    assert "<script" not in document
    assert 'src="http' not in document and 'href="http' not in document

    pdf_hashes, sizes, latencies = [], [], []
    for run in range(3):
        t0 = time.perf_counter()
        pdf = HTML(string=document).write_pdf()
        latencies.append((time.perf_counter() - t0) * 1000)
        sizes.append(len(pdf))
        pdf_hashes.append(_sha(pdf))
        (OUT / f"weasyprint_run{run}.pdf").write_bytes(pdf)

    identical = len(set(pdf_hashes)) == 1
    print("weasyprint version:", __import__("weasyprint").__version__)
    print("pdf sizes:", sizes)
    print("latencies_ms:", [round(x, 1) for x in latencies])
    print("pdf byte-identical across 3 runs:", identical)
    print("pdf sha256[0]:", pdf_hashes[0])


if __name__ == "__main__":
    main()
