---
kind: file
jira_key: null
file_path: sdd/proposals/brainstorm-copilot-a2a-percredential.md
fetched_at: 2026-06-26T00:36:52Z
summary_oneline: Publish AI-Parrot as an A2A connected agent in M365 Copilot with parrot-owned per-user tool credential acquisition
---

# Source: Continuation of Copilot ⇄ A2A integration work

The user is continuing in-progress work integrating one AI-Parrot Agent into
Microsoft 365 Copilot via the Agent-to-Agent (A2A) protocol. The base artifact
is the brainstorm at `sdd/proposals/brainstorm-copilot-a2a-percredential.md`.

Key established facts from the brainstorm (full text preserved at
`source-original.md`):

- **Goal**: Make an AI-Parrot agent (bundling `work-iq`, `fireflies.ai`, `jira`
  tools) invokable from inside the M365 Copilot surface via Copilot Studio's
  A2A connection.
- **Closed decision**: Model B — credential custody stays in parrot (vault),
  not in Copilot's Power Platform connection store. Acquisition UX is link-out
  (OOB) to parrot's authenticated web surface.
- **Spike status (2026-06-26)**: Copilot connects + invokes parrot as an A2A
  sub-agent (POSTs `message/send` to host origin `/`, not the card `url`).
  AgentCard discovery still failing — name/description do NOT autopopulate.
- **Diagnosed root cause (§11)**: v0.3 vs v1.0 AgentCard schema fork + camelCase
  MUST + missing `supportedInterfaces`. Decision: dual-emit + camelCase. Fix
  lands in `parrot.a2a` model / `to_dict`, NOT `server.py`.
- **Hard part**: per-user tool authentication. `work-iq` (Entra OBO),
  `jira` (Atlassian 3LO), `fireflies` (static API key). A2A carries no user
  identity in the payload.
- **Spike gate (OQ#1)**: does Copilot's low-code A2A connection deliver a
  stable, verifiable per-user identity to parrot? The vault-keying premise
  depends on this.

The brainstorm carries two anchor classes: §11 anchors marked **VERIFIED**
against `examples/a2a/server.py`, and §7 anchors marked **⚠️ VERIFY** (the
credential/HITL/audit primitives). This proposal's job is to ground every one
of those anchors in the real codebase before any further spec work.
kind: inline
jira_key: null
fetched_at: 2026-06-26T00:00:00Z
summary_oneline: LLM Wiki with PageIndex + GraphIndex for persistent, compounding knowledge bases
---

# Source: LLM Wiki with PageIndex + GraphIndex

This is an implementation of LLM wiki with several features, take as example to create a LLM Wiki implementation using ai-parrot, covering PageIndex + GraphIndex document construction, LLM-wiki with search topics, etc following the patterns described by Karpathy: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

The idea is creating a Knowledge base as a persistent wiki, usable for an Agent using the 3-layer architecture described by Karpathy:

1. **Raw sources** — your curated collection of source documents. Articles, papers, images, data files. These are immutable — the LLM reads from them but never modifies them. This is your source of truth.

2. **The wiki** — a directory of LLM-generated markdown files. Summaries, entity pages, concept pages, comparisons, an overview, a synthesis. The LLM owns this layer entirely. It creates pages, updates them when new sources arrive, maintains cross-references, and keeps everything consistent. You read it; the LLM writes it.

3. **The schema** — a document (e.g. CLAUDE.md for Claude Code or AGENTS.md for Codex) that tells the LLM how the wiki is structured, what the conventions are, and what workflows to follow when ingesting sources, answering questions, or maintaining the wiki. This is the key configuration file — it's what makes the LLM a disciplined wiki maintainer rather than a generic chatbot. You and the LLM co-evolve this over time as you figure out what works for your domain.

But combining wiki-style schemas, PageIndex and GraphIndex, combined search and the ability for LLMs to save answers and documents on each (llmwiki, pageindex or graphindex), add tooling for bookkeeping.

## Reference: Karpathy LLM Wiki Concept

### Core Idea
Instead of just retrieving from raw documents at query time (RAG), the LLM **incrementally builds and maintains a persistent wiki** — a structured, interlinked collection of markdown files. The wiki is a persistent, compounding artifact. Cross-references are already there. Contradictions have already been flagged. The synthesis already reflects everything.

### Operations
- **Ingest**: Drop a new source → LLM reads it, writes summary, updates index, updates entity/concept pages, appends to log. A single source might touch 10-15 wiki pages.
- **Query**: Ask questions → LLM searches relevant pages, synthesizes answer. Good answers can be filed back into the wiki as new pages.
- **Lint**: Health-check the wiki. Look for contradictions, stale claims, orphan pages, missing cross-references, data gaps.

### Indexing and Logging
- **index.md**: Content-oriented catalog of everything in the wiki with links, one-line summaries, organized by category.
- **log.md**: Chronological append-only record of operations.

### Tooling
- Search engine over wiki pages (BM25 + vector + LLM re-ranking)
- File management tools for the LLM to read/write wiki pages
