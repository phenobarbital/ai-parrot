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
Users report that **they cannot attach `.docx` files to a Jira ticket** through an
agent. The report arrived as "there is a bug" with no stack trace, no HTTP status
and no per-file-type matrix — so the first job of this brainstorm was to find out
whether there is a Jira failure at all.

There is not, at least not on the path the users exercise. Codebase research
found a **silent drop** upstream of Jira:

1. A file uploaded in a chat / web session reaches
   `AgentHandler._handle_attachments` (`packages/ai-parrot-server/src/parrot/handlers/agent.py:1278`),
   which calls `bot.handle_files(attachments)`.
2. `Agent.handle_files` (`packages/ai-parrot/src/parrot/bots/agent.py:365`) only
   understands `.xlsx`, `.xls` and `.csv`. It reads every other file into a
   `BytesIO`, finds no DataFrame branch for it, **drops the bytes and never
   writes anything to disk** (`agent.py:404-418`).
3. The handler nevertheless answers `{"message": "Files uploaded successfully",
   "added_files": []}` (`handlers/agent.py:1289-1291`). The user sees *success*.
4. The agent is then asked to attach the document. The only tool available,
   `JiraToolkit.jira_add_attachment`
   (`packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1748`), accepts
   **one filesystem path** (`attachment: str`). No path exists for that upload,
   so the model either hallucinates one (→ `FileNotFoundError` from
   `jira.JIRA.add_attachment`) or reports that it cannot do it.

So "docx cannot be uploaded" is really **"non-tabular uploads are discarded
before any Jira code runs"**. Word and PDF are simply the formats users actually
hand to a ticketing agent; CSV/Excel work by accident because they take the
DataFrame branch.

Three further weaknesses compound it and must be addressed in the same feature,
because any fix that only restores the path would still be fragile:

- **Two divergent attachment paths.** `jira_add_attachment` (`jiratoolkit.py:1748`)
  lets the exception escape; the upload loop inside `jira_add_comment`
  (`jiratoolkit.py:2055-2079`) catches every exception and returns
  `{"file": …, "error": …}` instead. Same operation, opposite failure contracts.
- **No pre-flight validation.** Size, emptiness and type are never checked.
  The underlying library raises `JIRAError("Added empty attachment?!")` only
  *after* the upload round-trip (`jira/client.py:1198-1202`), and Jira's own
  attachment-size limit surfaces as an opaque HTTP error — neither is actionable
  for an LLM deciding whether to retry.
- **Wrong Content-Type.** `jira.JIRA.add_attachment` hard-codes
  `application/octet-stream` for every file (`jira/client.py:1159-1161`), so even
  a successful docx/PDF lands in Jira without its real MIME type, losing the
  icon and preview.

**Who is affected**: end users of any agent with `JiraToolkit` enabled (support
and ticketing flows), plus every agent that produces a document and wants to
attach it to a ticket.

### Constraints and goals
Locked during discovery (Rounds 0–3) — these are decisions, not suggestions:

- **Flow type**: `feature`, base branch `dev`.
- **Four origins in scope**: server-side path, chat upload, remote URL
  (SharePoint / Drive / S3), and agent-generated document.
- **Both call paths in scope**: `jira_add_attachment` and
  `jira_add_comment(attachments=[…])`.
