---
id: FC-019
query_id: Q027
type: read
intent: "Migration skill: export/convert/review/apply/preflight procedure for troc.planograms_configurations."
executed_at: 2026-11-06T16:11:15Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-019 — The migration procedure is a command file, .claude/commands/planogram-migrate.md (the planned skill path does not exist)

## Summary

`.claude/skills/planogram-migrate/SKILL.md` does not exist; the procedure lives in `.claude/commands/planogram-migrate.md` (243 lines, "FEAT-574, FEAT-612"). It drives `python -m parrot_pipelines.planogram.migration_runner <subcommand>` through: target confirmation (`ENV` selects the database), read-only `preflight`, `alter` (schema, writes), `export`, `convert`, review of `unresolved` items with the user, `render` → `<workdir>/apply.sql`, and `apply` (writes, explicit confirmation naming the target database). Two steps write to the database: `alter` and `apply`.

## Citations

- path: `.claude/commands/planogram-migrate.md`
  lines: 7-15
  symbol: `(header)`
  excerpt: |
    # /planogram-migrate — Planogram configuration migration (FEAT-574, FEAT-612)
    against the live `troc.planograms_configurations` table: apply the ALTER
    write the approved rows back and prove readiness with the preflight.
    The mechanical part lives in `parrot_pipelines.planogram.migration_runner`;
- path: `.claude/commands/planogram-migrate.md`
  lines: 28-48
  symbol: `(Ground rules)`
  excerpt: |
    - **Two steps write to the database**: `alter` (Step 2) and `apply` (Step 6).
      environment — `ENV` selects which one). The runner resolves it itself and
    source .venv/bin/activate && python -m parrot_pipelines.planogram.migration_runner <subcommand> ...
- path: `.claude/commands/planogram-migrate.md`
  lines: 56-72
  symbol: `(Step 1 — Parse and gate)`
  excerpt: |
    3. **Show the user the `host:port/database` line and get them to confirm it
       is the intended environment** (prod / staging / dev). To target another
       one, prefix every runner call with `ENV=<env>` — keep the same prefix for
- path: `.claude/commands/planogram-migrate.md`
  lines: 163-180
  symbol: `(render / Step 6 — Apply)`
  excerpt: |
    ... migration_runner render --dir <workdir>
    exits `0` and writes `<workdir>/apply.sql`. Exit `2` lists what is still
    ## Step 6 — Apply (writes — confirm)
    3. **Ask for explicit confirmation**, naming the target database again.

## Notes

- The hand-written apply scripts (FC-002/FC-003) are a second, parallel write path to the same table that bypasses this command's `render`/`apply.sql` artefact; they have their own backup + optimistic lock.
- Only headings and matching lines were read.
