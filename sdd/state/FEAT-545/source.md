---
kind: inline
jira_key: null
fetched_at: 2026-09-10T00:00:00+00:00
summary_oneline: Make /sdd-spec emit executor-ready code+explanations and add a Codex collaborative design-research pass before spec creation
---

# Source (inline, verbatim)

> collaborative-adversarial-spec-design -- current "sdd-spec" command is using
> for converting a brainstorm or proposal into a full featured spec-driven
> development document, but because we are using thinking models for spec
> design but non-thinking models (as haiku) to take the "orders" and write the
> decided code into the expected files, I'm proposing here two changes over the
> "sdd-spec" command:
>
> 1. requesting to the thinking model (fable, Opus) to add more usable code +
>    explanations on spec (and over each "TASK-" file created) to reduced the
>    effort of non-thinking models during the execution of each task.
>
> 2. collaborative improvement-research: exactly like Adversarial Code Review we
>    implemented on code-reviewer (using Codex), using Codex (but a thinking
>    model like gpt 5.6-luna), Codex will receive the "accepted" proposal
>    definition and will suggest ideas how to do the job, those proposed ideas
>    will be incorporated during "spec creation" to enrich the ideas.
