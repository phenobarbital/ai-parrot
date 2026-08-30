/**
 * Canvas Block Exporter — serializes CanvasBlock[] to self-contained HTML documents.
 *
 * Supports export of individual canvas tabs and all canvas tabs combined.
 */
import { markdownToHtml } from "$lib/utils/markdown";
import { isCanvasBlockArray } from "./canvas-block-types";
import type {
  CanvasBlock,
  MarkdownBlockData,
  ChartBlockData,
  ImageBlockData,
  TableBlockData,
  MapBlockData,
  HtmlBlockData,
  TitleBlockData,
  HeroCardBlockData,
  SummaryBlockData,
  QuoteBlockData,
  CalloutBlockData,
  DividerBlockData,
  BulletListBlockData,
} from "./canvas-block-types";
import type { CanvasTab } from "./canvas-tab-manager.svelte.js";

// ─── Shared CSS for exported documents ───────────────────────────────────────

const EXPORT_CSS = `
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#f8fafc;color:#0f172a;padding:0;line-height:1.6}
.container{max-width:800px;margin:0 auto;padding:32px 24px}
h1,h2,h3,h4,h5,h6{margin-bottom:8px;line-height:1.3}
h1{font-size:2rem;font-weight:700;margin-bottom:16px;color:#0f172a}
h2{font-size:1.5rem;font-weight:600;color:#1e293b}
h3{font-size:1.25rem;font-weight:600;color:#334155}
p{margin-bottom:12px;color:#475569}
ul,ol{margin-bottom:12px;padding-left:24px}
li{margin-bottom:4px}
pre{background:#1e293b;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;margin-bottom:16px;font-size:0.875rem}
code{background:#e2e8f0;padding:2px 6px;border-radius:4px;font-size:0.875rem;font-family:monospace}
pre code{background:transparent;padding:0}
blockquote{border-left:4px solid #6366f1;padding:8px 16px;background:#eef2ff;border-radius:0 8px 8px 0;margin-bottom:12px;color:#334155}
a{color:#6366f1;text-decoration:underline}
img{max-width:100%;height:auto;border-radius:8px;margin-bottom:12px}
.block-section{margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #e2e8f0}
.block-section:last-child{border-bottom:none}
.placeholder-card{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:8px;padding:16px;color:#64748b;font-size:0.875rem;margin-bottom:12px}
table{width:100%;border-collapse:collapse;margin-bottom:16px;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06)}
thead{background:#6366f1;color:#fff}
th{padding:10px 14px;text-align:left;font-size:0.78rem;font-weight:600;text-transform:uppercase;letter-spacing:0.04em}
td{padding:9px 14px;font-size:0.85rem;border-bottom:1px solid #f1f5f9}
tbody tr:nth-child(even){background:#f8fafc}
tbody tr:hover{background:#eef2ff}
.tab-section{margin-bottom:48px}
.tab-title{font-size:1.75rem;font-weight:700;color:#0f172a;margin-bottom:20px;padding-bottom:12px;border-bottom:3px solid #6366f1}
.footer{margin-top:40px;padding-top:16px;border-top:1px solid #e2e8f0;text-align:center;font-size:0.75rem;color:#94a3b8}
@media print{
  body{background:#fff;padding:0}
  .container{padding:16px}
  pre{background:#f1f5f9;color:#1e293b}
}
@media(max-width:600px){
  .container{padding:16px 12px}
  h1{font-size:1.5rem}
}
`.trim();

