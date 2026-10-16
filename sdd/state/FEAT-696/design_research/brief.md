<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
### 2.3 Constraints
- The toolkit file is large and touched by FEAT-637/639. Re-check line numbers before editing.
- aiohttp only. Secrets go only in git-ignored files or env vars.

### Recommended option / probable scope
## 3. Scope
**M1 — Parity tools:** add `jira_create_issue_link` (with `jira_get_link_types`),
`jira_get_create_fields(project, issue_type)` (createmeta), `jira_edit_comment(issue, comment_id, body)` (FEAT-637
template support optional), and `jira_get_accessible_resources` (all modes; see §5).

**M2 — `parrot jiratoolkit auth`:** a click group in ai-parrot-tools, registered lazily like `manuals`. The flow:
1. Print the Atlassian authorize URL (redirect = `JIRA_OAUTH_REDIRECT_URI`) and prompt the user to paste back the
   redirected URL or the code. There is no local server (**decided**).
2. Exchange the code for tokens and resolve `cloud_id` via accessible-resources. If several sites are returned,
   the user picks one.
3. Persist the result in two places (**decided: both**):
   - `JIRA_OAUTH_CLIENT_ID` and `JIRA_OAUTH_CLIENT_SECRET` go in `.env`.
   - The rotating access/refresh tokens, `cloud_id` and `site` go in `~/.parrot/jira/settings.local.json`, mode 0600 (**decided: per user**).
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
packages/ai-parrot-tools/src/parrot_tools/jira_config.py
packages/ai-parrot/src/parrot/auth/jira_oauth.py
packages/ai-parrot/src/parrot/cli/__init__.py
packages/ai-parrot/src/parrot/interfaces/jira/client.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
