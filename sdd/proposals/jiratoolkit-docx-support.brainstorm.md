---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [jira, attachments, file-upload, sandbox, toolkit]
---

# Brainstorm: Jira attachments for binary documents (docx / PDF)

**Date**: 2026-10-07
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option D

---

## Problem Statement

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

## Constraints & Requirements

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
- **Real Content-Type** sent per file, not `application/octet-stream`.
- **Lifecycle**: session files persist; cleanup is manual. No TTL, no
  end-of-session sweep.
- **Project conventions**: async-first (`asyncio.to_thread` around the
  sync `jira` client), `aiohttp` only for HTTP, Pydantic v2 schemas,
  `self.logger`, no new provider SDK.

---

## Options Explored

### Option A: Harden `JiraToolkit` only

Leave the upload pipeline alone. Unify the two attachment paths inside
`jiratoolkit.py`, add pre-flight validation (exists / non-empty / size / type),
send the real MIME type, and return a per-file report with actionable errors.
Accept paths as today, validated against an allowed root.

✅ **Pros:**
- Smallest blast radius — one file, one package, one test module to extend.
- Fixes the *second* layer of the problem permanently: whatever hands a path to
  the toolkit afterwards benefits.
- Could ship in days.

❌ **Cons:**
- **Does not fix the reported bug.** The chat-upload case — the one users hit —
  still has no file to attach. The report would come back.
- Leaves the "success with `added_files: []`" lie in place.
- Keeps path-shaped inputs in the model's hands, which the agreed security
  posture rejects.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jira` | Jira REST client | `==3.10.5` pinned in `packages/ai-parrot/pyproject.toml:388`; `>=3.10` in `packages/ai-parrot-tools/pyproject.toml:54` |
| `python-magic` *(optional)* | Content-based MIME sniffing | Avoids trusting the extension; adds a libmagic system dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1748` — `jira_add_attachment`
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2055-2079` — the upload loop to fold into the shared helper
- `packages/ai-parrot/tests/test_jira_comment_attachments.py` — six existing tests covering valid / missing / mixed / error cases

---

### Option B: Pass bytes through the tool call

Extend the tool schema so the agent can hand over the document inline
(base64 + filename), bypassing the filesystem entirely. The handler returns the
upload's base64 to the model, which forwards it to Jira.

✅ **Pros:**
- No session store, no path resolution, no sandbox root to configure.
- Works identically across every deployment topology, including stateless
  workers that share no disk.

❌ **Cons:**
- **Fatal for the actual use case**: a 2 MB docx is ~2.7 MB of base64, far beyond
  any model's context budget, and it would be billed as input tokens on every
  turn it stays in history. Exactly the content `memory/compaction/` exists to
  keep *out* of context.
- The model becomes a data pipe, with a real chance of silent corruption.
- Cannot express "the file the user just uploaded" without first serializing it.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `base64` (stdlib) | Transport encoding | +33% size, before tokenization |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:361` — `AddAttachmentInput`

---

### Option C: Build a dedicated `SessionAttachmentStore`

A new, purpose-built store owned by `AbstractBot`: per-session directory, rich
metadata (original filename, declared and sniffed MIME, origin, uploader,
checksum), its own listing tool, and its own handle namespace. `JiraToolkit`
consumes handles from it.

✅ **Pros:**
- Metadata model tailored to attachments; richest audit trail.
- Full control over the handle format and over what the model can enumerate.

❌ **Cons:**
- Duplicates most of `FileManagerToolkit` (`packages/ai-parrot/src/parrot/tools/filemanager.py:724`),
  which already offers a sandboxed `fs`/`temp` backend, a size limit, listing,
  metadata and seven storage backends.
- Two overlapping file abstractions for agents to confuse — a tool-selection
  regression at prompt level.
- Nothing but Jira would adopt it at first, so the generality is unpaid-for.

