# TASK-2406: `jira` host extra + operator runbook

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2404
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** (spec §3 M7). Two deliverables: a host `jira` extra so
`pip install 'ai-parrot[jira]'` — the string TASK-2400's error message tells
users to run — actually works, and the operator runbook.

Today `jira` only rides the host's `agents`/`mcp` extras
(`pyproject.toml:305, 356, 389`), which means the actionable install message
this feature emits would currently be **wrong**. That is the single highest-value
line in this task.

The runbook covers what no code can: the one-time `ns add` registration, the
cron line, the credential keys, and the `--force` / extractor-version
re-render path. The shape to follow is what TASK-2382 established for the
notes namespace.

---

## Scope

- Add a `jira` extra to `packages/ai-parrot/pyproject.toml`:
  `jira = ["jira>=3.10", "html2text==2025.4.15"]` — both are needed by the
  ingest path, and `html2text` currently also only rides `agents`/`mcp`.
- Verify the extra installs and that
  `python -c "import jira, html2text"` works from it.
- Write `docs/runbooks/jira-issues-namespace.md` covering:
  - what the corpus is and where it lives (off-repo, `PARROT_HOME`)
  - install (`pip install 'ai-parrot[jira]'`)
  - credential keys and the four auth modes
  - the one-time `wikitoolkit ns add issues --store … --global`
  - the **daily** cron line (spec §8, resolved)
  - the default JQL and how to widen it
  - re-render paths: `--force` and an `EXTRACTOR_VERSION` bump
  - reading a `SweepReport`, including what a non-zero `unresolved_link_keys`
    means and what `"partial"` means
  - the human-annotation contract (`<!-- jira-sync:end -->`)
  - what is **not** synced in v1 (comments, attachment payloads,
    cross-namespace edges) and the PII posture (G9)
- Link the runbook from `CLAUDE.md`'s "Codebase Knowledge Graph (LLM Wiki)"
  section so a future Claude Code session can find the `issues` namespace.

**NOT in scope**:
- Any code change to `parrot/` or `parrot_tools/`.
- Adding a scheduler. The runbook documents cron; nothing ships.
- Changing the `ai-parrot-tools` extra — it already has
  `jira = ["jira>=3.10"]` (`ai-parrot-tools/pyproject.toml:51`).
- Choosing the cron **host machine**. The spec resolved cadence (daily) but
  left the host an operator choice; the runbook names it as a placeholder the
  operator fills in.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add the `jira` extra |
| `docs/runbooks/jira-issues-namespace.md` | CREATE | The operator runbook |
| `CLAUDE.md` | MODIFY | One pointer line to the runbook + the `issues` namespace |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing.

### Verified facts about the packaging surface

```toml
# packages/ai-parrot/pyproject.toml
[project.optional-dependencies]     # :150
# `jira` and `html2text` today appear ONLY inside these extras:
#   :297  "html2text==2025.4.15"      :305  "jira==3.10.5"      (extra A)
#   :351  "html2text==2025.4.15"      :356  "jira==3.10.5"      (extra B)
#   :384  "html2text==2025.4.15"      :389  "jira==3.10.5"      (extra C)
# There is NO standalone `jira` extra. Identify which named extras A/B/C are
# (the spec says `agents` and `mcp`) by reading the section headers above each
# block, and follow their pin style.
#
# PIN STYLE DECISION: the host pins exact versions (jira==3.10.5,
# html2text==2025.4.15) while ai-parrot-tools uses a floor (jira>=3.10).
# Match the HOST's surrounding style for a host extra, or deliberately choose
# the floor and say why in the Completion Note. Do NOT silently mix.

# packages/ai-parrot-tools/pyproject.toml:51
jira = ["jira>=3.10"]               # already exists — DO NOT change
# :99 — the aggregate extra already includes ai-parrot-tools[jira,...]
```

### Verified facts the runbook must state correctly

