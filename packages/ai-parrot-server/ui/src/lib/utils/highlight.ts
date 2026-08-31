/**
 * Lazy, minimal highlight.js loader.
 *
 * Importing the full `highlight.js` bundle (~950 KB) statically pulls ~200
 * languages into the eager graph of every component that uses it. Instead we
 * lazy-import `highlight.js/lib/core` on first use and register only the
 * languages we actually render in chat code blocks. The theme CSS is loaded
 * alongside, so callers don't need a static stylesheet import.
 */
import type { HLJSApi } from "highlight.js";

let hljsPromise: Promise<HLJSApi> | null = null;

async function loadHljs(): Promise<HLJSApi> {
  const [{ default: hljs }, ...langs] = await Promise.all([
    import("highlight.js/lib/core"),
    import("highlight.js/lib/languages/sql"),
    import("highlight.js/lib/languages/json"),
    import("highlight.js/lib/languages/python"),
    import("highlight.js/lib/languages/javascript"),
    import("highlight.js/lib/languages/typescript"),
    import("highlight.js/lib/languages/bash"),
    import("highlight.js/lib/languages/yaml"),
    import("highlight.js/lib/languages/xml"),
    import("highlight.js/lib/languages/css"),
    import("highlight.js/lib/languages/markdown"),
    // Theme stylesheet — Vite injects it as a side effect.
    import("highlight.js/styles/github-dark.css"),
  ]);

  const register: Array<[string, any]> = [
    ["sql", langs[0]],
    ["json", langs[1]],
    ["python", langs[2]],
    ["javascript", langs[3]],
    ["typescript", langs[4]],
    ["bash", langs[5]],
    ["yaml", langs[6]],
    ["xml", langs[7]],
    ["css", langs[8]],
    ["markdown", langs[9]],
  ];
  for (const [name, mod] of register) {
    hljs.registerLanguage(name, (mod as any).default);
  }
  return hljs;
}

function getHljs(): Promise<HLJSApi> {
  if (!hljsPromise) hljsPromise = loadHljs();
  return hljsPromise;
}

/** Lazily highlight a single `<code>`/`<pre>` element. Safe to fire-and-forget. */
export async function highlightElement(el: HTMLElement): Promise<void> {
  try {
    const hljs = await getHljs();
    hljs.highlightElement(el);
  } catch (err) {
    console.error("highlight.js failed to load", err);
  }
}
