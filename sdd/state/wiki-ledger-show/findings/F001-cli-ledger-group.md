# F001 — `wikitoolkit ledger` command group (type: grep+read, wiki: sym:...cli.py#ledger_unclaim)
Citations: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3221-3574
- Group `ledger` at cli.py:3221; subcommands: open(3226) ready(3277) claim(3298) acknowledge(3323) close(3339)
  plan-fix(3364) unclaim(3410) context(3428) blockers(3452) export(3469) sync(3489) rebuild(3505) ingest-sdd(3536)
  compact(3558) audit(3572). No `list`, no `show`. Confirmed with `wikitoolkit ledger --help`.
- `ledger ready` (3277-3295) prints `id [severity] title (kind)` only — no body, only status=open (claimed/closed invisible).
- Proxied commands use `@remote_cli.remote_aware(proxied=True, tool="ledger_x")` + `remote_cli.call_remote_text(...)` branch;
  WikiStoreBusy is caught and reported as index_pending.
