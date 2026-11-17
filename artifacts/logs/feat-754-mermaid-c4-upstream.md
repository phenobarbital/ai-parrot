# FEAT-754 Mermaid C4 upstream parse evidence

## Environment

- Date: 2026-10-27
- Upstream parser: `mermaid@12.2.0` (npm), `mermaid.parse()` under `jsdom`, Node v20.20.2.
- Installed in a throwaway directory outside the repo (`npm install mermaid@12.2.0 jsdom --cache <scratch>`);
  no project dependency was added. An earlier attempt with `npx --offline @mermaid-js/mermaid-cli` failed
  with `ENOTCACHED`; a writable scratch npm cache resolved it.

## Method

`to_mermaid_c4` output for 16 specs was written to `.mmd` files and passed to `mermaid.parse()`.
Specs: the `c4_container_diagram.json` fixture; one per level (context, container, component, dynamic);
all 20 element macros; three-deep nested boundaries; the 7 relationship forms
(`BiRel`, `Rel`, `Rel_Back`, `Rel_U/D/L/R`); `UpdateLayoutConfig`; a label with embedded quotes.

## Result

All 16 sources parse (`diagramType` = `c4`). Negative control: `C4Container` + a malformed macro
fails with `Lexical error on line 2`, so the parser does reject bad input.

Scope note: this is a parse check, not a render. It satisfies the M2 "upstream parse" gate.