📊 **Effort:** High

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:47` — `WorkingMemoryToolkit`, for surfacing handles in context
- `packages/ai-parrot/src/parrot/conf.py:56` — `OUTPUT_DIR` as the parent root

---

### Option D: Session file store on `FileManagerToolkit` + handle-based Jira attachments *(recommended)*

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

---

## Recommendation

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

## Feature Description

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

## Capabilities

### New Capabilities
- `session-file-store`: per-session, sandboxed persistence of uploaded and
  agent-generated files on top of `FileManagerToolkit`, addressed by opaque
  handles.
- `jira-attachment-pipeline`: one validated, MIME-aware, best-effort attachment
  path shared by `jira_add_attachment` and `jira_add_comment`.

### Modified Capabilities
- `Agent.handle_files` ingestion (`packages/ai-parrot/src/parrot/bots/agent.py:365`)
  — non-tabular uploads persisted instead of discarded.
- Agent upload endpoint response (`packages/ai-parrot-server/src/parrot/handlers/agent.py:1278`)
  — reports stored files; no success-with-nothing.
- `JiraToolkit` attachment tool contracts (`jiratoolkit.py:361`, `:455`, `:1748`,
  `:2027`) — hard cut to handles plus per-file report.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | modifies | Hard cut on `AddAttachmentInput` / `AddCommentInput`; both tools converge on one helper |
| `packages/ai-parrot/src/parrot/bots/agent.py` | extends | `handle_files` gains the persistence branch; tabular behavior preserved |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | extends | Per-session root + handle↔path resolution; shared by every file-using agent — regression risk |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | modifies | `_handle_attachments` response shape (API change for the admin UI / clients) |
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | depends on | Optional: surface recent handles in context |
| `packages/ai-parrot/src/parrot/conf.py` | depends on | `OUTPUT_DIR` as the parent of session roots |
| `packages/ai-parrot/tests/test_jira_comment_attachments.py` | extends | Add the per-type matrix and the sandbox-rejection cases |
| `packages/ai-parrot/tests/test_jiratoolkit_permissions.py` | modifies | `jira.write` assertions must follow the renamed/reshaped tools |
| Admin UI upload flow | depends on | Consumes the changed upload response — coordinate if it parses `added_files` |

**Breaking changes**: yes, by decision — the tool signatures and the upload
endpoint's response shape both change, with all in-repo callers updated in the
same feature. **New dependencies**: none mandatory (`python-magic` only if
extension-based MIME proves insufficient). **Deployment**: `OUTPUT_DIR` must be
writable and on persistent storage, since cleanup is manual.

---

## Code Context

### User-Provided Code

No code was supplied by the user. The report was narrative:

```text
# Source: user-provided (brainstorm invocation, 2026-10-07)
Por algún motivo (usuarios indican que hay un bug o error), no se pueden subir
archivos docx a un ticket de Jira, es necesario permitir subir archivos Docx o
PDF como attachments del ticket.
```

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:361
class AddAttachmentInput(BaseModel):
    """Input for adding an attachment to an issue."""
    issue: str = Field(description="Issue key or id")                     # line 364
    attachment: str = Field(description="Path to attachment file on disk")  # line 365


# From packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:455
class AddCommentInput(BaseModel):
    """Input for adding a comment to an issue."""
    issue: str                                            # line 458
    body: str                                             # line 459
    is_internal: bool = Field(default=False, ...)         # line 460
    attachments: Optional[List[str]] = Field(default=None, ...)  # line 461


# From packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1746-1758
@requires_permission("jira.write")
@tool_schema(AddAttachmentInput)
async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]:
    """Add an attachment to an issue. Requires jira.write permission."""
    def _run():
        return self.jira.add_attachment(issue=issue, attachment=attachment)
    await asyncio.to_thread(_run)
    return {"ok": True, "issue": issue, "attachment": attachment}


# From packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2027
async def jira_add_comment(
    self, issue: str, body: str, is_internal: bool = False,
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    ...
    # lines 2055-2079: per-file loop — os.path.isfile check, asyncio.to_thread
    # upload, exceptions captured into {"file": ..., "error": ...}, collected
    # into result["attachments"]


# From packages/ai-parrot/src/parrot/bots/agent.py:365
async def handle_files(self, attachments: Dict[str, Any]) -> List[str]:
    """Handle uploaded files and register them as DataFrames."""
    # lines 404-410: ONLY .xlsx/.xls/.csv produce a DataFrame
    # lines 411-418: anything else → df is None → nothing stored, bytes dropped


# From packages/ai-parrot-server/src/parrot/handlers/agent.py:1278
async def _handle_attachments(
    self, bot: AbstractBot, agent: AbstractBot, attachments: Dict[str, Any]
) -> web.Response:
    added_files = await bot.handle_files(attachments)            # line 1287
    return self.json_response(
        {"message": "Files uploaded successfully",
         "added_files": added_files, "agent": agent.name}        # lines 1289-1291
    )


# From packages/ai-parrot/src/parrot/tools/filemanager.py:724
class FileManagerToolkit(AbstractToolkit):
    tool_prefix: Optional[str] = "fs"                            # line 762
    def __init__(self, manager_type: ManagerType = "fs",
                 default_output_dir: Optional[str] = None,
                 allowed_operations: Optional[Set[str]] = None,
                 max_file_size: int = 100 * 1024 * 1024,
                 auto_create_dirs: bool = True, **manager_kwargs) -> None: ...  # line 764
    async def list_files(...)          # line 905
    async def upload_file(...)         # line 944
    async def download_file(...)       # line 993
    async def get_file_metadata(...)   # line 1144
    async def create_file(...)         # line 1173
    async def find_files(...)          # line 1222
    async def batch_upload(self, items: List[Dict[str, str]]) -> Dict[str, Any]   # line 1258
    async def batch_download(self, items: List[Dict[str, str]]) -> Dict[str, Any] # line 1348
    def _storage_path(self, path) -> str        # line 870
    def _resolve_output_path(self, path) -> str # line 887
    def _check_file_size(self, size) -> None    # line 854


# From packages/ai-parrot/src/parrot/tools/working_memory/tool.py:47
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
    tool_prefix: str = "wm"          # line 81
```