```
# Registration — packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1826
wikitoolkit ns add issues --store <issues-dir>/.parrot/wiki --global \
    --description "Jira ticket corpus"
#   --store  -> kind "store", a PRE-BUILT store directory
#   --vault  -> REQUIRES .obsidian/ (cli.py:1864) — WRONG for this corpus
#   --global -> writes PARROT_HOME/wikis.json (per-user) instead of the
#               repo's wiki.json
#   ns_add docstring: "This is the only writer of namespace entries —
#     neither `build` nor any other command ever self-registers a wiki."
#     => registration is a ONE-TIME OPERATOR ACTION, by design.

# Querying — cli.py:1394 (query), :1483 (page), :1530 (related)
wikitoolkit query --ns issues "<phrase>"
wikitoolkit page issues::file:NAV-9372.md
wikitoolkit related issues::file:NAV-9372.md

# Storage layout (spec §2)
<issues-dir>/                       # default ${PARROT_HOME}/wikis/issues
├── NAV-9372.md
├── people/<slug>.md
├── projects/NAV.md
├── components/<slug>.md
├── labels/<slug>.md
└── .parrot/
    ├── jira_sync.json              # watermark + extractor version
    └── wiki/wiki.db                # the plane
# vault_scan.py:58 — ".parrot" is in VAULT_EXCLUDE_DIRS, so neither the state
#   file nor the plane is ever re-ingested as a note.

# Config keys (spec §2)
JIRA_WIKI_ISSUES_DIR   default ${PARROT_HOME}/wikis/issues
JIRA_WIKI_JQL          default `project = ${JIRA_DEFAULT_PROJECT}`
JIRA_WIKI_NAMESPACE    default `issues`
JIRA_WIKI_AC_FIELD     unset -> resolved by field name, else AC omitted
JIRA_INSTANCE, JIRA_AUTH_TYPE, JIRA_USERNAME, JIRA_API_TOKEN,
JIRA_SECRET_TOKEN, JIRA_OAUTH_*, JIRA_REQUEST_TIMEOUT   (existing, reused)
# JIRA_AUTH_TYPE has NO heuristic default (jiratoolkit.py:767-775) — leaving
#   it unset means every call raises. The runbook must say so explicitly.

# The resolved default JQL (spec §8): `project = ${JIRA_DEFAULT_PROJECT}`
#   single project, NO status filter, NO date bound. Closed/resolved tickets
#   are IN SCOPE deliberately. First run is a full backfill; the watermark
#   makes every run after that near-free.

# Cron cadence (spec §8, resolved): DAILY. Host machine = operator choice.
```

### Does NOT Exist

- ~~A `jira` extra in `packages/ai-parrot/pyproject.toml`~~ — created here.
  Confirm: `grep -n '^jira' packages/ai-parrot/pyproject.toml`
- ~~`docs/runbooks/jira-issues-namespace.md`~~ — created here. Check whether
  `docs/runbooks/` exists at all; if the repo puts runbooks elsewhere, follow
  the existing convention instead:
  `find docs -iname '*runbook*' -o -iname '*ns*' | head`
- ~~`ns add --vault` for this corpus~~ — requires `.obsidian/`
  (`cli.py:1864`). Always document `--store`.
- ~~`ingest-jira` self-registering the namespace~~ — it does not, by design.
  The runbook must present `ns add` as a required one-time step, or users will
  sweep successfully and then wonder why `query --ns issues` finds nothing.
- ~~Cross-namespace edges from a ticket to a repo spec~~ — unsupported
  (`cli.py:2665-2666`). The runbook must say the ticket↔spec join is
  **text-level** (frontmatter `repo_pages` + the `**Jira**:` line), findable by
  `query`, **not** traversable by `related`, and that a follow-up spec
  extending FEAT-450 is where real federated edges would come from.
- ~~Comment sync~~ — v1 non-goal. State it, so nobody files it as a bug.

---

## Implementation Notes