- **Strict session sandbox.** An agent may attach *only* files inside its own
  session store. A remote URL must be downloaded into that store by an explicit
  tool first; the Jira tool never fetches a URL itself. This is the security
  boundary against prompt-injected exfiltration (`/etc/…`, other tenants' files)
  and against SSRF to internal metadata endpoints.
- **Opaque handles.** The Jira tool takes a session `file_id`, not a path. The
  model never sees, and therefore cannot invent, a filesystem path.
- **Hard cut** on the tool contract — a single helper behind both tools, all
  callers updated in-feature, no compatibility shim (the repo has no external
  consumers of these signatures).
- **Best-effort semantics** with a per-file report (success/error per item), so
  the model can retry exactly what failed. No all-or-nothing: Jira offers no
  attachment rollback.
- **Pre-flight validation** of existence, emptiness, size and type, returning an
  actionable error instead of an opaque `JIRAError`.
- ~~**Real Content-Type** sent per file~~ — **reversed on 2026-10-07 during `/sdd-spec`**:
  we keep `jira.JIRA.add_attachment` and accept `application/octet-stream`, rather
  than hand-rolling a multipart POST. See the resolved Open Question below.
- **Lifecycle**: session files persist; cleanup is manual. No TTL, no
  end-of-session sweep.
- **Project conventions**: async-first (`asyncio.to_thread` around the
  sync `jira` client), `aiohttp` only for HTTP, Pydantic v2 schemas,
  `self.logger`, no new provider SDK.

---

### Recommended option / probable scope
**Option D** is recommended.

Option A is tempting — it is a fraction of the effort and touches one file — but
it fixes the layer that is *not* broken for the reporting users. Shipping it
would close the ticket without changing what those users experience, which is the
worst outcome available here.

Option B dies on the context budget: pushing document bytes through the model is
precisely what the compaction machinery exists to prevent, and it would make the
cost of attaching a file scale with every subsequent turn.

Option C would produce a cleaner attachment-specific abstraction, and that is a
genuine loss we are accepting: `FileManagerToolkit` was not designed around
session scoping, so D has to extend it. But C's cost is a second file
abstraction competing with the first at tool-selection time, for a store that
only Jira would use on day one. Reuse wins.

What Option D trades away, stated plainly:

- **Breadth over speed** — three distributions instead of one, and a longer task
  graph, in exchange for fixing the reported bug rather than its neighbour.
- **An extension to a shared component** — per-session roots and handle
  resolution land in `FileManagerToolkit`, so a regression there is felt by every
  file-using agent. Mitigated by keeping session scoping additive and by the
  existing toolkit test suite.
- **A bespoke multipart upload** for the real Content-Type, instead of leaning
  entirely on the `jira` library. Contained to one helper; the fallback is to
  keep `octet-stream` and drop that acceptance criterion if the custom request
  proves brittle against the target Jira deployment.

---

Two halves, one feature:

**D1 — stop the drop.** `Agent.handle_files` keeps its DataFrame branch for
tabular files and gains a second branch: every other upload is **persisted** into
a per-session root inside the existing `FileManagerToolkit` `fs` backend, and
registered under a stable opaque `file_id`. The handler's response becomes
honest — it reports what was stored *and* what was turned into a DataFrame, so
`added_files: []` with a success message is no longer possible. The agent learns
about the files through the toolkit's listing tool (and/or a working-memory
namespace), never through a raw path.

**D2 — one attachment path.** Both `jira_add_attachment` and
`jira_add_comment(attachments=…)` route through a single internal helper that
takes **`file_id`s**, resolves them against the session root, pre-validates
(exists, non-empty, size against the Jira limit, type), uploads with the **real
Content-Type**, and returns a **per-file report**. Remote URLs are handled by
`FileManagerToolkit`'s existing download backends (`s3`, `gcs`, `sharepoint`,
`onedrive`, `gdrive`) — the Jira tool never performs a network fetch.

✅ **Pros:**
- Fixes the bug users actually reported, and the three latent weaknesses, in one
  coherent change.
- Reuses a mature, already-sandboxed component instead of growing a second one;
  the remote-URL origin comes almost free via existing backends.
- The opaque handle makes the sandbox hold *by construction*: there is no path
  for a prompt injection to point anywhere else.
- Equally serves the "agent generated a report" origin — write it into the
  session store, attach it by handle.

❌ **Cons:**
- Touches three distributions (`ai-parrot`, `ai-parrot-tools`, `ai-parrot-server`),
  so the task graph is wider than Option A's.
- `FileManagerToolkit` must learn a per-session root and a handle↔path mapping it
  does not have today — a real, if contained, extension.
- Manual-only cleanup (an explicit decision) means disk growth needs an operator
  runbook.
- Content-Type cannot be passed through `jira.JIRA.add_attachment`, which
  hard-codes `application/octet-stream` (`jira/client.py:1159-1161`). Honouring it
  requires posting the multipart request ourselves against
  `issue/{key}/attachments` with `X-Atlassian-Token: no-check` — a small, well
  understood piece of extra surface that must be explicitly specced.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jira` | Jira REST client | `==3.10.5` (`packages/ai-parrot/pyproject.toml:388`) — still used for everything but the custom-MIME upload |
| `aiohttp` | Multipart upload with the real Content-Type | Mandatory per conventions; `requests`/`httpx` are banned |
| `mimetypes` (stdlib) | Extension → MIME | Already the house pattern (`clients/base.py:1416`, `integrations/parser.py:142`) |
| `python-magic` *(optional)* | Content-based sniffing | Only if extension-trust proves insufficient; adds libmagic |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/filemanager.py:724` — `FileManagerToolkit`, sandboxed `fs`/`temp` backends, `max_file_size`, seven storage backends
- `packages/ai-parrot/src/parrot/tools/filemanager.py:944` / `:993` / `:1222` / `:1144` — `upload_file`, `download_file`, `find_files`, `get_file_metadata`
- `packages/ai-parrot/src/parrot/bots/agent.py:365` — `Agent.handle_files`, extended, not replaced
- `packages/ai-parrot-server/src/parrot/handlers/agent.py:1278` — `_handle_attachments`, honest response
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1748` / `:2027` — the two tools to converge
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:47` — `WorkingMemoryToolkit` (`tool_prefix = "wm"`, line 81), optional surfacing of handles
- `packages/ai-parrot/tests/test_jira_comment_attachments.py` — existing suite to extend with a per-type matrix

