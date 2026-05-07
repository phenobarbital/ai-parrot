#!/usr/bin/env python3
"""Build a combined PDF from the architecture chapters.

Reads the markdown set under ``docs/architecture/``, converts it to a
single HTML document (preserving Mermaid blocks as rendered diagrams),
then uses headless Chromium to print it to PDF.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
ARCH_DIR = ROOT / "docs" / "architecture"
OUT_HTML = ROOT / "artifacts" / "architecture.html"
OUT_PDF = ROOT / "artifacts" / "ai-parrot-architecture.pdf"

CHAPTER_FILES = [
    "README.md",
    "01-mcp-server.md",
    "02-a2a.md",
    "03-toolkits.md",
    "04-interaction-surface.md",
    "05-hardening.md",
    "06-cross-cutting.md",
]

MERMAID_BLOCK = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def md_to_html(md_text: str) -> str:
    """Convert markdown to HTML, preserving mermaid blocks as <div>s."""
    md_text = MERMAID_BLOCK.sub(
        lambda m: f'\n<div class="mermaid">\n{m.group(1).strip()}\n</div>\n',
        md_text,
    )
    # Rewrite cross-chapter relative links (e.g. `02-a2a.md`) to anchors.
    md_text = re.sub(
        r"\]\((\d{2}-[a-z0-9-]+)\.md(#[^)]+)?\)",
        lambda m: f"](#{m.group(1)}{m.group(2) or ''})",
        md_text,
    )
    md_text = re.sub(r"\]\(README\.md(#[^)]+)?\)",
                     lambda m: f"](#index{m.group(1) or ''})", md_text)
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        output_format="html5",
    )


def build_html() -> str:
    chapters_html = []
    for name in CHAPTER_FILES:
        path = ARCH_DIR / name
        anchor = "index" if name == "README.md" else path.stem
        body = md_to_html(path.read_text(encoding="utf-8"))
        chapters_html.append(
            f'<section id="{anchor}" class="chapter">{body}</section>'
        )

    css = """
    @page { size: A4; margin: 18mm 16mm 20mm 16mm; }
    body {
        font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        font-size: 11.5pt;
        line-height: 1.55;
        color: #222;
        max-width: 100%;
    }
    h1 { font-size: 22pt; border-bottom: 2px solid #1976d2; padding-bottom: 6px;
         page-break-before: always; }
    section.chapter:first-of-type h1 { page-break-before: avoid; }
    h2 { font-size: 16pt; color: #1976d2; margin-top: 1.6em; }
    h3 { font-size: 13pt; color: #444; margin-top: 1.2em; }
    h4 { font-size: 12pt; color: #555; }
    p, li { orphans: 3; widows: 3; }
    code { background: #f4f4f4; padding: 1px 4px; border-radius: 3px;
           font-family: "Fira Code", Menlo, Consolas, monospace; font-size: 10pt; }
    pre { background: #f6f8fa; padding: 10px 12px; border-radius: 6px;
          overflow: auto; font-size: 9.5pt; line-height: 1.4;
          page-break-inside: avoid; }
    pre code { background: transparent; padding: 0; }
    blockquote { border-left: 3px solid #1976d2; margin: 0; padding: 4px 14px;
                 background: #f0f7ff; color: #444; }
    table { border-collapse: collapse; margin: 1em 0; font-size: 10.5pt;
            page-break-inside: avoid; }
    th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left;
             vertical-align: top; }
    th { background: #f4f4f4; }
    .mermaid { text-align: center; page-break-inside: avoid; margin: 1.2em 0; }
    a { color: #1976d2; text-decoration: none; }
    a:hover { text-decoration: underline; }
    section.chapter { page-break-before: always; }
    section.chapter:first-of-type { page-break-before: avoid; }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI-Parrot — Exposure, Interoperability &amp; Hardening Architecture</title>
<style>{css}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'default',
    securityLevel: 'loose',
    flowchart: {{ htmlLabels: true, useMaxWidth: true }},
    sequence:  {{ useMaxWidth: true }},
  }});
  // Signal readiness once every diagram has rendered.
  window.addEventListener('load', async () => {{
    try {{
      await mermaid.run();
    }} catch (e) {{ console.error(e); }}
    document.title += ' [READY]';
    document.body.setAttribute('data-mermaid-ready', '1');
  }});
</script>
</head>
<body>
{''.join(chapters_html)}
</body>
</html>
"""


def main() -> None:
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html = build_html()
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"wrote {OUT_HTML} ({len(html):,} bytes)")

    cmd = [
        "google-chrome",
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--virtual-time-budget=20000",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={OUT_PDF}",
        "--no-pdf-header-footer",
        OUT_HTML.as_uri(),
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"wrote {OUT_PDF}")


if __name__ == "__main__":
    main()
