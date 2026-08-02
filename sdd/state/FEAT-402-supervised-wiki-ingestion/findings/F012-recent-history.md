# F012 — Recent history: wiki/ is a hot area (last 2-3 weeks)

`git log --since="60 days ago" -- packages/ai-parrot/src/parrot/knowledge/wiki/`
(newest first, abridged):

| Commit | When | Author | Message |
|--------|------|--------|---------|
| 20148525 | 3 days ago | Jesus | wip: Dev loop flow and wiki toolkit |
| 09fe7df6 | 4 days ago | Claude | feat(graphindex): grounding evaluator + lineage |
| a76413d6 | 4 days ago | Claude | feat(graphindex): LLM-typed knowledge extraction |
| e9ea0378 | 4 days ago | Claude | feat(wiki): CLI authoring surface (persistent memory) |
| 1d158c2f | 12 days ago | Javier León | feat: native wiki integrations for codex and gemini |
| 32e17d0e | 12 days ago | Claude | feat(crew): execution wiki |
| 11e33a8a | 2 weeks ago | Jesus Lara | feat(wiki): port llmwiki reader capabilities |
| cd6ac5e6 | 2 weeks ago | Jesus Lara | fix(wiki): merge-safe post-commit upsert |

- Implication: high merge-conflict risk for long-lived branches touching
  `wiki/cli.py`; keep the feature additive (new modules + new command) and
  rebase often. SDD conventions: proposals in `sdd/proposals/`, FEAT/TASK ids
  via `scripts/sdd/reserve_ids.py` (FEAT-387), base branch `dev`.

Method: git log (shallow clone, depth 50) + CLAUDE.md SDD section.