// ─── Block Serializers ────────────────────────────────────────────────────────

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function blockToHtml(
  block: CanvasBlock,
  chartImages?: Map<string, string>,
): string {
  switch (block.type) {
    case "markdown": {
      const d = block.data as MarkdownBlockData;
      if (!d.content?.trim()) return "";
      return `<div class="block-section">${markdownToHtml(d.content, { allowHtml: true, allowSvg: true, allowImages: true })}</div>`;
    }

    case "chart": {
      const d = block.data as ChartBlockData;
      const imgDataUrl = chartImages?.get(block.id);
      const title = d.config.title || "Chart";
      if (imgDataUrl) {
        return `<div class="block-section">
  <h3>${escapeHtml(title)}</h3>
  <img src="${imgDataUrl}" alt="${escapeHtml(title)}" />
</div>`;
      }
      return `<div class="block-section placeholder-card">
  <strong>Chart: ${escapeHtml(title)}</strong>
  <p style="margin-top:4px;font-size:0.8rem">Chart image not available in export. Data: ${d.data.length} rows.</p>
</div>`;
    }

    case "image": {
      const d = block.data as ImageBlockData;
      if (!d.url) return "";
      const captionHtml = d.caption
        ? `<p style="text-align:center;font-size:0.8rem;color:#64748b;margin-top:4px">${escapeHtml(d.caption)}</p>`
        : "";
      return `<div class="block-section">
  <img src="${escapeHtml(d.url)}" alt="${escapeHtml(d.alt || "")}" />
  ${captionHtml}
</div>`;
    }

    case "table": {
      const d = block.data as TableBlockData;
      if (!d.rows.length) return "";
      const cols = d.columns ?? Object.keys(d.rows[0]);
      const headers = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
      const rows = d.rows
        .map(
          (row) =>
            `<tr>${cols.map((c) => `<td>${escapeHtml(String(row[c] ?? ""))}</td>`).join("")}</tr>`,
        )
        .join("");
      return `<div class="block-section">
  <table>
    <thead><tr>${headers}</tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>`;
    }

    case "map": {
      const d = block.data as MapBlockData;
      const title = d.config.title || "Map";
      return `<div class="block-section placeholder-card">
  <strong>Map: ${escapeHtml(title)}</strong>
  <p style="margin-top:4px;font-size:0.8rem">${d.data.length} markers. Interactive map not available in static export.</p>
</div>`;
    }

    case "html": {
      const d = block.data as HtmlBlockData;
      if (!d.html?.trim()) return "";
      // SECURITY: HTML blocks contain user-authored HTML. Sanitize before embedding
      // in the exported document to prevent XSS in downloaded files.
      const sanitized = d.html
        .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
        .replace(/\bon\w+\s*=\s*"[^"]*"/gi, "")
        .replace(/\bon\w+\s*=\s*'[^']*'/gi, "")
        .replace(/javascript\s*:/gi, "void:");
      return `<div class="block-section">${sanitized}</div>`;
    }

    case "interactive":
      // Omit interactive blocks from export
      return "";

    case "title": {
      const d = block.data as TitleBlockData;
      if (!d.title?.trim()) return "";
      const subtitleHtml = d.subtitle?.trim()
        ? `<h2>${escapeHtml(d.subtitle)}</h2>`
        : "";
      return `<div class="block-section"><h1>${escapeHtml(d.title)}</h1>${subtitleHtml}</div>`;
    }

    case "hero_card": {
      const d = block.data as HeroCardBlockData;
      const trendHtml = d.trend
        ? `<p style="font-size:0.8rem;color:${d.trend === "up" ? "#10b981" : d.trend === "down" ? "#ef4444" : "#6b7280"}">${d.trend === "up" ? "▲" : d.trend === "down" ? "▼" : "—"} ${escapeHtml(d.trend_value ?? "")}</p>`
        : "";
      return `<div class="block-section" style="text-align:center;border:1px solid #e2e8f0;border-radius:12px;padding:20px;${d.color ? `border-top:3px solid ${escapeHtml(d.color)}` : ""}">
  <div style="font-size:2rem;font-weight:bold">${escapeHtml(d.value)}</div>
  <div style="font-size:0.8rem;color:#64748b;margin-top:4px">${escapeHtml(d.label)}</div>
  ${trendHtml}
</div>`;
    }

    case "summary": {
      const d = block.data as SummaryBlockData;
      if (!d.content?.trim()) return "";
      const titleHtml = d.title ? `<h3>${escapeHtml(d.title)}</h3>` : "";
      const style = d.highlight
        ? "border-left:4px solid #3b82f6;background:#eff6ff;padding:16px;border-radius:0 8px 8px 0"
        : "";
      return `<div class="block-section" style="${style}">${titleHtml}<p>${escapeHtml(d.content)}</p></div>`;
    }

    case "quote": {
      const d = block.data as QuoteBlockData;
      if (!d.text?.trim()) return "";
      const authorHtml = d.author
        ? `<footer style="margin-top:8px;font-size:0.8rem;color:#64748b">— ${escapeHtml(d.author)}${d.source ? ` (${escapeHtml(d.source)})` : ""}</footer>`
        : "";
      return `<blockquote class="block-section" style="border-left:4px solid #94a3b8;padding:12px 16px;margin:0;background:#f8fafc;border-radius:0 8px 8px 0"><p style="font-style:italic">${escapeHtml(d.text)}</p>${authorHtml}</blockquote>`;
    }

    case "callout": {
      const d = block.data as CalloutBlockData;
      if (!d.content?.trim()) return "";
      const colors: Record<string, string> = {
        info: "#3b82f6",
        success: "#10b981",
        warning: "#f59e0b",
        error: "#ef4444",
        tip: "#8b5cf6",
      };
      const color = colors[d.level] ?? colors.info;
      const titleHtml = d.title
        ? `<strong>${escapeHtml(d.title)}</strong><br>`
        : "";
      return `<div class="block-section" style="border-left:4px solid ${color};background:${color}10;padding:12px 16px;border-radius:0 8px 8px 0">${titleHtml}${escapeHtml(d.content)}</div>`;
    }

    case "divider": {
      const d = block.data as DividerBlockData;
      const style = d.style ?? "solid";
      if (d.label) {
        return `<div class="block-section" style="display:flex;align-items:center;gap:12px"><div style="flex:1;border-top:1px ${style} #e2e8f0"></div><span style="font-size:0.75rem;color:#94a3b8">${escapeHtml(d.label)}</span><div style="flex:1;border-top:1px ${style} #e2e8f0"></div></div>`;
      }
      return `<hr class="block-section" style="border:none;border-top:1px ${style} #e2e8f0;margin:16px 0">`;
    }

    case "bullet_list": {
      const d = block.data as BulletListBlockData;
      const items = d.items.filter((i) => i.trim());
      if (!items.length) return "";
      const titleHtml = d.title ? `<h3>${escapeHtml(d.title)}</h3>` : "";
      const tag = d.ordered ? "ol" : "ul";
      const listItems = items.map((i) => `<li>${escapeHtml(i)}</li>`).join("");
      return `<div class="block-section">${titleHtml}<${tag}>${listItems}</${tag}></div>`;
    }

    default:
      return "";
  }
}

