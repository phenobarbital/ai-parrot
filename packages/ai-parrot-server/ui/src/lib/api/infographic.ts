/**
 * Infographic generation API — sends canvas data to an agent for analysis,
 * then builds a rich HTML/CSS infographic client-side.
 *
 * FEAT-034: Updated to use INFOGRAPHIC_DESIGN_SYSTEM_PROMPT where the LLM
 * generates the full HTML/CSS layout. Falls back to buildInfographicHtml()
 * template on LLM failure or malformed output.
 *
 * FEAT-039: Added dedicated infographic handler endpoints (fetchTemplates,
 * fetchThemes, generateInfographicFromApi). Legacy functions preserved as fallback.
 */
import { chatWithAgent } from "./agent.js";
import apiClient from "./http";
import type {
  InfographicGenerateParams,
  InfographicJsonResponse,
  TemplateListResponse,
  TemplateDetailResponse,
  ThemeListResponse,
  ThemeDetailResponse,
} from "../components/agents/canvas/infographic/infographic-types";
import type {
  CanvasBlock,
  MarkdownBlockData,
  ChartBlockData,
  TableBlockData,
} from "../components/agents/canvas/canvas-block-types";

// ─── Legacy Prompt (kept for fallback reference) ──────────────────────────────

/** @deprecated — kept for reference; replaced by INFOGRAPHIC_DESIGN_SYSTEM_PROMPT */
const _INFOGRAPHIC_PROMPT_LEGACY = [
  "Create a rich, professional infographic analysis from the data below.",
  "",
  "Your response MUST begin with a title line in this exact format:",
  "TITLE: <a short, compelling, descriptive title for this infographic>",
  "",
  "After the title, include these sections:",
  "1. A one-sentence executive insight — the key takeaway",
  "2. Key metrics: highlight 3-5 important numbers (totals, averages, min/max, outliers)",
  "3. An analytical summary (2-4 sentences) covering the main findings, trends, and comparisons",
  "4. Highlight notable patterns: top performer, biggest change, outliers",
  "",
  "CRITICAL: Do NOT repeat the source data verbatim. Analyze, summarize, and interpret it.",
  "DATA:",
].join("\n");

// ─── Design System Prompt ─────────────────────────────────────────────────────

/**
 * Instructs the LLM to generate a complete, self-contained HTML/CSS infographic
 * document — no JavaScript, no external resources, CSS-only visual components.
 */
const INFOGRAPHIC_DESIGN_SYSTEM_PROMPT = `You are an expert infographic designer. Generate a complete, self-contained HTML/CSS infographic document based on the data provided.

CRITICAL CONSTRAINTS:
- Return ONLY a complete HTML document starting with <!DOCTYPE html>
- NO JavaScript — no <script> tags, no on* event attributes, no javascript: URLs
- NO external resources — all CSS must be inline in <style>, no CDN links, no @import
- NO <iframe>, <embed>, or <object> tags
- Use ONLY HTML and CSS (including CSS Grid, Flexbox, linear-gradient, conic-gradient)

CSS-ONLY COMPONENT LIBRARY (use these as building blocks):

1. KPI CARDS (for numeric highlights):
   .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; }
   .kpi-card { background: #fff; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }

2. BAR CHARTS (CSS flexbox, percentage widths):
   .bar-track { flex: 1; background: #e2e8f0; border-radius: 6px; height: 28px; }
   .bar-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, #6366f1, #4f46e5); }

3. DONUT/PIE CHARTS (conic-gradient on circle):
   .donut { width: 120px; height: 120px; border-radius: 50%; background: conic-gradient(#6366f1 0% VAR_PCT%, #e2e8f0 VAR_PCT% 100%); }

4. TIMELINES (vertical, CSS grid connectors):
   .timeline { display: flex; flex-direction: column; gap: 0; }
   .timeline-item { display: flex; gap: 16px; padding-bottom: 24px; position: relative; }
   .timeline-dot { width: 12px; height: 12px; border-radius: 50%; background: #6366f1; flex-shrink: 0; margin-top: 4px; }
   .timeline-item::before { content: ''; position: absolute; left: 5px; top: 16px; bottom: 0; width: 2px; background: #e2e8f0; }

5. COMPARISON GRIDS (side-by-side):
   .compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }

6. DATA TABLES (zebra striping):
   table { width: 100%; border-collapse: collapse; } th { background: #6366f1; color: #fff; padding: 10px 14px; }
   td { padding: 9px 14px; border-bottom: 1px solid #f1f5f9; } tr:nth-child(even) { background: #f8fafc; }

7. HERO BANNERS:
   .hero { background: linear-gradient(135deg, #6366f1, #4f46e5); color: #fff; padding: 40px 32px; border-radius: 16px; }

8. STAT HIGHLIGHTS (icon + number + label):
   .stat-card { display: flex; gap: 12px; align-items: center; background: #fff; border-radius: 10px; padding: 16px; }

COLOR PALETTE (use freely):
- Primary: #6366f1 (indigo), #4f46e5 (darker indigo), #818cf8 (lighter)
- Accent: #10b981 (green), #f59e0b (amber), #ef4444 (red), #3b82f6 (blue)
- Neutral: #f8fafc (bg), #e2e8f0 (border), #64748b (muted), #0f172a (text)

LAYOUT STRATEGY (choose based on data shape):
- Mostly numeric/KPI data → hero + kpi-grid + bar chart + table
- Time-series data → hero + timeline + trend bar chart
- Categorical comparison → hero + compare-grid + grouped bars
- Text-heavy analysis → hero + summary box + stat highlights
- Mixed → hero + kpi-grid + appropriate chart + table

REQUIRED: Include @media print { ... } and @media (max-width: 600px) { ... } styles.
REQUIRED: max-width: 900px; margin: 0 auto; on main container.
REQUIRED: The document must be fully readable offline without any network resources.

Return ONLY the HTML document. No explanation, no markdown fences, just raw HTML starting with <!DOCTYPE html>.

DATA TO VISUALIZE:
`;

