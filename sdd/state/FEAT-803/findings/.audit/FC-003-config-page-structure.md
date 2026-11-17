# FC-003: Configuration page structure

## Query
Read `docs/config.md` first 40 lines

## Result
`config.md` is a flat reference of env vars organized by service, each with a bullet list of variable names and descriptions. Sections: LLM API Keys (Google/OpenAI/Anthropic/Groq/xAI/zAI), Database, Cache & Redis, Vector Databases, Microsoft, Cloud Services, LLM Defaults, Embeddings, Directory Paths, HTTP Client, Additional Tools.

Stays on Pages per FEAT-801 classification rule (it's in the "Getting Started" nav, not technical reference).

## Citations
- docs/config.md:1-40 — ToC and first section

## Notes
This page is a good candidate to remain on the informative site but needs a rewrite: currently it's a flat dump of ~50+ env vars. An informative site would show a "minimal config to get started" block prominently and collapse advanced vars into expandable sections or move them to the wiki.
