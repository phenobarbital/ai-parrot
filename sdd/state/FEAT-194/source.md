---
kind: inline
jira_key: null
fetched_at: 2026-05-28T00:34:40Z
summary_oneline: New AgentTalk OutputMode (or Toolkit) that produces an HTML infographic artifact directly from agent response, fed by skill-defined datasets and a layout template
---

# Feature request: agentalk-infographic-mode

AgentTalk already has the capability to build infographics, but today the
flow is **two-step**:

1. The user asks a question (e.g. "Show me revenue this week").
2. The agent replies in text. The user then issues a *follow-up* asking
   for an infographic, which is built from a pre-existing template.

We want a **new dedicated OutputMode** (or possibly a Toolkit) where the
infographic — an HTML artifact with potential JavaScript interaction —
**is itself the agent's primary response**, eliminating the two-step
question → follow-up → infographic dance.

The process is non-trivial because it crosses several concerns:

- If the LLM has produced several datasets/data items in service of the
  answer, those must be **retained and available** so the infographic
  can consume them.
- The infographic layout must be **declared up-front** by something the
  agent can plan against (probably a Skill).

## Use case (illustrated by attached image, not pastable here)

A finance-style dashboard with this layout:

```
---
Card: revenue total | Card: revenue change previous week | Card: EBITDA total | Card: Total EBITDA Day-over-Day
---
Bar Chart: Daily Total Revenue with day-over-day change | Bar Chart: Daily Total EBITDA with day-over-day change
---
Cumulative Total Revenue by day
```

4 hero cards on top, 2 charts in the middle, 1 chart at the bottom.

## What we need

A Skill in ai-parrot (the user notes that ai-parrot is the project here
but cannot be added as a project in their UI — irrelevant aside) that:

1. **Instructs the LLM** to generate a set of queries to fetch the
   underlying data (revenue per day, EBITDA per day, etc.).
2. **Passes those datasets** to a piece of functionality that, based on
   a pre-existing template, **fills in the gaps** of the infographic
   with the charts the skill requested.

The Skill basically describes to the LLM *where each datum comes from*
and **must return them** (the datasets must be exposed back upstream).

## The open architectural question

The user is unsure how this HTML-artifact generator (which can become a
full interactive application asked of the LLM) should be modeled:

- **Option A — A new `OutputMode`**: infographic becomes a first-class
  output type alongside whatever modes exist today (text, JSON, etc.).
- **Option B — A Toolkit**: receives N datasets and invokes the
  existing infographic system to materialize the layout the skill
  described.
- **Option C — The skill names a pre-existing template**: same way the
  current `Infographic` capability already works, just routed through
  the skill so the user doesn't have to ask twice.

This is the central design question this proposal must illuminate.
