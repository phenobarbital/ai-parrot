import { marked, Renderer, type Tokens } from "marked";
import { browser } from "$app/environment";
import DOMPurify from "dompurify";

function sanitize(html: string, config?: Record<string, unknown>): string {
  if (!browser) return html;
  return config
    ? (DOMPurify.sanitize(html, config) as string)
    : (DOMPurify.sanitize(html) as string);
}

// Configure marked for proper markdown handling
marked.setOptions({
  breaks: true, // Convert single newlines to <br>
  gfm: true, // GitHub Flavored Markdown
});

export type MarkdownToHtmlOptions = {
  allowHtml?: boolean;
  allowSvg?: boolean;
  allowImages?: boolean;
};

const SVG_TAGS = [
  "svg",
  "g",
  "path",
  "rect",
  "circle",
  "ellipse",
  "line",
  "polyline",
  "polygon",
  "defs",
  "linearGradient",
  "radialGradient",
  "stop",
  "text",
  "tspan",
  "style",
  "clipPath",
  "mask",
  "pattern",
  "image",
  "use",
];

const SVG_ATTRS = [
  "viewBox",
  "xmlns",
  "xmlns:xlink",
  "x",
  "y",
  "width",
  "height",
  "d",
  "fill",
  "stroke",
  "stroke-width",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-dasharray",
  "stroke-opacity",
  "fill-opacity",
  "transform",
  "class",
  "style",
  "font-family",
  "font-size",
  "text-anchor",
  "points",
  "rx",
  "ry",
  "cx",
  "cy",
  "x1",
  "x2",
  "y1",
  "y2",
  "preserveAspectRatio",
  "opacity",
  "offset",
  "stop-color",
  "stop-opacity",
  "id",
];

const IMAGE_ATTRS = [
  "src",
  "srcset",
  "alt",
  "title",
  "loading",
  "decoding",
  "referrerpolicy",
  "width",
  "height",
  "href",
  "xlink:href",
];

const SVG_LANGS = new Set(["svg", "image/svg+xml"]);
const HTML_LANGS = new Set(["html", "markup", "xml"]);

function buildSanitizeConfig(options: MarkdownToHtmlOptions | undefined) {
  if (!options?.allowHtml && !options?.allowSvg && !options?.allowImages) {
    return undefined;
  }

  const allowSvg = options?.allowSvg ?? options?.allowHtml ?? false;
  const allowImages = options?.allowImages ?? options?.allowHtml ?? false;

  const config: Record<string, unknown> = {
    USE_PROFILES: {
      html: true,
      svg: allowSvg,
      svgFilters: allowSvg,
    },
  };

  const addTags: string[] = [];
  const addAttrs: string[] = [];

  if (allowSvg) {
    addTags.push(...SVG_TAGS);
    addAttrs.push(...SVG_ATTRS);
  }

  if (allowImages) {
    addTags.push("img", "image");
    addAttrs.push(...IMAGE_ATTRS);
    config.ALLOWED_URI_REGEXP = /^(?:(?:https?|data:image\/):|\/)/i;
  }

  if (addTags.length) {
    config.ADD_TAGS = Array.from(new Set(addTags));
  }

  if (addAttrs.length) {
    config.ADD_ATTR = Array.from(new Set(addAttrs));
  }

  return config;
}

function buildRenderer(options: MarkdownToHtmlOptions | undefined): Renderer {
  const renderer = new Renderer();
  const baseRenderer = new Renderer();
  const allowHtml = options?.allowHtml ?? false;
  const allowSvg = options?.allowSvg ?? options?.allowHtml ?? false;

  renderer.code = ({ text, lang, escaped }: Tokens.Code): string => {
    const normalizedLang = (lang ?? "").trim().toLowerCase();
    const trimmed = text.trim();

    if (allowSvg) {
      const looksLikeSvg =
        trimmed.startsWith("<svg") && trimmed.endsWith("</svg>");
      if (SVG_LANGS.has(normalizedLang) || looksLikeSvg) {
        return trimmed;
      }
    }

    if (allowHtml && HTML_LANGS.has(normalizedLang)) {
      return trimmed;
    }

    return baseRenderer.code({ type: "code", raw: text, text, lang, escaped });
  };

  return renderer;
}