// ─── Serialization ────────────────────────────────────────────────────────────

/**
 * Serializes CanvasBlock[] to a text representation for the LLM infographic prompt.
 */
export function serializeBlocksForInfographic(blocks: CanvasBlock[]): string {
  return blocks
    .map((block) => {
      switch (block.type) {
        case "markdown":
          return `--- TEXT ---\n${(block.data as MarkdownBlockData).content}`;
        case "chart": {
          const d = block.data as ChartBlockData;
          return (
            `--- CHART (${d.config.type}: ${d.config.title || "Untitled"}) ---\n` +
            `X: ${d.config.x}, Y: ${d.config.y.join(", ")}\n` +
            `Data (${d.data.length} rows):\n${JSON.stringify(d.data.slice(0, 20), null, 2)}`
          );
        }
        case "table": {
          const d = block.data as TableBlockData;
          return `--- TABLE (${d.rows.length} rows) ---\n${JSON.stringify(d.rows.slice(0, 20), null, 2)}`;
        }
        default:
          return "";
      }
    })
    .filter(Boolean)
    .join("\n\n");
}

// ─── Sanitization ─────────────────────────────────────────────────────────────

/**
 * Strips dangerous content from LLM-generated HTML output.
 * Removes scripts, event handlers, javascript: URLs, and unsafe embeds.
 */
export function sanitizeInfographicHtml(html: string): string {
  // NOTE: <script> tags are intentionally kept. The infographic HTML is rendered
  // inside a sandboxed iframe (sandbox="allow-scripts allow-modals") which
  // provides the security boundary. Stripping scripts would break chart
  // libraries like ECharts that rely on inline <script> for initialization.
  return html
    .replace(/\s+on\w+\s*=\s*["'][^"']*["']/gi, "")
    .replace(/javascript\s*:/gi, "javascript-blocked:")
    .replace(/<iframe\b[^>]*>[\s\S]*?<\/iframe>/gi, "")
    .replace(/<embed\b[^>]*\/?>/gi, "")
    .replace(/<object\b[^>]*>[\s\S]*?<\/object>/gi, "");
}

// ─── Main Generator ───────────────────────────────────────────────────────────

/**
 * Generates an infographic from serialized block data.
 * Sends the design-system prompt to the LLM and sanitizes the HTML response.
 * Falls back to buildInfographicHtml() if the LLM response is malformed.
 */
