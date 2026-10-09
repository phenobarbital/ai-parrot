# TASK-4190: Knowledge-upload documentation

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4187, TASK-4188, TASK-4189
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 11** and AC18. The operator-facing guide for the
feature: how to enable `knowledge_upload` on a bot, the commands per platform
(final syntax as implemented by TASK-4187 Telegram, TASK-4188 Teams,
TASK-4189 Slack), authorization and login requirements, the wiki charter
prerequisite, Slack app scopes and the navigator-agent-server deployment
example (spec §7 "Deployment").

Location decision: `docs/integrations/` already exists and holds the
per-integration guides (`slack-devloop.md`, `google-oauth2.md`,
`office365-oauth2.md`, `msagentsdk-semantic-cards.md`), so the guide goes to
`docs/integrations/knowledge-upload.md` as the spec states.

---

## Scope

- Write `docs/integrations/knowledge-upload.md` covering:
  1. What it does (one paragraph) and the "original is deleted" guarantee.
  2. The `knowledge_upload` YAML block with every `KnowledgeUploadConfig`
     field and default (`enabled`, `allowed_usernames`, `allowed_groups`,
     `max_size_mb` = 10, `allowed_extensions`, `max_concurrent_jobs` = 2,
     `slack_pending_window_s` = 300, `bookstore.library_dir`/`llm`,
     `wiki.wiki_root`/`charter_path`/`llm`, default LLM
     `google:gemini-3.1-flash-lite`).
  3. Authorization: username OR group, one global list per bot, deny by
     default; identity sources per platform (Telegram navigator-auth login,
     Teams/Slack email → `auth.vw_users`).
  4. Commands per platform with flags (`--force`, `--title`, `--author`,
     `--topic`), copied from the merged adapters — not from this task file.
  5. Outcomes table (accepted / added / updated / skipped / rejected by triage
     / denied / invalid / failed) and duplicate semantics (same content
     skipped unless `--force`; same file name replaces; `--force` never
     bypasses triage).
  6. Wiki prerequisites: charter at `<wiki_root>/.parrot/charter.yaml`
     (user-authored); without it `ingest_wiki` is not offered; only
     triage `admit` is ingested.
  7. Platform notes: Telegram 20 MB Bot API cap and required
     `enable_login: true` + `force_authentication: true`; Teams proactive
     message needs `client_id`; Slack scopes `files:read`, `users:read`,
     `users:read.email`, the `/ingest_book` and `/ingest_wiki` slash commands
     in the app manifest, and the bare-word `ingest_book` message form.
  8. navigator-agent-server deployment example (spec §7 YAML).
  9. Known limitations (spec §7 Known Risks: same-name replacement, stale
     `source_path`, restart loses running jobs).

**NOT in scope**: any code change, README/index edits elsewhere, editing
navigator-agent-server, writing a charter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/integrations/knowledge-upload.md` | CREATE | Operator guide for FEAT-647 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# None — documentation task. The guide must name only symbols that exist after the dependencies merge:
from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig  # created by TASK-4182 (spec §2 Data Models)
```

### Existing Signatures to Use
```python
# Config field names/defaults to document — spec §2 Data Models (implemented by TASK-4182):
class KnowledgeUploadConfig(BaseModel):
    enabled: bool = False
    allowed_usernames: list[str] = []
    allowed_groups: list[str] = []
    max_size_mb: int = 10
    allowed_extensions: list[str] = [".pdf", ".docx", ".md", ".markdown"]
    max_concurrent_jobs: int = 2
    slack_pending_window_s: int = 300
    bookstore: BookstoreTargetConfig | None = None   # library_dir: str, llm: str = "google:gemini-3.1-flash-lite"
    wiki: WikiTargetConfig | None = None             # wiki_root: str, charter_path: str | None, llm: str = "google:gemini-3.1-flash-lite"

# Wiki charter default path — packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4564
def _resolve_charter_path(root: Path, charter_opt: str | None) -> Path:  # default <root>/.parrot/charter.yaml

# Telegram login flags — packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
enable_login: bool = True            # :83
force_authentication: bool = False   # :85

# Existing docs style reference — docs/integrations/slack-devloop.md (H1 title + FEAT id, short intro, sections)
```

### Does NOT Exist
- ~~`docs/integrations/knowledge-upload.md`~~ — created here
- ~~a `wikitoolkit bookstore` command~~ — the Bookstore CLI is `bookstore` / `parrot bookstore`
- ~~an HTTP upload endpoint or agent-side upload tool~~ — explicitly out of scope (spec §1 Non-Goals); do not document one
- ~~a DB audit table~~ — audit is log-only (logger `parrot.integrations.knowledge_upload.audit`)
- ~~chat confirmation for triage gray-zone documents~~ — they are rejected with the briefing

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/integrations/knowledge-upload.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_charter_path"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `docs/integrations/slack-devloop.md`: H1 with the feature id, a short
intro paragraph, then task-oriented sections with fenced YAML / command
examples.