### The extra

```toml
# Jira ticket -> LLM Wiki ingest (FEAT-454). `jira` previously rode only the
# `agents`/`mcp` extras, so `pip install 'ai-parrot[jira]'` — the string the
# ingest path's own error message tells users to run — did not resolve.
jira = [
    "jira==3.10.5",
    "html2text==2025.4.15",
]
```
Place it near the other single-purpose extras and match the surrounding
comment style. Then actually verify it:
```bash
source .venv/bin/activate
uv pip install -e 'packages/ai-parrot[jira]'
python -c "import jira, html2text; print(jira.__version__)"
```
If the install fails, that is this task's problem to solve, not to document.

### Runbook outline

```markdown
# Runbook — the `issues` namespace (Jira ticket corpus)

## What this is
## Install
## Credentials
## One-time setup            <- ns add --store ... --global
## The daily sweep           <- the cron line
## Querying it
## Scope: the default JQL and how to widen it
## Re-rendering everything   <- --force, EXTRACTOR_VERSION bump
## Reading a SweepReport     <- partial, unresolved_link_keys, orphaned
## Your own notes survive    <- the <!-- jira-sync:end --> contract
## What is not synced in v1
## Troubleshooting
```

Make the **cron line** copy-pasteable and note that a `"partial"` run exits
non-zero so cron mail surfaces it:

```cron
# Daily Jira -> issues-namespace sweep (FEAT-454). Host: <FILL IN>.
17 6 * * *  cd /path/to/checkout && \
  /path/to/.venv/bin/wikitoolkit ingest-jira --quiet \
  >> /var/log/parrot/jira-ingest.log 2>&1
```

For **Troubleshooting**, cover the failure modes the code deliberately
surfaces — each one exists because it is otherwise silent:

| Symptom | Cause | Fix |
|---|---|---|
| Every call raises an auth error | `JIRA_AUTH_TYPE` unset — there is **no** heuristic default (`jiratoolkit.py:767-775`) | Set it explicitly |
| Sweep reports 0 fetched, run marked `partial` | Jira Cloud silent auth failure (`X-Seraph-Loginreason: AUTHENTICATED_FAILED`) — the watermark deliberately did **not** advance | Re-check credentials |
| `query --ns issues` finds nothing after a successful sweep | The namespace was never registered — `ns add` is a required one-time step | Run the `ns add` line |
| `unresolved_link_keys` is non-empty | A ticket links outside the JQL scope; the edge is dropped (`vault_scan.py:183`) but the key is still in the frontmatter | Widen `JIRA_WIKI_JQL` if the edge matters |
| A large `orphaned` count | Tickets moved project or were renamed | Review; documents are never auto-deleted |
| Acceptance-criteria section missing | The AC custom field did not resolve | Set `JIRA_WIKI_AC_FIELD` |
| `related` does not reach a repo spec | Cross-namespace edges do not exist (`cli.py:2665-2666`) — the join is text-level | Use `query` across namespaces |

### Key Constraints

- **Documentation and packaging only.** No change under `src/`.
- Every command in the runbook must be **run once and verified** before being
  written down. A runbook with an untested command is worse than none.
- State the PII posture plainly: person pages carry display name and
  `accountId` only; no email is ever captured (G9).
- Emphasise **G8**: the corpus lives outside the git repo so internal ticket
  prose and customer names never enter git history. Warn against pointing
  `JIRA_WIKI_ISSUES_DIR` inside a checkout.
- Keep the `CLAUDE.md` edit to a **single pointer line** in the existing LLM
  Wiki section — that file is loaded into every session's context.

### References in Codebase

- `packages/ai-parrot/pyproject.toml:150+` — the extras block
- `packages/ai-parrot-tools/pyproject.toml:51` — the existing tools `jira` extra
- `docs/migration/feat-201-ai-parrot-embeddings.md` — an existing docs artifact
  for tone/structure
