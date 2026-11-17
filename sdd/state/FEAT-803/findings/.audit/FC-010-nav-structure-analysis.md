# FC-010: Navigation structure analysis

## Query
Analysis of mkdocs.yml nav (lines 114-341)

## Result
Current nav has 14 top-level sections:
1. **Home** — landing page (index.md)
2. **Getting Started** — Install, Config, Tools Quick (3 pages)
3. **Foundations** — architecture series (11 pages)
4. **LLM Clients** — provider docs (8 pages)
5. **Bots & Agents** — agent types (17 pages)
6. **Memory & Knowledge** — memory/storage (13 pages)
7. **Knowledge Graph** — wiki/graphindex (8 pages including LLM Wiki sub-nav)
8. **Tools, Loaders & RAG** — tools catalog (18 pages including Infographics sub-nav)
9. **Integrations & Transport** — platforms/voice (28 pages with Events/Frontend sub-navs)
10. **Prompts** — PromptBuilder (5 pages)
11. **Orchestration & Flows** — AgentCrew/AgentsFlow (7 pages)
12. **Advanced** — APIs, deployment, security, migration (30 pages with 4 sub-navs)
13. **API Reference** — mkdocstrings-generated (11 pages, removed by M9)
14. **Reference** — CLASSES.md, FUNCTIONS.md (2 pages)
15. **Development** — SDD, style guide, design notes (15+ pages)

Total: ~175 nav entries. Very developer-heavy — no newcomer onboarding flow.

## Citations
- mkdocs.yml:114-341 — full nav tree

## Notes
For an informative site, this nav collapses dramatically. Keep: Home (redesigned), Getting Started (expanded), Concepts (distilled from Foundations/Clients/Bots), Guides (new), Integrations (summary), and a "Technical Reference → Wiki" link. Everything else moves to wiki or is already moved by FEAT-801 M7. The Development section stays but moves to a less prominent position.