### Key Constraints
- Every command, flag and default must be copied from the merged code of
  TASK-4182 / TASK-4187 / TASK-4188 / TASK-4189 (grep them), not from the
  spec, if they differ — record any difference in the Completion Note.
- Never put real usernames, groups, tokens or hostnames in examples — use
  placeholders like `jdoe`, `knowledge_curators`.
- Validate that the YAML example parses: load it in a Python REPL inside the
  worktree with `KnowledgeUploadConfig.model_validate(yaml.safe_load(...)["knowledge_upload"])`
  (do not add a test file — test files belong to other tasks).

### References in Codebase
- `docs/integrations/slack-devloop.md` — style
- `sdd/specs/teams-telegram-uploader-bookstore.spec.md` §2, §7 — behavior and deployment

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged adapters (`telegram/knowledge_upload.py`, `msteams/commands/knowledge_upload.py`, `slack/knowledge_upload.py`) and `knowledge_upload/models.py` — *why*: the guide must match shipped syntax and defaults (AC18).
2. Write the document from the skeleton below — *why*: fixed section order keeps it reviewable.
3. Parse the YAML example with `KnowledgeUploadConfig.model_validate` in a REPL — *why*: a broken example is the most common docs defect.
4. Run the Validation Commands — *why*: confirms the documented config and adapters still pass their tests.

### `docs/integrations/knowledge-upload.md` (CREATE)
```markdown
# Knowledge upload from chat (FEAT-647)

Authorized users can attach a PDF, DOCX or Markdown file to a command in
Telegram, MS Teams or Slack and have it ingested into a Bookstore library or
an LLM wiki. The uploaded file is never kept: it is staged only for the
duration of the ingest and deleted afterwards; only the derived knowledge
persists.

## Enabling it on a bot
<!-- FILL IN: YAML block with every KnowledgeUploadConfig field + defaults table — AC18 -->

## Who may upload
<!-- FILL IN: username OR group, global per bot, deny by default; identity per platform -->

## Commands
### Telegram
### Microsoft Teams
### Slack
<!-- FILL IN: exact syntax/flags from the merged adapters; Slack bare-word form + pending window -->

## What happens after you upload
<!-- FILL IN: outcomes table, duplicates, triage (admit only), notifications -->

## Wiki prerequisite: the editorial charter
## Platform setup notes
<!-- FILL IN: Telegram login flags + 20 MB cap; Teams client_id; Slack scopes + slash commands -->

## Deployment example (navigator-agent-server)
## Limitations
```
**Why this shape**: section order follows the operator's journey (enable →
authorize → use → outcomes → prerequisites → limits); the intro states the
non-persistence guarantee first because it is the feature's key promise.

### FILL IN checklist
- [ ] Config section — all fields and defaults; YAML parses; AC18
- [ ] Authorization section — OR rule, deny-by-default, identity per platform; AC3, AC4
- [ ] Commands — copied from merged code; AC1
- [ ] Outcomes/duplicates/triage; AC6, AC7, AC11
- [ ] Charter prerequisite; AC9
- [ ] Platform notes incl. Slack scopes and Telegram login; AC4, AC10
- [ ] Deployment example + limitations

---

## Acceptance Criteria

- [ ] AC18 — `docs/integrations/knowledge-upload.md` documents config (all fields + defaults), commands per platform, Slack scopes, the Telegram login requirement and the charter prerequisite.
- [ ] Command syntax and defaults match the merged code of TASK-4182/4187/4188/4189.
- [ ] The YAML example parses with `KnowledgeUploadConfig.model_validate`.
- [ ] No real usernames, groups, tokens or hostnames in the document.

---

## Validation Commands

> Docs-only task: these run the existing tests of the features being documented, read-only.

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_config_fields.py -q`
- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py -q`

---

## Test Specification

No new tests (documentation only). Validation = the existing config-field and
adapter tests above, plus the manual `model_validate` parse of the YAML
example (step 3).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4187, TASK-4188 and TASK-4189 must be `"done"` in
   `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY content:
   - Confirm the config fields and command syntax in the merged code
   - If anything has changed, document what the code does and note it in the Completion Note
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint skeleton and complete every `FILL IN`
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the doc** — stage only `docs/integrations/knowledge-upload.md` (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4190 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