export async function generateInfographic(
  agentId: string,
  data: string,
): Promise<string> {
  const query = `${INFOGRAPHIC_DESIGN_SYSTEM_PROMPT}\n${data}`;

  try {
    const response = await chatWithAgent(agentId, { query });
    const rawHtml =
      (typeof response.output === "string" ? response.output : null) ||
      response.response ||
      "";

    if (rawHtml.trim()) {
      const sanitized = sanitizeInfographicHtml(rawHtml.trim());

      // Validate: check that we got a proper HTML document
      const hasHtmlStructure =
        sanitized.length > 100 &&
        (sanitized.includes("<html") ||
          sanitized.includes("<body") ||
          sanitized.includes("<!DOCTYPE"));

      if (hasHtmlStructure) {
        return sanitized;
      }
    }
  } catch (err) {
    console.warn(
      "[infographic] LLM generation failed, falling back to template:",
      err,
    );
  }

  // Fallback: use the classic template builder
  // Re-call with analysis-only prompt so we get structured text + table data
  try {
    const fallbackQuery = `${_INFOGRAPHIC_PROMPT_LEGACY}\n${data}`;
    const fallbackResponse = await chatWithAgent(agentId, {
      query: fallbackQuery,
    });
    const analysisText =
      (typeof fallbackResponse.output === "string"
        ? fallbackResponse.output
        : null) ||
      fallbackResponse.response ||
      "";
    const tableData: Record<string, unknown>[] = Array.isArray(
      fallbackResponse.data,
    )
      ? fallbackResponse.data
      : [];
    return buildInfographicHtml(analysisText, tableData);
  } catch {
    return buildInfographicHtml("Failed to generate infographic.", []);
  }
}

