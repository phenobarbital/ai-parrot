# Design-research triage — jiratoolkit-docx-support

Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning_effort=high) · 12 suggestions · schema-valid.
All 13 cited paths passed repository containment and `test -e`.
Spot-checked claims S1, S3, S5 against the source — all three CONFIRMED verbatim.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make file resolution request-scoped, not mutable toolkit state (architecture) | CONFIRM | Verified: `RequestContext` + `_current_ctx: ContextVar` exist (`utils/helpers.py:53`, bound by `AbstractBot.session()`, imported at `bots/abstract.py:67`). Toolkits are reusable instances, so per-request mutation would race across sessions. | §2 Overview, §3 M2/M3 |
| S2 | Persist the handle manifest and define worker-storage requirements (risk) | CONFIRM | The server runs under gunicorn with multiple workers; an in-memory `file_id`→path map would not survive a restart nor resolve cross-worker, contradicting the "files persist" decision. | §3 M1, §7 Known Risks |
| S3 | Do not reuse the current path resolver as the security boundary (risk) | CONFIRM | Verified: `_resolve_output_path` (`filemanager.py:887`) returns any absolute path unchanged (`if Path(path).is_absolute(): return path`) — lexical, no canonicalization, no symlink handling. | §3 M1, §6 Does NOT Exist |
| S4 | Add explicit staging APIs for remote and generated files (architecture) | CONFIRM | `FileManagerToolkit` binds one backend at construction; `download_file` targets a local destination but there is no "remote source → session handle" operation. | §3 M2 |
| S5 | Persist attachments before the query-handling branch (architecture) | CONFIRM | Verified: `handlers/agent.py:1821` — `if not query: return await self._handle_attachments(...)`. A multipart request carrying a file *and* a prompt never reaches `handle_files` at all. Second, independent silent-drop path. | §3 M4, §4, §5 AC6 |
| S6 | Define the Jira size limit as deployment configuration (api) | CONFIRM | No attachment-size constant exists in the repo; Cloud and Server/DC limits differ, and the deployment is still an open question. A hard-coded 10 MB would be a guess. | §7 External Deps, §5 AC9 |
| S7 | Freeze one typed result envelope and attachment cardinality (api) | CONFIRM | The two tools currently return different shapes; "same shape" was underspecified for the singular tool. | §2 Data Models, §3 M3 |
| S8 | Specify partial-commit semantics for comments (risk) | CONFIRM | Verified: `jira_add_comment` creates the comment at `jiratoolkit.py:2049-2052` **before** uploading, so attachment failure leaves a committed comment. Pre-flighting does not make it atomic. | §3 M3, §4, §7 |
| S9 | Expand tests beyond path-based Jira mocks (testing) | CONFIRM | The six existing tests in `test_jira_comment_attachments.py` all exercise local paths; none would fail under the new contract. | §4 Test Specification |
| S10 | Bound and sanitize Jira error details returned to the model (risk) | CONFIRM | Overrides the brainstorm's "status and body surfaced verbatim" edge case: a Jira error body can be a large HTML page or carry operational detail, and it is fed straight into the model's context. | §2 Data Models, §7 |
| S11 | Add aggregate session quotas and an operator cleanup contract (risk) | ESCALATE | The runbook half is folded into §7 regardless. The enforcing half conflicts with the locked "persistent, manual cleanup" decision — whether a session quota *rejects* uploads is the user's call, not the reviewer's. | §7 + §8 Q4 |
| S12 | Resolve the MIME decision and remove contradictory acceptance criteria (alternative) | CONFIRM | Correct: the brief still carried the multipart/`aiohttp`/real-MIME language inside the Option D body after the constraint was reversed. The spec states exactly one behavior. | §1 Non-Goals, §5 |

Summary: **11** confirmed · **0** rejected · **1** escalated.
