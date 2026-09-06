---
kind: inline
jira_key: null
fetched_at: 2026-09-06T03:00:00+00:00
summary_oneline: Auto-detect Claude Code/Codex CLI and default wikitoolkit/bookstore LLM to it with a visible warning
---

en repositorios recien creados enfrento que el LLM by default para wikitoolkit es Gemini:
`[WARNING] 2026-09-06 02:57:16,306 parrot.knowledge.pageindex.builder(builder.py:171) :: TOC
detector failed on page 0: No LLM configured for the bookstore`, sin embargo hace ya algun
tiempo que tenemos Claude Agent SDK y un cliente LLM de ai-parrot usando las credenciales de
Claude Code, además, "wikitoolkit build" es basicamente un cli command por lo que es más común
que lo ejecutemos en una consola con Claude Code o OpenAI Codex que con Gemini Google, por lo
que propondría un cambio: en la primera ejecución detectar con un safe-execution si contamos
con acceso a Claude Code y entonces definir que ese sea el LLM by default (si hay que definir
un modelo LLM, sería haiku, ya que wikitoolkit summary es algo determinista).

Follow-up clarification from the requester (same session, in response to a philosophy
trade-off question): the intent is zero-friction usability, not strict backward
compatibility with the current "no LLM configured = fully supported silent degraded mode"
stance. If the user already has a working coding-agent CLI session (Claude Code and/or
Codex), the tool should default to using it instead of asking for a separate provider API
key. The auto-selection must not be silent: it must emit a clear, visible warning stating
which provider/model was auto-selected and how to override it, then let the user switch
providers if they want to.

**Initial signals** (extracted, not interpreted):
- Verbs: "propondría un cambio" → feature proposal, not a bug report.
- Named entities: `wikitoolkit`, `bookstore`, "Claude Agent SDK", "Claude Code", "OpenAI Codex", "Gemini", "haiku".
- Explicit ask: auto-detect coding-agent CLI availability; default `WIKI_MODEL` /
  `WIKI_LIGHTWEIGHT_MODEL` / `WIKI_EXTRACT_LLM` / `PARROT_BOOKSTORE_LLM` to it when unset;
  use a cheap/deterministic model (Haiku) for Claude Code; warn visibly; allow override.
