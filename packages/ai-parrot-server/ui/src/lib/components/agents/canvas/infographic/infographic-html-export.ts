/**
 * Infographic HTML Export — FEAT-039
 *
 * Renders InfographicBlock[] to a self-contained HTML document with inline CSS.
 * Charts are embedded as base64 PNG images via ECharts getDataURL().
 * The output is suitable for saving as a file, printing, or sending to a backend
 * for PDF generation.
 */

import type {
  InfographicBlock,
  TitleBlockData,
  HeroCardBlockData,
  SummaryBlockData,
  ChartBlockData,
  BulletListBlockData,
  TableBlockData,
  ImageBlockData,
  QuoteBlockData,
  CalloutBlockData,
  DividerBlockData,
  TimelineBlockData,
  ProgressBlockData,
  TrendDirection,
  CalloutLevel,
} from "./infographic-types";

// ─── Chart Image Collection ──────────────────────────────────────────────────

/**
 * Collect base64 data URLs from all ECharts instances inside a container.
 * Returns a Map keyed by the chart's index position in the blocks array.
 */
export function collectChartImages(
  containerEl: HTMLElement,
  blocks: InfographicBlock[],
): Map<number, string> {
  const map = new Map<number, string>();

  // Collect all chart canvases from the container
  const chartContainers =
    containerEl.querySelectorAll<HTMLDivElement>(".echarts-container");

  // Track which chart container corresponds to which block index
  let chartContainerIdx = 0;
  blocks.forEach((block, blockIdx) => {
    if (block.type !== "chart") return;

    const el = chartContainers[chartContainerIdx];
    chartContainerIdx++;

    if (!el) return;

    // Get the data URL directly from the canvas element rendered by ECharts
    const canvas = el.querySelector("canvas");
    if (canvas) {
      try {
        map.set(blockIdx, canvas.toDataURL("image/png"));
      } catch {
        // Canvas tainted or unavailable
      }
    }
  });

  return map;
}

// ─── Escape Helper ───────────────────────────────────────────────────────────

