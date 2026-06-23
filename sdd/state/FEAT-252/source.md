---
kind: file
jira_key: null
fetched_at: 2026-06-23T03:51:00Z
summary_oneline: "REPL allowlist sandbox + Gemini final-response contract + deterministic secret scrubber to contain arbitrary-exec credential leakage"
file_path: sdd/proposals/brainstorm-repl-sandbox-response-contract-scrubber.md
---

# Source: brainstorm-repl-sandbox-response-contract-scrubber.md

The full brainstorm (revision 2) is tracked at
`sdd/proposals/brainstorm-repl-sandbox-response-contract-scrubber.md`. It is a
deeply-researched, verified-anchor brainstorm triggered by a production
credential-leak incident:

> A production JiraSpecialist agent (model gemini-3) running an autonomous
> "process the remaining tickets" loop called the python_repl tool, evaluated
> os.environ.keys(), and the repr of the resulting KeysView serialized the
> entire mapping WITH VALUES. That string became the tool result, fed back into
> the model context, echoed as the final answer, rendered to Telegram, and
> logged in cleartext to CloudWatch via fluent-bit.

Three stacked failures, each sufficient alone:
1. python_repl runs in-process with full os.environ; BLOCKED_IMPORTS empty,
   sanitize_input only strips markdown fences.
2. Gemini client surfaces raw tool output as the final response.
3. No deterministic redaction at any hop.

Three workstreams + a cross-cutting foundation:
- WS1: python_repl allowlist-first AST sandbox (PythonCodeSanitizer / PythonExecutionPolicy).
- WS2: Gemini tool-call -> final-response contract (_resolve_final_response chokepoint + closed tool manifest).
- WS3: deterministic OutputScrubber in the AbstractTool result seam (in-bound + egress).
- Foundation: shared compiled security primitive in core (parrot.security), reused from shell_tool.

Closed decisions (Q1, Q4, module placement, default_api manifest) and open
questions (empty-response policy, echo threshold, allowlist calibration) are
enumerated in §6 of the brainstorm.