/**
 * Normalizes markdown table formatting so that marked.js can always parse
 * tables correctly, regardless of how the AI backend serializes newlines.
 *
 * Handles three common failure modes:
 *  1. Too many newlines — "\n\n" between rows splits the table into paragraphs.
 *  2. Missing blank line  — table directly after a text line, no separator \n\n.
 *  3. Flattened rows      — header/separator/data merged on one "line" with spaces.
 *
 * Fenced code blocks (``` or ~~~) are extracted before normalization and
 * restored afterwards so their content is never mutated.
 */
export function normalizeMarkdownTable(content: string): string {
  // Step 0: protect fenced code blocks — extract them and replace with placeholders.
  // Use a backreference so a 5-backtick opening is only closed by 5+ backticks,
  // preventing a shorter fence inside the block from prematurely ending the match.
  const codeBlocks: string[] = [];
  let result = content.replace(
    /(`{3,})[^\n]*\n[\s\S]*?\1|(~{3,})[^\n]*\n[\s\S]*?\2/g,
    (match) => {
      const idx = codeBlocks.push(match) - 1;
      return `\x02CODEBLOCK_${idx}\x02`;
    },
  );

  // --- Fix 1: collapse \n\n between table rows (too many newlines) ---
  // Repeatedly collapse until stable (handles triple-newline edge cases too).
  let prev: string;
  do {
    prev = result;
    result = result.replace(/(\|[^\n]*)\n\n(?=[ \t]*\|)/g, "$1\n");
  } while (result !== prev);

  // --- Fix 1b: join broken table rows ---
  // Some LLM responses split a single table row across multiple lines, e.g.:
  //   | Cell A\n| Cell B | Cell C |
  // Join a line that starts with | but does NOT end with | onto the next line.
  // Repeat until stable since multiple fragments may need merging.
  do {
    prev = result;
    result = result.replace(
      /(^[ \t]*\|[^\n]*[^|\s])[ \t]*\n(?=[ \t]*\|)/gm,
      "$1 ",
    );
  } while (result !== prev);

  // --- Fix 2: ensure blank line before a table that follows regular text ---
  result = result.replace(/([^|\n])(\n)(\|.*\|)/g, "$1\n\n$3");

  // --- Fix 3: inline text immediately before table cells (same line) ---
  result = result.replace(/(^[^|].*?)\s+(\|.+?\|.+?\|)/gm, "$1\n\n$2");

  // --- Fix 4: split flattened header from separator row ---
  // A real GFM separator cell is: optional spaces + optional colon + 3+ dashes + optional colon + optional spaces.
  // Using a strict pattern avoids false positives on data cells that contain dashes.
  const sepCell = "[ \\t]*:?-{3,}:?[ \\t]*";
  const sepRow = new RegExp(`(\\|)\\s*((?:\\|${sepCell})+\\|)`, "g");
  result = result.replace(sepRow, "$1\n$2");

  // --- Fix 5: split separator row from the first data row ---
  // Use a negative lookahead so we don't mis-fire on consecutive separator rows,
  // and so cells that start with '-' (negative numbers) or ':' (timestamps) are
  // correctly treated as data cells rather than being skipped.
  const afterSep = new RegExp(
    `((?:\\|${sepCell})+\\|)\\s*(\\|(?!\\s*(?:${sepCell})+\\|))`,
    "g",
  );
  result = result.replace(afterSep, "$1\n$2");

  // Step 0 (restore): put fenced code blocks back
  result = result.replace(
    /\x02CODEBLOCK_(\d+)\x02/g,
    (_, i) => codeBlocks[Number(i)],
  );

  return result;
}

export function markdownToHtml(
  markdown: string | null | undefined,
  options: MarkdownToHtmlOptions = {},
): string {
  if (!markdown) return "";
  try {
    const normalized = normalizeMarkdownTable(markdown);
    const renderer = buildRenderer(options);
    // Wrap every <table> in a scrollable container. Post-processing avoids the
    // display:block anti-pattern and keeps the native table formatting context.
    const rawHtml = (marked.parse(normalized, { renderer }) as string)
      .replace(/<table>/g, '<div class="chat-table-wrapper"><table>')
      .replace(/<\/table>/g, "</table></div>");
    const sanitizeConfig = buildSanitizeConfig(options);
    return sanitizeConfig
      ? sanitize(rawHtml, sanitizeConfig)
      : sanitize(rawHtml);
  } catch (e) {
    console.error("Failed to parse markdown", e);
    return markdown || "";
  }
}