External library behavior (installed, verified):

```python
# From .venv/lib/python3.12/site-packages/jira/client.py:1119-1203  (jira==3.10.5)
def add_attachment(self, issue, attachment: str | BufferedReader,
                   filename: str | None = None) -> Attachment:
    if isinstance(attachment, str):
        attachment_io = open(attachment, "rb")      # line 1141 — raises FileNotFoundError
    ...
    encoded_data = MultipartEncoder(
        fields={"file": (fname, attachment_io, "application/octet-stream")}  # line 1160
    )                                               # ← Content-Type is HARD-CODED
    request_headers = {"content-type": ..., "X-Atlassian-Token": "no-check"}  # 1162-1167
    url = self._get_url(f"issue/{issue}/attachments")                         # line 1179
    ...
    if jira_attachment.size == 0:
        raise JIRAError("Added empty attachment?!: ...")                      # 1198-1202
```

#### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot_tools.jiratoolkit import JiraToolkit            # packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
from parrot.tools.filemanager import FileManagerToolkit     # packages/ai-parrot/src/parrot/tools/filemanager.py:724
from parrot.tools.working_memory.tool import WorkingMemoryToolkit  # :47
from parrot.conf import OUTPUT_DIR                          # packages/ai-parrot/src/parrot/conf.py:56
from parrot.interfaces.jira.client import JiraInterface     # packages/ai-parrot/src/parrot/interfaces/jira/client.py:101
# Inside jiratoolkit.py (lines 52-57):
from parrot.tools.manager import ToolManager
from .toolkit import AbstractToolkit
from .decorators import tool_schema, requires_permission
from .jira_config import JiraToolkitConfig
```

#### Key Attributes & Constants

- `JiraToolkit.jira` → `jira.JIRA` instance, built by `_init_jira_client()`
  (`jiratoolkit.py:915`), assigned in `_set_jira_client()` (`:908`); it is `None`
  in the 3LO paths and resolved per-call in `_pre_execute` (`:819`, `:829`, `:848`)
- `_init_jira_client` options: `{"server": …, "verify": False,
  "headers": {"Accept-Encoding": "gzip, deflate"}}` (`jiratoolkit.py:916-921`)
- `JiraToolkit._issue_to_dict(issue_obj)` → `Dict[str, Any]` (`jiratoolkit.py:1157`)
- `FileManagerToolkit.max_file_size` → default `100 * 1024 * 1024` (`filemanager.py:768`)
- `FileManagerToolkit.manager_type` → `"fs" | "temp" | "s3" | "gcs" | "sharepoint" | "onedrive" | "gdrive"` (`filemanager.py:746-753`)
- `OUTPUT_DIR` → `Path`, defaults to `BASE_DIR/outputs`, created at import (`conf.py:56-60`)
- `jira` pin → `jira==3.10.5` (`packages/ai-parrot/pyproject.toml:388`), `jira>=3.10` (`packages/ai-parrot-tools/pyproject.toml:54`)
- Existing tests: `packages/ai-parrot/tests/test_jira_comment_attachments.py`
  (`test_add_comment_with_valid_attachments:51`, `…_missing_file:83`,
  `…_mixed_files:99`, `…_attachment_upload_error:127`) and
  `packages/ai-parrot/tests/test_jiratoolkit_permissions.py:165`
  (`test_jira_add_attachment_requires_write`)

### Does NOT Exist (Anti-Hallucination)

- ~~`packages/ai-parrot/src/parrot/interfaces/jira.py`~~ — Jira is a **package**:
  `parrot/interfaces/jira/{__init__,client,errors,models,parse}.py`
- ~~`JiraInterface.add_attachment` / `get_attachment` / any attachment method~~ —
  `JiraInterface` (`interfaces/jira/client.py:101`) has **no** attachment support
  at all; every attachment call in the repo goes through the raw `jira.JIRA`
  client held by `JiraToolkit`
- ~~`async def fs_upload_file(...)`~~ — no `fs_`-prefixed methods exist in source;
  the tool names are generated from `upload_file` etc. via
  `tool_prefix = "fs"` (`filemanager.py:762`)
- ~~A session-scoped file store, a `file_id`/handle namespace, or any
  handle→path resolver~~ — nothing of the sort exists today; this feature
  introduces it
- ~~MIME detection anywhere in the Jira attachment path~~ — no `mimetypes` call
  exists in `jiratoolkit.py`; the only MIME shown to the caller is the `mimeType`
  attribute **read back** from Jira's response (`jiratoolkit.py:2073`)
- ~~A size or emptiness check before upload~~ — `jira_add_comment` checks only
  `os.path.isfile` (`jiratoolkit.py:2057`); `jira_add_attachment` checks nothing
- ~~Any docx/PDF branch in `Agent.handle_files`~~ — only `.xlsx`, `.xls`, `.csv`
  (`agent.py:404-410`)
- ~~A `.docx` entry in the Telegram crew MIME allowlist~~ — the default list
  (`integrations/telegram/crew/payload.py:36-44`) covers csv, json, txt, png,
  jpeg, pdf and parquet only. It gates the **Telegram crew** file exchange, not
  the Jira path, but it will reject docx on that channel and must be revisited
  if Telegram is a target surface

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Three natural, mostly independent lanes —
  (1) `FileManagerToolkit` session root + handle resolution, (2)
  `Agent.handle_files` persistence branch and the handler's honest response, (3)
  the unified Jira attachment helper with validation, MIME and reporting. Lane 3
  depends on lane 1's handle contract; lane 2 depends on lane 1's session-root
  API. A contract-first task that fixes the handle shape unblocks 2 and 3 to run
  in parallel.
- **Cross-feature independence**: `jiratoolkit.py` is a large, frequently touched
  file. **FEAT-637 (`jiratoolkit-template-support`) is the live conflict** — its
  proposal landed on `dev` on 2026-10-07 and it adds templating to
  `jira_create_issue` / `jira_add_comment` / issue updates, i.e. it edits
  `jira_add_comment` too. Older Jira work
  (`cross-repository-jiratoolkit-oauth2-3lo`, `jira_analyst_systemprompt_hardening`,
  `jira-extractor-llmwiki`) must also be checked before starting.
  `filemanager.py` overlaps with
  FEAT-603 (`sharepoint-filemanager`, TASK-3748..3768) and FEAT-608
  (`google-drive-interface`, TASK-3806..3819), **both committed on `dev` with no
  worktree yet** — sequencing against them is mandatory, not optional.
  `handlers/agent.py` overlaps with the AgentStudio UI/backend work.
- **Recommended isolation**: `per-spec` — one worktree, tasks sequential.
- **Rationale**: the three lanes converge on a handle contract that will be
  refined while implementing lane 1; splitting them across worktrees would force
  that contract to be frozen prematurely. The shared-file conflict risk with
  FEAT-603 / FEAT-608 on `filemanager.py` argues for a single, serializable
  branch that can be rebased once rather than several.

---

## Open Questions

- [x] Is this a feature or a hotfix, and on which base branch? — *Owner: Jesus*: `feature`, base `dev`.
- [x] Which origins must be supported? — *Owner: Jesus*: all four — server path, chat upload, remote URL, agent-generated.
- [x] Does the chat-upload → path bridge belong to this feature? — *Owner: Jesus*: yes, it is the core of the feature.
- [x] What security posture for paths and URLs? — *Owner: Jesus*: strict session sandbox; URLs must be downloaded by an explicit tool first.
- [x] How does the tool contract evolve? — *Owner: Jesus*: hard cut, one unified helper, all callers updated in-feature.
- [x] Failure semantics and pre-flight validation? — *Owner: Jesus*: best-effort with a per-file report, pre-validate size/type/emptiness, send the real Content-Type.
- [x] Where do session files live? — *Owner: Jesus*: reuse `FileManagerToolkit` (`fs`/`temp`) with a per-session root.
- [x] What reference does the Jira tool accept? — *Owner: Jesus*: an opaque session `file_id`, never a path.
- [x] Lifecycle of session files? — *Owner: Jesus*: persistent, manual cleanup.
- [ ] Which Jira deployment is the target — Cloud or Server/DC — and under which `auth_type`? The attachment size limit and the XSRF behavior differ, and the acceptance matrix needs a concrete limit to assert against. — *Owner: Jesus*
- [ ] Is the custom multipart upload (for the real Content-Type) acceptable against that deployment, or do we keep `jira.JIRA.add_attachment` and accept `application/octet-stream`? Needs one live probe before the spec freezes this acceptance criterion. — *Owner: Jesus*
- [ ] Does any client (admin UI, Teams/Telegram wrappers) parse the current `{"message", "added_files"}` upload response? If so it must be updated in the same feature — the response shape is a hard cut. — *Owner: Jesus*
- [ ] Is the Telegram crew MIME allowlist (`integrations/telegram/crew/payload.py:36-44`, no docx) in scope, or is Telegram out of the target surfaces for now? — *Owner: Jesus*
- [ ] Sequencing against FEAT-603 (`sharepoint-filemanager`) and FEAT-608 (`google-drive-interface`), both of which land on `filemanager.py` — does this feature wait, or rebase after them? — *Owner: Jesus*
- [ ] Sequencing against **FEAT-637** (`jiratoolkit-template-support`, proposal on `dev` 2026-10-07), which also modifies `jira_add_comment`: do the two features share one worktree, or does one land first? Both rewrite the same method's signature-adjacent code. — *Owner: Jesus*
- [ ] Should the per-session root be scoped by `session_id` alone, or by `(user_id, session_id)`? Multi-tenant deployments make the pair safer, but it changes the handle namespace. — *Owner: Jesus*