### User-Facing Behavior

- A user attaches `report.docx` (or a PDF, PNG, ZIP…) in the chat and says
  *"attach this to NAV-123"*. The agent attaches it. This is the headline change.
- The upload response stops lying: it lists what was **stored** and what was
  **registered as a DataFrame**. An upload that produced neither is an explicit
  error, not a success with an empty list.
- When several files are attached and some fail, the agent reports precisely
  which ones failed and why ("file is empty", "exceeds the 10 MB Jira limit"),
  so the user can act — instead of a blanket "it did not work".
- An agent-generated document (an exported report, a converted PDF) is attached
  through the same route, with no special casing.
- A document living in SharePoint / Drive / S3 is first brought into the session
  store by the file tool, then attached by handle. The Jira tool itself never
  reaches out to the network.

### Internal Behavior

1. **Ingestion.** `Agent.handle_files` keeps its tabular branch. Everything else
   is written through `FileManagerToolkit` into a per-session root under
   `OUTPUT_DIR`, and recorded with an opaque `file_id`, the original filename, the
   resolved MIME type, size and origin.
2. **Discovery.** The agent enumerates what it holds through the file toolkit's
   listing tool (optionally mirrored into a working-memory namespace so recent
   uploads are visible without a tool call). Handles — never paths — are what the
   model sees.
3. **Resolution.** The shared Jira attachment helper maps each `file_id` to a
   concrete path **inside the session root**. A handle that is unknown, or that
   resolves outside the root after normalization, is rejected before any I/O.
4. **Pre-flight.** Per file: exists, non-empty, size within the Jira attachment
   limit, type resolvable. Failures are collected, not raised.
5. **Upload.** Each surviving file is posted to `issue/{key}/attachments` with its
   real Content-Type and `X-Atlassian-Token: no-check`, off the event loop.
6. **Report.** One entry per input handle — `ok`, filename, Jira attachment id,
   size and MIME on success; a stable, machine-readable reason on failure. Both
   `jira_add_attachment` and `jira_add_comment` return the same shape (hard cut).

### Edge Cases & Error Handling

| Situation | Behavior |
|---|---|
| Unknown `file_id` | Rejected in pre-flight: `unknown_handle`, no I/O, no exception |
| Handle resolving outside the session root | Rejected: `outside_sandbox`, logged at WARNING as a security event |
| Zero-byte file | Rejected before upload — avoids the library's post-hoc `"Added empty attachment?!"` (`jira/client.py:1198-1202`) |
| File larger than the Jira attachment limit | Rejected with the limit in the message, so the model can propose splitting or linking |
| MIME not resolvable from the extension | Falls back to `application/octet-stream` and uploads anyway — unknown type is not a reason to refuse |
| Some files fail, others succeed | Best-effort: successes stand, the report names each failure. No rollback (Jira has none) |
| Jira rejects the upload (403 / XSRF / 413) | Status and body surfaced verbatim in that file's entry, not swallowed |
| Issue key does not exist or is not writable | Fails for the whole call before any upload is attempted |
| Same filename uploaded twice in a session | Distinct handles; Jira keeps both attachments, as it does for a human uploader |
| Tabular file (CSV/XLSX) | Still becomes a DataFrame **and** is stored, so it can be attached too |
| Disk full while persisting an upload | Upload call fails explicitly; partial file removed |

---

### Verified code anchors (paths only — open them yourself)
.venv/lib/python3.12/site-packages/jira/client.py
packages/ai-parrot-server/src/parrot/handlers/agent.py
packages/ai-parrot-tools/pyproject.toml
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot/src/parrot/bots/agent.py
packages/ai-parrot/src/parrot/conf.py
packages/ai-parrot/src/parrot/interfaces/jira.py
packages/ai-parrot/src/parrot/interfaces/jira/client.py
packages/ai-parrot/src/parrot/tools/filemanager.py
packages/ai-parrot/src/parrot/tools/working_memory/tool.py
packages/ai-parrot/tests/test_jira_comment_attachments.py
packages/ai-parrot/tests/test_jiratoolkit_permissions.py

### Questions still open in the exploration document
- [ ] Which Jira deployment is the target — Cloud or Server/DC — and under which `auth_type`? The attachment size limit and the XSRF behavior differ, and the acceptance matrix needs a concrete limit to assert against. — *Owner: Jesus*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
