---
id: PROVISIONAL
title: JiraToolkit upgrades — MCP parity, CLI 3LO auth, YAML knowledge base
type: feature
mode: enrichment
status: review
base_branch: dev
confidence: medium
research_state: sdd/state/jiratoolkit-upgrades/
projects: [ai-parrot-tools, ai-parrot]
tags: [jira, oauth2-3lo, cli, knowledge-base, toolkit]
---

# JiraToolkit upgrades

## 0. Origin
Inline request (2026-10-16). It has three parts:
1. Compare JiraToolkit against the Atlassian MCP method list and add the methods it lacks.
2. Add `parrot jiratoolkit auth`, which runs an OAuth2 3LO flow and stores the credentials.
3. Add a YAML knowledge base describing the Jira site's structure (cloud_id, projects, issue types, priorities,
   status_map, fields, limits, templates, components). The toolkit reads it instead of querying Jira for that
   structure each time.

## 1. Synthesis Summary
JiraToolkit (`parrot_tools/jiratoolkit.py`) already covers 8 of the 12 MCP operations. Four are missing: issue
linking, field metadata for creating an issue, comment editing, and cloud-id resolution as a tool [F001].
3LO support exists, but `JiraOAuthManager` is built around the server: it needs Redis and an aiohttp callback,
and stores tokens per chat (channel, user) [F002]. A CLI flow therefore needs a local loopback callback and its
own file-based token store, connected to the toolkit through the existing `credential_resolver` hook. The toolkit
has no knowledge base today: issue types and components are fetched live on every call [F004].

## 2. Codebase Findings
### 2.1 Gap matrix [F001]
| MCP op | JiraToolkit | Status |
|---|---|---|
| getAccessibleAtlassianResources | only `JiraOAuthManager` (ACCESSIBLE_RESOURCES_URL) | **missing as tool** |
| getJiraIssue | `jira_get_issue` | ✓ |
| createJiraIssue | `jira_create_issue` | ✓ |
| editJiraIssue | `jira_update_issue` / `jira_update_ticket` | ✓ |
| searchJiraIssuesUsingJql | `jira_search_issues` | ✓ |
| lookupJiraAccountId | `jira_search_users` | ✓ |
| getJiraProjectIssueTypesMetadata | `jira_get_issue_types(project)` | ✓ |
| getJiraIssueTypeMetaWithFields | — (types only, no fields) | **missing** |
| getTransitionsForJiraIssue | `jira_get_transitions`, `jira_list_transitions` | ✓ |
| addCommentToJiraIssue / addOrEdit… | `jira_add_comment` (add only) | **edit missing** |
| createIssueLink | — | **missing** |
| getVisibleJiraProjects | `jira_get_projects` | ✓ |

### 2.2 Localization
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`: new tools; `credential_resolver` / `_pre_execute`
  (L982, L1243) [F001, F002]
- `packages/ai-parrot-tools/src/parrot_tools/jira_config.py`: `auth_type` Literal lacks `oauth2_3lo` [F002]
- `packages/ai-parrot/src/parrot/auth/jira_oauth.py`: reuse the URL and constants; the Redis store is not
  reusable for the CLI [F002]
- `packages/ai-parrot/src/parrot/cli/__init__.py` `_lazy_commands`: register `"jiratoolkit"` [F003]

### 2.3 Constraints
- The toolkit file is large and touched by FEAT-637/639. Re-check line numbers before editing.
- aiohttp only. Secrets go only in git-ignored files or env vars.

## 3. Scope
**M1 — Parity tools:** add `jira_create_issue_link` (with `jira_get_link_types`),
`jira_get_create_fields(project, issue_type)` (createmeta), `jira_edit_comment(issue, comment_id, body)` (FEAT-637
template support optional), and `jira_get_accessible_resources` (3LO mode only).

**M2 — `parrot jiratoolkit auth`:** a click group in ai-parrot-tools, registered lazily like `manuals`. The flow:
1. Open a loopback server at `http://127.0.0.1:<port>/callback` and open the browser to the Atlassian authorize URL.
2. Exchange the code for tokens and resolve `cloud_id` via accessible-resources. If several sites are returned,
   the user picks one.
3. Persist the result in two places (**decided: both**):
   - `JIRA_OAUTH_CLIENT_ID` and `JIRA_OAUTH_CLIENT_SECRET` go in `.env`.
   - The rotating access/refresh tokens, `cloud_id` and `site` go in `settings.local.json`, git-ignored, mode 0600.
4. Add a `FileTokenCredentialResolver` that refreshes the tokens and writes them back atomically. It plugs into
   `credential_resolver`.

Related subcommands: `status`, `logout`, `sync-kb`.

**M3 — YAML knowledge base:** a Pydantic `JiraKnowledgeBase` model following the user's schema. It is loaded from
`knowledge_base=` / `JIRA_KB_PATH`. The toolkit uses it to:
- resolve issue-type names and ids, priorities and custom-field aliases (`team` → `customfield_10001`);
- map template names to their allowed types;
- enforce summary/description limits;
- map statuses into the wiki enum.

When the KB lacks an entry, the toolkit falls back to the live API and logs a stale-KB warning (**decided**).
`sync-kb` generates the structural sections from the API and keeps the hand-written ones (status_map, templates,
limits) (**decided**).

## 4. Confidence Map
- ✓ [high] The four ops above are missing, and the other eight are covered (method grep).
- ✓ [high] `JiraOAuthManager` requires Redis, so the CLI cannot reuse it unchanged (L98-125).
- ◐ [medium] Plugging the file resolver into `credential_resolver` is enough for oauth2_3lo mode. The resolver's
  call contract was not read in full.
- ◌ [low] A loopback redirect URI needs the Atlassian app to register `http://127.0.0.1:<port>/callback`.

## 5. Open Questions
- [x] Token store → both: client creds in `.env`, rotating tokens in `settings.local.json`.
- [x] KB source → generated by the CLI and edited by hand; hand-written sections are kept on re-sync.
- [x] KB miss → fall back to the live API and warn.
- [ ] Location of settings.local.json: per user (`~/.parrot/jira/`) or per project (`.parrot/jira/`)?
- [ ] Should `jira_get_accessible_resources` be offered in static (basic/token) mode?

## 6. Recommended Next Step
`/sdd-spec jiratoolkit-upgrades`. The three modules are independent; M1 can ship first.

## 7. Research Audit
`sdd/state/jiratoolkit-upgrades/` (findings F001–F004). The budget was tight and the plan and review gates were
collapsed into one Q&A round. The FEAT-ID is provisional because the id ledger (next 696) disagrees with specs
that already cite FEAT-715. `/sdd-spec` will reserve the real id.
