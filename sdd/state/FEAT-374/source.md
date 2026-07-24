---
kind: inline
jira_key: null
fetched_at: 2026-07-24T13:06:23+02:00
summary_oneline: CLI console (parrot devloop) to dispatch dev-loop AgentCrew flows interactively from the terminal
---

# devloop-cli-console

Currently the flow "dev-loop" will work only for a UI with websockets. The idea
of this proposal is to build a CLI console (like `Claude Code` CLI) for invoking
a dev-loop flow via console. A rich console using a library for user interaction
in console will be very useful.

The idea:
- User can send the instruction for dispatching a dev-loop flow via the CLI.
- The CLI can use a Pydantic structured input to ask the user details about:
  - Jira ticket (if any)
  - Description or path of proposal/brainstorm to be developed
- The AgentCrew flow will be dispatched interactively in the CLI console.
- The CLI console command can be installed (like others) as `parrot devloop`.