- The TASK-2382 notes-namespace runbook (find it:
  `grep -rln "ns add" docs/`) — the shape this task follows

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/pyproject.toml` has a `jira` extra, and
      `uv pip install -e 'packages/ai-parrot[jira]'` succeeds.
- [ ] `python -c "import jira, html2text"` works from a venv where only the
      `jira` extra was installed.
- [ ] The pin style matches the surrounding host extras (or the deviation is
      justified in the Completion Note).
- [ ] `docs/runbooks/jira-issues-namespace.md` exists and documents: install,
      credential keys, the four auth modes, the one-time `ns add --store`, the
      daily cron line, the default JQL and how to widen it, `--force` and the
      `EXTRACTOR_VERSION` re-render path, how to read a `SweepReport`, the
      `<!-- jira-sync:end -->` contract, the v1 non-goals, and the
      troubleshooting table.
- [ ] Every command in the runbook was executed and verified (list them in the
      Completion Note).
- [ ] The runbook states that `JIRA_AUTH_TYPE` has no default and that leaving
      it unset makes every call raise.
- [ ] The runbook states that `ns add` is a **required** one-time step and that
      `ingest-jira` never self-registers.
- [ ] The runbook states the ticket↔spec join is text-level, not traversable
      by `related`, and points at the follow-up FEAT-450 extension.
- [ ] The runbook warns against pointing `JIRA_WIKI_ISSUES_DIR` inside a
      git checkout (G8).
- [ ] `CLAUDE.md` gains exactly one pointer line to the runbook in the LLM
      Wiki section.
- [ ] `packages/ai-parrot-tools/pyproject.toml` is **unmodified**.
- [ ] No source file under any `src/` tree is modified by this task
      (`git diff --name-only` shows only pyproject, docs, CLAUDE.md).

---

## Test Specification

No unit tests — this task is packaging and documentation. Verification is
executed, not asserted:

```bash
source .venv/bin/activate

# 1. The extra resolves and imports.
uv pip install -e 'packages/ai-parrot[jira]'
python -c "import jira, html2text; print(jira.__version__, html2text.__file__)"

# 2. The install string the code emits is now correct.
grep -rn "ai-parrot\[jira\]" packages/ai-parrot/src/parrot/interfaces/jira/
grep -n '^jira' packages/ai-parrot/pyproject.toml

# 3. Every runbook command actually works. Run each one and paste the
#    outcome into the Completion Note.
wikitoolkit ingest-jira --help
wikitoolkit ns add --help
wikitoolkit query --help

# 4. Nothing under src/ was touched.
git diff --name-only | grep -E '/src/' && echo "FAIL: source modified" || \
  echo "OK: docs+packaging only"

# 5. The tools extra is untouched.
git diff --quiet -- packages/ai-parrot-tools/pyproject.toml && \
  echo "OK" || echo "FAIL: tools pyproject modified"
```

Optionally add a packaging smoke test if the repo already has one for extras:
```bash
grep -rn "optional-dependencies\|extras" packages/ai-parrot/tests/ | head
```
If such a test exists, extend it with the `jira` extra rather than adding a
new file.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§3 M7, §2 "Configuration keys", §7 "External Dependencies", §8's resolved cron/JQL decisions) for full context
2. **Check dependencies** — TASK-2404 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing anything:
   - `grep -n '^jira\|^html2text' packages/ai-parrot/pyproject.toml`
   - Read the section headers above lines 297/305, 351/356, 384/389 to learn
     which extras those are and match their style
   - `find docs -iname '*runbook*'` and `grep -rln "ns add" docs/` — follow the
     existing runbook location and shape rather than inventing one
   - Read `CLAUDE.md`'s "Codebase Knowledge Graph (LLM Wiki)" section to place
     the pointer line correctly
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** the extra first, verify the install, **then** write the
   runbook — so every command you document has already been run
6. **Verify** all acceptance criteria are met
7. **Save the LLM-wiki memory**: after the runbook lands, record the durable
   fact so future sessions find it —
   `wikitoolkit remember "The Jira ticket corpus is queryable as the \`issues\`
   namespace; see docs/runbooks/jira-issues-namespace.md" --category note
   --title "issues namespace (Jira corpus)"`
8. **Move this file** to `sdd/tasks/completed/TASK-2406-jira-extra-and-runbook.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-24)
**Date**: 2026-08-24

