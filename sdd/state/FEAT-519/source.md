---
kind: inline
jira_key: null
fetched_at: 2026-09-02T21:52:00Z
summary_oneline: Refactor the parrot CLI console (parrot agent <agent_id>) from raw stdout prints to a rich TUI stack
---

# Source (inline invocation)

Slug requested: `new-cli-infra`

Verbatim request:

> the current CLI console of parrot ("parrot agent {agent_id}") is using direct
> print to stdout but this look&feel and usability in cli console is very poor
> and cheap, idea is refactor the current cli for using a combination of `Rich`
> as output, prompt_toolkit (currently in use) with color format, etc or
> `Textual` for chat area with own scrolling + markdown widget and InquirerPy
> for confirmation, HITL and other interactions.

## Extracted intent

- **Problem**: `parrot agent <agent_id>` interactive console writes directly to
  stdout with `print()`; look & feel and usability are poor.
- **Desired direction** (candidate libraries named by requester):
  - `Rich` — styled output rendering (markdown, panels, syntax, tables).
  - `prompt_toolkit` — already in use; wants colour formatting from it.
  - `Textual` — alternative: full TUI app with a dedicated chat area that owns
    its own scrolling plus a markdown widget.
  - `InquirerPy` — confirmations, HITL prompts, and other interactions.
- **Ambiguity flagged by the source itself**: "Rich + prompt_toolkit" *or*
  "Textual" — the requester has not decided between an inline-console upgrade
  and a full-screen TUI. This is a genuine architectural fork.
