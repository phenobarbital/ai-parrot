# F004 — CodexCodeDispatchProfile constraints that block the requested behaviors (query Q013)

**Type**: read
**Citations**:
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py:540-566` — `CodexCodeDispatchProfile`
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py:805` — `CodexCodeReviewProfile.subagent: Literal["sdd-worker"]`

Facts:
- `subagent: Literal["sdd-worker"]` on BOTH the dispatch profile and the review profile — the Codex path can only load the `sdd-worker` prompt body ("v1 Codex integration is intentionally scoped to Development", models.py:543). Claude's review profile can select `sdd-codereview` (models.py:788); Codex cannot.
- `sandbox` already supports `"read-only"` as a Literal value, but nothing constructs a read-only profile today.
- Dispatcher builds one-shot `codex exec` sessions only — no `codex exec review` subcommand, no `codex exec resume --last` session continuation, no `-i` image attach.
- `_enforce_cwd_under_worktree_base` (dispatcher.py:1264) pins every dispatch cwd under `WORKTREE_BASE_PATH`.

**Implication**: an adversarial-reviewer or opinion-brief mode needs (a) the subagent Literal widened or a dedicated brief body, (b) a read-only profile constructor, and possibly (c) `exec review`/`resume` command variants in `_build_command`.