// ─── Main Export Functions ────────────────────────────────────────────────────

/**
 * Exports a CanvasBlock[] to a self-contained HTML document string.
 *
 * @param includeTitle - When true, renders an `<h1>` heading with the canvas title.
 *   Defaults to false so "Export as HTML" exports only block content without an injected heading.
 */
export function exportBlocksToHtml(
  blocks: CanvasBlock[],
  title?: string,
  chartImages?: Map<string, string>,
  includeTitle: boolean = false,
): string {
  const docTitle = title || "Canvas Export";
  const blockSections = blocks
    .map((b) => blockToHtml(b, chartImages))
    .filter(Boolean)
    .join("\n");

  const now = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${escapeHtml(docTitle)}</title>
  <style>${EXPORT_CSS}</style>
</head>
<body>
  <div class="container">
    ${includeTitle ? `<h1>${escapeHtml(docTitle)}</h1>` : ""}
    ${blockSections || '<p style="color:#94a3b8">Empty canvas</p>'}
    <div class="footer">Exported from Navigator on ${now}</div>
  </div>
</body>
</html>`;
}

/**
 * Exports all canvas tabs as a single HTML document.
 * Skips audio tabs. For infographic tabs, embeds the HTML.
 * For spreadsheet tabs, generates an HTML table.
 */
export function exportAllTabsToHtml(tabs: CanvasTab[]): string {
  const now = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const sections = tabs
    .filter((tab) => tab.type !== "audio")
    .map((tab) => {
      let content = "";

      if (isCanvasBlockArray(tab.data)) {
        content = (tab.data as CanvasBlock[])
          .map((b) => blockToHtml(b))
          .filter(Boolean)
          .join("\n");
      } else if (
        tab.type === "infographic" &&
        typeof tab.data === "string" &&
        tab.data.trim()
      ) {
        // Embed infographic HTML body content
        const bodyMatch = (tab.data as string).match(
          /<body[^>]*>([\s\S]*?)<\/body>/i,
        );
        content = bodyMatch ? bodyMatch[1] : (tab.data as string);
      } else if (tab.type === "spreadsheet" && Array.isArray(tab.data)) {
        const rows = tab.data as Record<string, unknown>[];
        if (rows.length > 0) {
          const cols = Object.keys(rows[0]);
          const headers = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
          const rowHtml = rows
            .map(
              (row) =>
                `<tr>${cols.map((c) => `<td>${escapeHtml(String(row[c] ?? ""))}</td>`).join("")}</tr>`,
            )
            .join("");
          content = `<table><thead><tr>${headers}</tr></thead><tbody>${rowHtml}</tbody></table>`;
        }
      }

      return `<div class="tab-section">
  <div class="tab-title">${escapeHtml(tab.title)}</div>
  ${content || '<p style="color:#94a3b8">Empty tab</p>'}
</div>`;
    })
    .join(
      '\n<hr style="border:none;border-top:2px solid #e2e8f0;margin:32px 0" />\n',
    );

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Canvas Export — All Tabs</title>
  <style>${EXPORT_CSS}</style>
</head>
<body>
  <div class="container">
    <h1>Canvas Export</h1>
    ${sections || '<p style="color:#94a3b8">No exportable content</p>'}
    <div class="footer">Exported from Navigator on ${now}</div>
  </div>
</body>
</html>`;
}

// ─── Browser Utilities ────────────────────────────────────────────────────────

import { browser } from "$app/environment";

/**
 * Triggers a browser download of the given HTML string as a .html file.
 */
export function downloadHtml(html: string, filename: string): void {
  if (!browser) return;
  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Renders the HTML in a hidden iframe and triggers the browser's print dialog.
 */
export function printHtml(html: string): void {
  if (!browser) return;
  const iframe = document.createElement("iframe");
  iframe.style.display = "none";
  document.body.appendChild(iframe);
  iframe.srcdoc = html;
  iframe.onload = () => {
    iframe.contentWindow?.print();
    setTimeout(() => iframe.remove(), 1000);
  };
}