**Notes**: Added a standalone `jira` extra to `packages/ai-parrot/pyproject
.toml` right after the similarly-shaped single-service `reddit` extra
(before `retrieval`), with a comment explaining why it exists (the
`JiraDependencyError` install string). Verified it actually resolves via
`uv pip install -e 'packages/ai-parrot[jira]'` in the shared venv, then
**reverted the editable install back to the main checkout** immediately
after verifying (`cd` to the main repo, reinstall against
`packages/ai-parrot` there) — the shared venv's editable pointer had
switched to this worktree, which would have left the venv in a broken
state for other concurrent worktree sessions once this worktree is
eventually removed post-merge. Confirmed `all`/`all-fast` already reach
`jira` transitively (they already depend on `agents`/`mcp`/`agents-lite`,
all three of which already pin `jira`/`html2text`), so no change was
needed there. `packages/ai-parrot-tools/pyproject.toml` is untouched
(verified via `git diff --quiet`).

TASK-2382's referenced notes-namespace runbook could not be found
anywhere in the repo (`find docs -iname '*runbook*'` and
`grep -rln "ns add" docs/` both returned nothing) — `docs/runbooks/` did
not exist yet. Created it at the spec's own suggested path
(`docs/runbooks/jira-issues-namespace.md`), the first runbook of its kind
in this repo, following `docs/migration/feat-201-ai-parrot-embeddings.md`
for tone/structure per the task's own reference.

Saved the durable LLM-wiki memory per Agent Instructions step 7:
`wikitoolkit remember "The Jira ticket corpus is queryable as the
\`issues\` namespace; see docs/runbooks/jira-issues-namespace.md"
--category note --title "issues namespace (Jira corpus)"` — succeeded
(`mem-6bf27c6444de`, graph commit `75aa5aec8004479e`), written to the
repo's own git-ignored `.parrot/wiki` plane (untracked, no effect on this
feature's commits).

**Pin style chosen**: **exact (`==`)** — `jira==3.10.5`,
`html2text==2025.4.15` — matching the host's existing `agents`/
`agents-lite`/`mcp` extras verbatim (all three already pin these two
packages at these exact versions). `ai-parrot-tools[jira]`'s floor
(`jira>=3.10`) is a deliberately different package with a different
install surface (a tools-only, no-html2text extra) and was left
unchanged, per scope.

**Runbook commands executed and verified** (via `CliRunner`, isolated
`PARROT_HOME`, never touching the developer's real registry):
- `wikitoolkit ingest-jira --help` → exit 0
- `wikitoolkit ns add --help` → exit 0 (confirmed exact flag names:
  `--store`, `--global`, `--description`, no `--vault` requirement issue)
- `wikitoolkit query --help` → exit 0
- `wikitoolkit ns add issues --store <dir> --global --description "Jira
  ticket corpus"` → exit 0, `"Added namespace 'issues' (store) →
  <tmp>/wikis.json"`
- `wikitoolkit ns list --json` → exit 0, `"issues"` present in output
- `uv pip install -e 'packages/ai-parrot[jira]'` → resolved and installed
  cleanly
- `python -c "import jira, html2text; print(jira.__version__,
  html2text.__file__)"` → `3.10.5 <path>/html2text/__init__.py`

**Runbook location**: `docs/runbooks/jira-issues-namespace.md` (the
spec's own suggested default) — no existing runbook convention was found
to defer to instead (see Notes above).

**Deviations from spec**: none.
