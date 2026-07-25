---
kind: inline
jira_key: null
fetched_at: 2026-07-26T00:53:14+02:00
summary_oneline: Add OpenAI codex CLI as an invocable sub-agent in parrot.flows.devloop for dev tasks and adversarial code review
---

# codex-cli-agent

On `parrot.flows.devloop` add the ability to use the `codex` CLI command
(example usage: `codex exec --skip-git-repo-check "Reply with OK"`,
reference: https://learn.chatgpt.com/docs/codex/cli) as a sub-agent that can
be invoked to run some development tasks or even adversarial code review
(reference: https://learn.chatgpt.com/docs/developer-commands?surface=cli).

Example markdown text for using "codex" as an adversarial code reviewer:

## Codex — second-opinion agent (all projects)

The OpenAI `codex` CLI is installed and authed. Use it as an independent perspective:
adversarial reviews, design opinions, brainstorming, research cross-checks. Rules:

- **Never feed it your reasoning or justification** — give it the diff, the requirement,
  and the question only. Feeding your conclusions produces ratification, not review.
- Treat output as advisory: CONFIRM (adopt), REJECT (say why), or escalate.
  Never silently concede, never silently drop a finding.
- **Reviews**: `codex exec review --uncommitted` (or `--base dev`, `--commit <sha>`).
- **Opinions / brainstorm**: `codex exec --sandbox read-only -o <scratch-file> "<brief>"`
  then read the `-o` file (stdout carries progress noise).
- **Follow-ups**: `codex exec resume --last "<question>"` continues the session.
- **Image generation** (mockups, wireframes): built-in `image_gen` tool (gpt-image-2).
  Needs a writable sandbox:
  `codex exec --sandbox workspace-write -o <out.txt> "Generate an image: <description>. Save as <name>.png"`
  Attach references with `-i <screenshot.png>`. Gotcha: `resume` does NOT accept
  `--sandbox`; pass `-c sandbox_mode="workspace-write"` instead.
- Each call is a full agent session (30s–2min): run it **in the background**;
  never call it per-edit or from hooks.
- **Parallel perspective**: one Claude subagent + one background `codex exec` with the
  same neutral brief, then synthesize agreements and disagreements.
