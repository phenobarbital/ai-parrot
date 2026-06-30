# F008 — AbstractTool output scrubber seam (EXISTS)

**Query**: Q006 (grep `class AbstractTool|scrub`)
**Verdict**: VERIFIED EXISTS — brainstorm §6 invariant #3/#1 partially backed.

- `packages/ai-parrot/src/parrot/tools/abstract.py:98` `class AbstractTool`.
- `_get_output_scrubber` (l.26), `_default_scrubber` (l.34) → `OutputScrubber`/`ScrubPolicy`.
- Scrubbing applied once at the tool-output boundary (l.625): "the ONLY place scrubbing happens on the way out; all downstream callers receive a pre-scrubbed ToolResult" — `update={"result": _scrubber.scrub(...)}`, `error` scrubbed too (l.637).

**Implication**: The "no secrets in the conversational plane" invariant has a real enforcement seam (the output scrubber). CredentialResolver returning *resolved clients* (F001) + scrubber = the two seams brainstorm §6 relies on both exist.
