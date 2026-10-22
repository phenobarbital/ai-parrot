---
name: meeting-insights
description: >
  House style for turning one meeting's transcript and Fireflies summary into
  decisions, risks/blockers and action items. Use when producing or reviewing
  FirefliesInsightsAgent insights.
triggers: ["/meeting-insights"]
category: domain
version: "1.0"
---

# Meeting insights

Turn ONE meeting into three lists. Prefer fewer, sharper items over many vague ones.

## Decisions
- A decision is something the group agreed, not something one person proposed.
- State it as a fact in one line: "Ship the v2 importer on 2026-11-01".

## Risks and blockers
- Something that can delay or break a commitment, raised in the meeting.
- Name what it threatens.

## Action items
- One owner, one outcome. Copy the owner's name exactly as spoken.
- Only give a due date that was actually said; never infer one.
- Every action item quotes its evidence verbatim from the transcript.

## Never
- Invent owners, dates, numbers or decisions.
- Merge two commitments into one action item.
