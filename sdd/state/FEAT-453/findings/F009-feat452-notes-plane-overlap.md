---
id: F009
query_id: Q018
type: read
intent: Read FEAT-452 audio-notes-obsidian — it may already own the wiki+Obsidian write path this proposal needs
executed_at: 2026-08-23T09:30:00Z
depth: 0
parent_id: null
---

# F009 — FEAT-452 is building the exact "separate wiki plane + Obsidian mirror over Telegram" substrate, and it is in flight right now

## Summary

`sdd/tasks/index/audio-notes-obsidian.json` (FEAT-452, base_branch `dev`) has
six tasks, **all currently `in-progress`**, and three of them are structurally
the same problem this proposal poses for the gestoría domain:

- TASK-2379 "Build the separate `notes` wiki plane"
- TASK-2382 "Register the notes wiki as a queryable namespace"
- TASK-2378 "Scope the nightly vault ingest to the meetings folder"

plus TASK-2377 (`telegram_chat_scope` in agent command handlers), TASK-2380
(note structuring + a `capture_audio_note` toolkit) and TASK-2381 (`/note`
sticky mode and capture-intent routing).

That is: a domain-scoped wiki plane, registered as a federated namespace,
mirrored to a folder of an Obsidian vault, fed from Telegram, with per-chat
scoping. FEAT-453's "cerebro autónomo con espejo en Obsidian" is the same
pattern with `gestoria`/`hooba` substituted for `notes`/`meetings`.

The repo's `wikitoolkit status` already lists `notes` as a registered namespace
(kind=store, backend=sqlite, 0 pages), so the plumbing is landing.

## Citations

- path: `sdd/tasks/index/audio-notes-obsidian.json`
  lines: 1-40
  symbol: "FEAT-452 task index"
  excerpt: |
    feature: audio-notes-obsidian   feature_id: FEAT-452   base_branch: dev
    TASK-2377 in-progress  Enter telegram_chat_scope in agent command handlers
    TASK-2378 in-progress  Scope the nightly vault ingest to the meetings folder
    TASK-2379 in-progress  Build the separate `notes` wiki plane
    TASK-2380 in-progress  Note structuring + `capture_audio_note` toolkit
    TASK-2381 in-progress  `/note` sticky mode and capture-intent routing
    TASK-2382 in-progress  Register the notes wiki as a queryable namespace

- path: `sdd/specs/audio-notes-obsidian.spec.md`
  lines: 1-1
  symbol: "FEAT-452 spec"

- path: `sdd/specs/llmwiki-obsidian-plugin.spec.md`
  lines: 1-1
  symbol: "LLM Wiki Obsidian Plugin — Vault Ingestion into AI-Parrot"

## Notes

Sequencing consequence: FEAT-453 should consume FEAT-452's namespace/mirror
mechanism rather than invent a parallel one. Starting FEAT-453's wiki layer
before FEAT-452 lands risks two incompatible "domain plane + vault mirror"
designs in the same repo. This is the strongest argument for splitting FEAT-453
into phases with the browser layer first.