function esc(text: string | number | null | undefined): string {
  if (text === null || text === undefined) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Block Renderers ─────────────────────────────────────────────────────────

function renderTitle(b: TitleBlockData): string {
  let html = `<div style="width:100%;border-radius:8px;overflow:hidden;background:linear-gradient(135deg,#4f46e5,#6366f1);color:#fff;padding:2rem;text-align:center;">`;
  if (b.logo_url) {
    html += `<img src="${esc(b.logo_url)}" alt="Logo" style="height:40px;margin:0 auto 1rem;display:block;object-fit:contain;" />`;
  }
  html += `<h1 style="font-size:1.875rem;font-weight:700;line-height:1.2;margin:0 0 0.5rem;">${esc(b.title)}</h1>`;
  if (b.subtitle) {
    html += `<p style="font-size:1rem;opacity:0.85;margin:0 0 0.75rem;">${esc(b.subtitle)}</p>`;
  }
  if (b.author || b.date) {
    html += `<div style="display:flex;align-items:center;justify-content:center;gap:0.75rem;font-size:0.875rem;opacity:0.7;margin-top:0.5rem;">`;
    if (b.author) html += `<span>${esc(b.author)}</span>`;
    if (b.author && b.date) html += `<span>&middot;</span>`;
    if (b.date) html += `<span>${esc(b.date)}</span>`;
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function renderHeroCard(b: HeroCardBlockData): string {
  const borderTop = b.color ? `border-top:3px solid ${esc(b.color)};` : "";
  const trendColor: Record<TrendDirection, string> = {
    up: "#10b981",
    down: "#ef4444",
    flat: "#6b7280",
  };
  const trendArrow: Record<TrendDirection, string> = {
    up: "&#8599;",
    down: "&#8600;",
    flat: "&#8594;",
  };

  let html = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:12px;border:1px solid #e5e7eb;background:#fff;padding:1.25rem;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,0.05);gap:0.25rem;${borderTop}">`;
  html += `<div style="font-size:1.875rem;font-weight:700;color:#1a1a1a;line-height:1;">${esc(b.value)}</div>`;
  html += `<div style="font-size:0.75rem;color:#6b7280;font-weight:500;margin-top:0.25rem;">${esc(b.label)}</div>`;
  if (b.trend) {
    html += `<div style="display:flex;align-items:center;gap:0.25rem;margin-top:0.25rem;font-size:0.75rem;color:${trendColor[b.trend]};">`;
    html += `<span>${trendArrow[b.trend]}</span>`;
    if (b.trend_value !== undefined)
      html += `<span>${esc(b.trend_value)}</span>`;
    if (b.comparison_period)
      html += `<span style="color:#6b7280;">vs ${esc(b.comparison_period)}</span>`;
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function renderSummary(b: SummaryBlockData): string {
  const bg = b.highlight
    ? "background:rgba(79,70,229,0.08);border-left:4px solid #6366f1;"
    : "background:#fff;border:1px solid #e5e7eb;";
  let html = `<div style="border-radius:8px;padding:1.25rem;${bg}">`;
  if (b.title) {
    html += `<h3 style="font-size:1rem;font-weight:600;color:#1a1a1a;margin:0 0 0.5rem;">${esc(b.title)}</h3>`;
  }
  // Render basic markdown (bold, italic, line breaks)
  const content = esc(b.content)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\n/g, "<br>");
  html += `<div style="font-size:0.875rem;color:#1a1a1a;line-height:1.6;">${content}</div>`;
  html += `</div>`;
  return html;
}

function renderChart(_b: ChartBlockData, chartImage?: string): string {
  let html = `<div style="border-radius:8px;border:1px solid #e5e7eb;background:#fff;padding:1rem;">`;
  if (_b.title) {
    html += `<h3 style="font-size:0.875rem;font-weight:600;color:#1a1a1a;margin:0 0 0.25rem;">${esc(_b.title)}</h3>`;
  }
  if (_b.description) {
    html += `<p style="font-size:0.75rem;color:#6b7280;margin:0 0 0.75rem;">${esc(_b.description)}</p>`;
  }
  if (chartImage) {
    html += `<div style="width:100%;text-align:center;"><img src="${chartImage}" alt="${esc(_b.title || "Chart")}" style="max-width:100%;height:auto;" /></div>`;
  } else {
    // Fallback: render data as a simple table
    html += `<div style="font-size:0.75rem;color:#6b7280;text-align:center;padding:2rem;">`;
    html += `<p style="margin:0 0 0.5rem;">[${esc(_b.chart_type)} chart]</p>`;
    html += renderChartFallbackTable(_b);
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function renderChartFallbackTable(b: ChartBlockData): string {
  let html = `<table style="width:100%;border-collapse:collapse;font-size:0.75rem;">`;
  html += `<thead><tr style="background:#f3f4f6;">`;
  html += `<th style="padding:0.375rem 0.75rem;text-align:left;border-bottom:1px solid #e5e7eb;"></th>`;
  for (const label of b.labels) {
    html += `<th style="padding:0.375rem 0.75rem;text-align:right;border-bottom:1px solid #e5e7eb;">${esc(label)}</th>`;
  }
  html += `</tr></thead><tbody>`;
  for (const s of b.series) {
    html += `<tr>`;
    html += `<td style="padding:0.375rem 0.75rem;border-bottom:1px solid #f3f4f6;font-weight:500;">${esc(s.name)}</td>`;
    for (const v of s.values) {
      html += `<td style="padding:0.375rem 0.75rem;text-align:right;border-bottom:1px solid #f3f4f6;">${v ?? "—"}</td>`;
    }
    html += `</tr>`;
  }
  html += `</tbody></table>`;
  return html;
}

function renderBulletList(b: BulletListBlockData): string {
  let html = `<div style="border-radius:8px;background:#fff;border:1px solid #e5e7eb;padding:1.25rem;">`;
  if (b.title) {
    html += `<h3 style="font-size:1rem;font-weight:600;color:#1a1a1a;margin:0 0 0.75rem;">${esc(b.title)}</h3>`;
  }
  const tag = b.ordered ? "ol" : "ul";
  const listStyle = b.ordered ? "decimal" : "disc";
  html += `<${tag} style="margin:0;padding-left:1.5rem;list-style:${listStyle};">`;
  for (const item of b.items) {
    html += `<li style="font-size:0.875rem;color:#1a1a1a;margin-bottom:0.375rem;line-height:1.5;">${esc(item)}</li>`;
  }
  html += `</${tag}>`;
  html += `</div>`;
  return html;
}

function renderTable(b: TableBlockData): string {
  let html = `<div style="border-radius:8px;border:1px solid #e5e7eb;background:#fff;overflow:hidden;">`;
  if (b.title) {
    html += `<div style="padding:0.75rem 1rem;border-bottom:1px solid #e5e7eb;background:#f9fafb;">`;
    html += `<h3 style="font-size:0.875rem;font-weight:600;color:#1a1a1a;margin:0;">${esc(b.title)}</h3>`;
    html += `</div>`;
  }
  html += `<div style="overflow-x:auto;">`;
  html += `<table style="width:100%;border-collapse:collapse;font-size:0.875rem;">`;
  html += `<thead><tr style="background:#4f46e5;color:#fff;">`;
  for (const col of b.columns) {
    html += `<th style="padding:0.5rem 1rem;text-align:left;font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;white-space:nowrap;">${esc(col)}</th>`;
  }
  html += `</tr></thead>`;
  html += `<tbody>`;
  b.rows.forEach((row, rowIdx) => {
    const bg = rowIdx % 2 === 0 ? "#fff" : "#f9fafb";
    html += `<tr style="background:${bg};">`;
    row.forEach((cell, cellIdx) => {
      const fw =
        b.highlight_first_column && cellIdx === 0
          ? "font-weight:600;color:#1a1a1a;"
          : "color:#374151;";
      html += `<td style="padding:0.5rem 1rem;border-bottom:1px solid #f3f4f6;font-size:0.75rem;${fw}">${esc(cell as string)}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table>`;
  html += `</div></div>`;
  return html;
}

function renderImage(b: ImageBlockData): string {
  let html = `<figure style="border-radius:8px;background:#fff;border:1px solid #e5e7eb;padding:0.75rem;margin:0;">`;
  const widthAttr = b.width ? ` width="${esc(b.width)}"` : "";
  const heightAttr = b.height ? ` height="${esc(b.height)}"` : "";
  html += `<img src="${esc(b.url)}" alt="${esc(b.alt)}"${widthAttr}${heightAttr} style="border-radius:6px;max-width:100%;height:auto;display:block;margin:0 auto;" loading="lazy" />`;
  if (b.caption) {
    html += `<figcaption style="font-size:0.75rem;color:#6b7280;text-align:center;margin-top:0.5rem;">${esc(b.caption)}</figcaption>`;
  }
  html += `</figure>`;
  return html;
}

function renderQuote(b: QuoteBlockData): string {
  let html = `<blockquote style="border-radius:8px;background:#fff;border:1px solid #e5e7eb;border-left:4px solid rgba(99,102,241,0.6);padding:1.25rem;margin:0;">`;
  html += `<p style="font-size:0.875rem;font-style:italic;color:#1a1a1a;line-height:1.6;margin:0;">&ldquo;${esc(b.text)}&rdquo;</p>`;
  if (b.author || b.source) {
    html += `<footer style="margin-top:0.5rem;font-size:0.75rem;color:#6b7280;">`;
    if (b.author)
      html += `<span style="font-weight:500;">&mdash; ${esc(b.author)}</span>`;
    if (b.source)
      html += `<span style="margin-left:0.25rem;">(${esc(b.source)})</span>`;
    html += `</footer>`;
  }
  html += `</blockquote>`;
  return html;
}

function renderCallout(b: CalloutBlockData): string {
  const colors: Record<CalloutLevel, { border: string; bg: string }> = {
    info: { border: "#3b82f6", bg: "rgba(59,130,246,0.08)" },
    success: { border: "#22c55e", bg: "rgba(34,197,94,0.08)" },
    warning: { border: "#f59e0b", bg: "rgba(245,158,11,0.08)" },
    error: { border: "#ef4444", bg: "rgba(239,68,68,0.08)" },
    tip: { border: "#a855f7", bg: "rgba(168,85,247,0.08)" },
  };
  const c = colors[b.level] ?? colors.info;
  const icons: Record<CalloutLevel, string> = {
    info: "ℹ️",
    success: "✅",
    warning: "⚠️",
    error: "❌",
    tip: "💡",
  };

  let html = `<div style="border-radius:8px;border:1px solid #e5e7eb;border-left:4px solid ${c.border};background:${c.bg};padding:1.25rem;">`;
  html += `<div style="display:flex;align-items:flex-start;gap:0.5rem;">`;
  html += `<span style="font-size:1rem;flex-shrink:0;">${icons[b.level] ?? icons.info}</span>`;
  html += `<div>`;
  if (b.title) {
    html += `<h3 style="font-size:0.875rem;font-weight:600;color:#1a1a1a;margin:0 0 0.25rem;">${esc(b.title)}</h3>`;
  }
  html += `<p style="font-size:0.875rem;color:#1a1a1a;line-height:1.6;margin:0;">${esc(b.content)}</p>`;
  html += `</div></div></div>`;
  return html;
}

function renderDivider(b: DividerBlockData): string {
  const borderStyle = b.style ?? "solid";
  if (b.label) {
    return `<div style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0;">
			<hr style="flex:1;border:none;border-top:1px ${borderStyle} #e5e7eb;margin:0;" />
			<span style="font-size:0.75rem;color:#6b7280;font-weight:500;flex-shrink:0;">${esc(b.label)}</span>
			<hr style="flex:1;border:none;border-top:1px ${borderStyle} #e5e7eb;margin:0;" />
		</div>`;
  }
  return `<hr style="border:none;border-top:1px ${borderStyle} #e5e7eb;margin:0.5rem 0;" />`;
}

function renderTimeline(b: TimelineBlockData): string {
  let html = `<div style="border-radius:8px;background:#fff;border:1px solid #e5e7eb;padding:1.25rem;">`;
  if (b.title) {
    html += `<h3 style="font-size:1rem;font-weight:600;color:#1a1a1a;margin:0 0 1rem;">${esc(b.title)}</h3>`;
  }
  html += `<div style="position:relative;padding-left:1.5rem;">`;
  // Vertical line
  html += `<div style="position:absolute;left:0.5rem;top:0.25rem;bottom:0.25rem;width:1px;background:#e5e7eb;"></div>`;
  b.items.forEach((item, i) => {
    const dotColor = item.color ?? "#6366f1";
    const pb = i < b.items.length - 1 ? "padding-bottom:1.25rem;" : "";
    html += `<div style="position:relative;${pb}">`;
    html += `<div style="position:absolute;left:-1rem;top:0.25rem;width:0.75rem;height:0.75rem;border-radius:50%;background:${esc(dotColor)};border:2px solid #fff;"></div>`;
    html += `<div>`;
    if (item.date)
      html += `<span style="font-size:0.75rem;color:#6b7280;">${esc(item.date)}</span>`;
    html += `<h4 style="font-size:0.875rem;font-weight:500;color:#1a1a1a;margin:0;">${esc(item.title)}</h4>`;
    if (item.description)
      html += `<p style="font-size:0.75rem;color:#6b7280;margin:0.125rem 0 0;">${esc(item.description)}</p>`;
    html += `</div></div>`;
  });
  html += `</div></div>`;
  return html;
}

function renderProgress(b: ProgressBlockData): string {
  let html = `<div style="border-radius:8px;background:#fff;border:1px solid #e5e7eb;padding:1.25rem;">`;
  if (b.title) {
    html += `<h3 style="font-size:1rem;font-weight:600;color:#1a1a1a;margin:0 0 0.75rem;">${esc(b.title)}</h3>`;
  }
  for (const item of b.items) {
    const max = item.max ?? 100;
    const pct = Math.min(100, Math.round((item.value / max) * 100));
    const color = item.color ?? "#6366f1";
    html += `<div style="margin-bottom:0.75rem;">`;
    html += `<div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:0.25rem;">`;
    html += `<span style="color:#1a1a1a;font-weight:500;">${esc(item.label)}</span>`;
    html += `<span style="color:#6b7280;">${pct}%</span>`;
    html += `</div>`;
    html += `<div style="height:0.5rem;border-radius:9999px;background:#f3f4f6;overflow:hidden;">`;
    html += `<div style="height:100%;border-radius:9999px;width:${pct}%;background:${esc(color)};"></div>`;
    html += `</div></div>`;
  }
  html += `</div>`;
  return html;
}

// ─── Block Dispatcher ────────────────────────────────────────────────────────

function renderBlock(
  block: InfographicBlock,
  chartImages: Map<number, string>,
  blockIndex: number,
): string {
  switch (block.type) {
    case "title":
      return renderTitle(block);
    case "hero_card":
      return renderHeroCard(block);
    case "summary":
      return renderSummary(block);
    case "chart":
      return renderChart(block, chartImages.get(blockIndex));
    case "bullet_list":
      return renderBulletList(block);
    case "table":
      return renderTable(block);
    case "image":
      return renderImage(block);
    case "quote":
      return renderQuote(block);
    case "callout":
      return renderCallout(block);
    case "divider":
      return renderDivider(block);
    case "timeline":
      return renderTimeline(block);
    case "progress":
      return renderProgress(block);
    default:
      return `<div style="border-radius:8px;border:1px dashed #d1d5db;padding:1rem;text-align:center;font-size:0.75rem;color:#9ca3af;">[${esc((block as InfographicBlock).type)}]</div>`;
  }
}

// ─── Hero Card Grouping ──────────────────────────────────────────────────────

function groupConsecutiveHeroCards(
  blocks: InfographicBlock[],
): Array<
  | { type: "hero_group"; blocks: HeroCardBlockData[]; startIndex: number }
  | { type: "single"; block: InfographicBlock; index: number }
> {
  const result: Array<
    | { type: "hero_group"; blocks: HeroCardBlockData[]; startIndex: number }
    | { type: "single"; block: InfographicBlock; index: number }
  > = [];
  let i = 0;
  while (i < blocks.length) {
    if (blocks[i].type === "hero_card") {
      const start = i;
      const group: HeroCardBlockData[] = [];
      while (i < blocks.length && blocks[i].type === "hero_card") {
        group.push(blocks[i] as { type: "hero_card" } & HeroCardBlockData);
        i++;
      }
      result.push({ type: "hero_group", blocks: group, startIndex: start });
    } else {
      result.push({ type: "single", block: blocks[i], index: i });
      i++;
    }
  }
  return result;
}

// ─── Main Export Function ────────────────────────────────────────────────────

/**
 * Export InfographicBlock[] to a self-contained HTML string with inline CSS.
 * Charts are embedded as base64 images if provided in chartImages.
 */
export function exportBlocksToHtml(
  blocks: InfographicBlock[],
  chartImages: Map<number, string> = new Map(),
): string {
  const grouped = groupConsecutiveHeroCards(blocks);

  let body = "";
  for (const entry of grouped) {
    if (entry.type === "hero_group") {
      // Responsive grid for hero cards
      const cols = Math.min(entry.blocks.length, 4);
      body += `<div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:1rem;">`;
      entry.blocks.forEach((heroBlock) => {
        body += renderHeroCard(heroBlock);
      });
      body += `</div>`;
    } else {
      body += renderBlock(entry.block, chartImages, entry.index);
    }
  }

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Infographic</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;padding:2rem;background:#fff;color:#1a1a1a;max-width:960px;margin:0 auto}
.blocks{display:flex;flex-direction:column;gap:1.5rem}
img{max-width:100%}
@media print{
  body{padding:0.5rem;max-width:none}
  @page{margin:1cm}
}
</style>
</head>
<body>
<div class="blocks">
${body}
</div>
</body>
</html>`;
}