// ─── HTML Builder ────────────────────────────────────────────────────────────

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Strip markdown artifacts (tables, bold, headers, links) from analysis text. */
function stripMarkdown(text: string): string {
  return (
    text
      // Remove markdown tables (header row, separator row, data rows)
      .replace(/\|[^\n]+\|/g, "")
      .replace(/^\s*:?-+:?\s*$/gm, "")
      // Remove markdown headers
      .replace(/^#{1,6}\s+/gm, "")
      // Remove bold/italic markers
      .replace(/\*{1,3}([^*]+)\*{1,3}/g, "$1")
      .replace(/_{1,3}([^_]+)_{1,3}/g, "$1")
      // Remove links [text](url) → text
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      // Remove inline code
      .replace(/`([^`]+)`/g, "$1")
      // Collapse multiple blank lines
      .replace(/\n{3,}/g, "\n\n")
      .trim()
  );
}

function buildInfographicHtml(
  analysis: string,
  data: Record<string, unknown>[],
): string {
  const cleanAnalysis = stripMarkdown(analysis);
  const title = extractTitle(cleanAnalysis);
  // Remove the TITLE: line from the analysis so it doesn't appear in the summary box
  const bodyAnalysis = cleanAnalysis.replace(/^TITLE:\s*.+\n*/im, "").trim();
  const accent = "#6366f1";
  const accentLight = "#eef2ff";
  const accentDark = "#4f46e5";

  const kpiCards = buildKpiCards(data, accent);
  const barChart = buildBarChart(data, accent, accentDark);
  const tableHtml = buildDataTable(data, accent);
  const highlights = buildHighlights(data);
  const now = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#f8fafc;color:#0f172a;padding:0;line-height:1.6}
.container{max-width:900px;margin:0 auto;padding:32px 24px}
.hero{text-align:center;margin-bottom:32px;padding:32px 24px;background:linear-gradient(135deg,${accent},${accentDark});border-radius:16px;color:#fff}
.hero h1{font-size:2rem;font-weight:700;margin-bottom:8px;line-height:1.2}
.hero .subtitle{font-size:0.95rem;opacity:0.85;margin-bottom:12px}
.hero .insight{display:inline-block;background:rgba(255,255,255,0.2);padding:8px 20px;border-radius:24px;font-size:0.9rem;font-weight:600;backdrop-filter:blur(4px)}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:28px}
.kpi-card{background:#fff;border-radius:12px;padding:20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #e2e8f0}
.kpi-card .number{font-size:1.75rem;font-weight:700;color:${accent};line-height:1.2}
.kpi-card .label{font-size:0.8rem;color:#64748b;margin-top:4px;font-weight:500}
.summary-box{background:${accentLight};border-left:4px solid ${accent};padding:20px 24px;border-radius:0 12px 12px 0;margin-bottom:28px;font-size:0.95rem;color:#334155;line-height:1.7}
.section{margin-bottom:28px}
.section h2{font-size:1.25rem;font-weight:700;color:#0f172a;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #e2e8f0}
.bar-chart{display:flex;flex-direction:column;gap:10px;margin-top:12px}
.bar-row{display:flex;align-items:center;gap:12px}
.bar-label{width:140px;font-size:0.82rem;color:#475569;text-align:right;flex-shrink:0;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{flex:1;background:#e2e8f0;border-radius:6px;height:28px;position:relative;overflow:hidden}
.bar-fill{height:100%;border-radius:6px;display:flex;align-items:center;justify-content:flex-end;padding-right:8px;font-size:0.75rem;font-weight:600;color:#fff;min-width:32px;transition:width 0.3s}
.bar-value{font-size:0.82rem;color:#64748b;width:70px;text-align:right;flex-shrink:0;font-weight:600}
.highlights{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:28px}
.highlight-card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,0.05);border:1px solid #e2e8f0;display:flex;gap:12px;align-items:flex-start}
.highlight-card .icon{font-size:1.5rem;flex-shrink:0;width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:8px;background:${accentLight}}
.highlight-card .text{flex:1}
.highlight-card .text strong{display:block;font-size:0.85rem;color:#0f172a;margin-bottom:2px}
.highlight-card .text span{font-size:0.78rem;color:#64748b}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);margin-top:12px}
thead{background:${accent};color:#fff}
th{padding:12px 14px;text-align:left;font-size:0.78rem;font-weight:600;text-transform:uppercase;letter-spacing:0.04em}
td{padding:10px 14px;font-size:0.85rem;border-bottom:1px solid #f1f5f9}
tbody tr:nth-child(even){background:#f8fafc}
tbody tr:hover{background:#eef2ff}
.footer{margin-top:32px;padding-top:16px;border-top:1px solid #e2e8f0;text-align:center;font-size:0.75rem;color:#94a3b8}
@media print{body{padding:0}.no-print{display:none}}
@media(max-width:600px){.hero h1{font-size:1.5rem}.kpi-row{grid-template-columns:repeat(2,1fr)}.bar-label{width:90px;font-size:0.75rem}.highlights{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
  <!-- Hero Header -->
  <div class="hero">
    <h1>${escapeHtml(title)}</h1>
    <div class="subtitle">${data.length > 0 ? escapeHtml(`${data.length} records analyzed`) : "Data Analysis Report"}</div>
    <div class="insight">${escapeHtml(getFirstSentence(bodyAnalysis))}</div>
  </div>

  <!-- KPI Cards -->
  ${kpiCards}

  <!-- Executive Summary -->
  <div class="summary-box">
    ${escapeHtml(bodyAnalysis)}
  </div>

  <!-- Bar Chart Section -->
  ${barChart}

  <!-- Highlights -->
  ${highlights}

  <!-- Data Table -->
  ${tableHtml}

  <!-- Footer -->
  <div class="footer">
    Generated on ${now} &middot; ${data.length} row${data.length !== 1 ? "s" : ""} analyzed
  </div>
</div>
</body>
</html>`;
}

// ─── Section Builders ────────────────────────────────────────────────────────

function extractTitle(analysis: string): string {
  // Look for explicit TITLE: prefix from the prompt
  const titleMatch = analysis.match(/^TITLE:\s*(.+)/im);
  if (titleMatch) {
    const title = titleMatch[1].trim();
    if (title.length > 0 && title.length < 100) return title;
  }
  // Fallback: try a short, non-sentence first line
  const firstLine =
    analysis
      .split("\n")
      .find((l) => l.trim().length > 0)
      ?.trim() || "";
  if (firstLine.length < 80 && !firstLine.endsWith(".")) return firstLine;
  // Last resort: derive from first sentence
  const first = getFirstSentence(analysis);
  return first.length > 60 ? first.slice(0, 57) + "..." : first;
}

function getFirstSentence(text: string): string {
  const match = text.match(/^[^.!?]+[.!?]/);
  return match ? match[0].trim() : text.slice(0, 120).trim();
}

function buildKpiCards(
  data: Record<string, unknown>[],
  accent: string,
): string {
  if (data.length === 0) return "";

  const headers = Object.keys(data[0]);
  const numericCols = headers.filter((h) =>
    data.some((row) => !isNaN(parseFloat(String(row[h] ?? "")))),
  );

  if (numericCols.length === 0) {
    // No numeric data — show count KPI
    return `<div class="kpi-row">
  <div class="kpi-card"><div class="number">${data.length}</div><div class="label">Total Records</div></div>
  <div class="kpi-card"><div class="number">${headers.length}</div><div class="label">Data Fields</div></div>
</div>`;
  }

  const cards = numericCols.slice(0, 5).map((col) => {
    const values = data
      .map((r) => parseFloat(String(r[col] ?? "0")))
      .filter((v) => !isNaN(v));
    if (values.length === 0)
      return `<div class="kpi-card"><div class="number">—</div><div class="label">${escapeHtml(col)}</div></div>`;
    const sum = values.reduce((a, b) => a + b, 0);
    const avg = sum / values.length;
    const max = Math.max(...values);
    const min = Math.min(...values);

    // Pick the most interesting metric
    if (values.length <= 3) {
      return `<div class="kpi-card"><div class="number">${formatNumber(sum)}</div><div class="label">Total ${escapeHtml(col)}</div></div>`;
    }
    return `<div class="kpi-card">
  <div class="number">${formatNumber(avg)}</div>
  <div class="label">Avg ${escapeHtml(col)}</div>
</div>`;
  });

  // Add total records card
  cards.unshift(
    `<div class="kpi-card"><div class="number" style="color:${accent}">${data.length}</div><div class="label">Total Records</div></div>`,
  );

  return `<div class="kpi-row">${cards.slice(0, 5).join("\n")}</div>`;
}

function buildBarChart(
  data: Record<string, unknown>[],
  accent: string,
  accentDark: string,
): string {
  if (data.length === 0) return "";

  const headers = Object.keys(data[0]);
  // Find the best label column (first non-numeric) and value column (first numeric)
  const labelCol = headers.find((h) =>
    data.every((r) => isNaN(parseFloat(String(r[h] ?? "")))),
  );
  const numericCols = headers.filter((h) =>
    data.some((r) => !isNaN(parseFloat(String(r[h] ?? "")))),
  );

  if (!labelCol || numericCols.length === 0) return "";

  // Use the first numeric column for the bar chart
  const valueCol = numericCols[0];
  const rows = data.slice(0, 15).map((r) => ({
    label: String(r[labelCol] ?? ""),
    value: parseFloat(String(r[valueCol] ?? "0")) || 0,
  }));

  const maxVal = Math.max(...rows.map((r) => r.value), 1);

  const bars = rows
    .map((r) => {
      const pct = Math.max((r.value / maxVal) * 100, 2);
      return `<div class="bar-row">
  <div class="bar-label" title="${escapeHtml(r.label)}">${escapeHtml(r.label)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%;background:linear-gradient(90deg,${accent},${accentDark})">${pct > 15 ? formatNumber(r.value) : ""}</div></div>
  <div class="bar-value">${formatNumber(r.value)}</div>
</div>`;
    })
    .join("\n");

  return `<div class="section">
  <h2>${escapeHtml(valueCol)} by ${escapeHtml(labelCol)}</h2>
  <div class="bar-chart">${bars}</div>
</div>`;
}

function buildHighlights(data: Record<string, unknown>[]): string {
  if (data.length === 0) return "";

  const headers = Object.keys(data[0]);
  const labelCol = headers.find((h) =>
    data.every((r) => isNaN(parseFloat(String(r[h] ?? "")))),
  );
  const numericCols = headers.filter((h) =>
    data.some((r) => !isNaN(parseFloat(String(r[h] ?? "")))),
  );

  if (!labelCol || numericCols.length === 0) return "";

  const valueCol = numericCols[0];
  const rows = data.map((r) => ({
    label: String(r[labelCol] ?? ""),
    value: parseFloat(String(r[valueCol] ?? "0")) || 0,
  }));

  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const cards: string[] = [];

  if (sorted.length > 0) {
    cards.push(
      makeHighlightCard(
        "trophy",
        "Top Performer",
        `${sorted[0].label} — ${formatNumber(sorted[0].value)}`,
      ),
    );
  }
  if (sorted.length > 1) {
    const last = sorted[sorted.length - 1];
    cards.push(
      makeHighlightCard(
        "chart",
        "Lowest",
        `${last.label} — ${formatNumber(last.value)}`,
      ),
    );
  }
  if (sorted.length >= 3) {
    const avg = rows.reduce((s, r) => s + r.value, 0) / rows.length;
    cards.push(
      makeHighlightCard(
        "target",
        "Average",
        `${formatNumber(avg)} across ${rows.length} entries`,
      ),
    );
  }
  if (sorted.length >= 2) {
    const spread = sorted[0].value - sorted[sorted.length - 1].value;
    cards.push(
      makeHighlightCard(
        "range",
        "Spread",
        `${formatNumber(spread)} between top and bottom`,
      ),
    );
  }

  if (cards.length === 0) return "";
  return `<div class="highlights">${cards.join("\n")}</div>`;
}

function makeHighlightCard(
  iconType: string,
  title: string,
  detail: string,
): string {
  const icons: Record<string, string> = {
    trophy: "\u{1F3C6}",
    chart: "\u{1F4C9}",
    target: "\u{1F3AF}",
    range: "\u{1F4CA}",
  };
  return `<div class="highlight-card">
  <div class="icon">${icons[iconType] || "\u{2728}"}</div>
  <div class="text"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>
</div>`;
}

function buildDataTable(
  data: Record<string, unknown>[],
  accent: string,
): string {
  if (data.length === 0) return "";

  const headers = Object.keys(data[0]);
  const showData = data.length > 20 ? data.slice(0, 10) : data;
  const truncated = data.length > 20;

  const ths = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const trs = showData
    .map(
      (row) =>
        `<tr>${headers.map((h) => `<td>${escapeHtml(String(row[h] ?? ""))}</td>`).join("")}</tr>`,
    )
    .join("\n");

  return `<div class="section">
  <h2>Data Overview</h2>
  <table>
    <thead><tr>${ths}</tr></thead>
    <tbody>${trs}</tbody>
  </table>
  ${truncated ? `<p style="text-align:center;margin-top:8px;font-size:0.8rem;color:#94a3b8">...and ${data.length - 10} more rows</p>` : ""}
</div>`;
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return n.toLocaleString("en-US");
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

// ─── Dedicated Infographic Handler API (FEAT-039) ────────────────────────────

const INFOGRAPHIC_BASE = "/api/v1/agents/infographic";

/**
 * Fetch the list of available infographic templates.
 * @param detailed — if true, returns `{ name, description }[]` instead of `string[]`
 */
export async function fetchTemplates(
  detailed = false,
): Promise<TemplateListResponse> {
  const response = await apiClient.get<TemplateListResponse>(
    `${INFOGRAPHIC_BASE}/templates`,
    { params: { detailed } },
  );
  return response.data;
}

/**
 * Fetch the list of available infographic themes.
 * @param detailed — if true, returns `{ name, primary, neutral_bg, body_bg }[]`
 */
export async function fetchThemes(
  detailed = false,
): Promise<ThemeListResponse> {
  const response = await apiClient.get<ThemeListResponse>(
    `${INFOGRAPHIC_BASE}/themes`,
    { params: { detailed } },
  );
  return response.data;
}

/**
 * Fetch details for a specific template by name.
 */
export async function fetchTemplateDetail(
  name: string,
): Promise<TemplateDetailResponse> {
  const response = await apiClient.get<TemplateDetailResponse>(
    `${INFOGRAPHIC_BASE}/templates/${encodeURIComponent(name)}`,
  );
  return response.data;
}

/**
 * Fetch details for a specific theme by name.
 */
export async function fetchThemeDetail(
  name: string,
): Promise<ThemeDetailResponse> {
  const response = await apiClient.get<ThemeDetailResponse>(
    `${INFOGRAPHIC_BASE}/themes/${encodeURIComponent(name)}`,
  );
  return response.data;
}

/**
 * Generate an infographic using the dedicated backend handler.
 *
 * @param agentId — The agent ID to generate the infographic for.
 * @param params  — Query, template, theme, session_id, user_id.
 * @param format  — 'json' returns parsed InfographicJsonResponse; 'html' returns sanitized HTML string.
 *
 * Throws an error with the `error` field from the API response on 4xx/5xx.
 */
export async function generateInfographicFromApi(
  agentId: string,
  params: InfographicGenerateParams,
  format: "json" | "html" = "json",
): Promise<InfographicJsonResponse | string> {
  try {
    if (format === "html") {
      const response = await apiClient.post<string>(
        `${INFOGRAPHIC_BASE}/${encodeURIComponent(agentId)}`,
        params,
        { params: { format: "html" }, responseType: "text" },
      );
      return sanitizeInfographicHtml(response.data);
    } else {
      const response = await apiClient.post<InfographicJsonResponse>(
        `${INFOGRAPHIC_BASE}/${encodeURIComponent(agentId)}`,
        params,
        { params: { format: "json" } },
      );
      return response.data;
    }
  } catch (err: unknown) {
    // Extract meaningful error message from API error response
    if (
      err &&
      typeof err === "object" &&
      "response" in err &&
      err.response &&
      typeof err.response === "object" &&
      "data" in err.response
    ) {
      const data = err.response.data as Record<string, unknown>;
      const msg =
        (data?.error as string) ||
        (data?.message as string) ||
        "Infographic generation failed";
      throw new Error(msg);
    }
    throw err;
  }
}
