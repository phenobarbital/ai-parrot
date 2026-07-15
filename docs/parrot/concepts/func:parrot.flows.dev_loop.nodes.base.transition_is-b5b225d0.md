---
type: Concept
title: transition_issue_with_candidates()
id: func:parrot.flows.dev_loop.nodes.base.transition_issue_with_candidates
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Apply the first candidate Jira transition that the workflow exposes.
---

# transition_issue_with_candidates

```python
async def transition_issue_with_candidates(jira: Any, issue: str, candidates: Sequence[str], *, logger: logging.Logger, **kwargs: Any) -> Optional[Dict[str, Any]]
```

Apply the first candidate Jira transition that the workflow exposes.

The dev-loop drives many Jira projects, each with its own workflow
transition names — a single hard-coded label (e.g. ``"Ready to Deploy"``)
only exists in one of them. Callers therefore pass an *ordered* list of
synonym labels (most specific first). Each is handed to
``jira_transition_to``, which walks the project's declared workflow path
(``JIRA_WORKFLOW_PATH`` / ``JIRA_WORKFLOW_PATH_<PROJECT>``) hop-by-hop when
the target status is several transitions away, and otherwise falls back to
a single direct transition. The first label that resolves is applied and
its result returned.

A non-matching label raises ``ValueError`` inside the toolkit (it lists the
available transitions) — that is treated as "try the next candidate", not a
failure. Any other exception (network/auth) propagates so the caller's own
error handling sees it. Returns ``None`` when no candidate matched, leaving
the decision of whether that is fatal to the caller.

Args:
    jira: A ``JiraToolkit`` instance.
    issue: Issue key (e.g. ``"NAV-6239"``).
    candidates: Ordered transition-label synonyms; empties are skipped.
    logger: Logger for diagnostics.
    **kwargs: Forwarded to ``jira_transition_issue`` (``fields``,
        ``resolution``, ``assignee`` …).

Returns:
    The toolkit's ``jira_transition_issue`` result on success, else
    ``None``.
