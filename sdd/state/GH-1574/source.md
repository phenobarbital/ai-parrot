---
kind: github_issue
github_issue: phenobarbital/ai-parrot#1574
fetched_at: 2026-10-05
summary_oneline: "notifications: send_email_report reports success when sending failed"
---
`NotificationMixin.send_email` and `send_teams_card` never raise; they return a status dict. `send_email_report` (`scheduler/functions`) ignores that status and reports "sent" even when the provider failed. Callback results and errors are also only logged or discarded (`manager.py`, around the callback execution), so callers can't tell a delivery failed.

**Suggested fix:** check `notification_succeeded` (or equivalent) and propagate failure; persist callback outcomes.

Related: the repo `.venv` had async-notify 1.6.0 while `uv.lock` pins 2.0.0.

_Found while integrating ai-parrot-server's scheduler and ai-parrot-visualizations' A2UI renderers into an external package (reportbuilder). Versions: ai-parrot 0.18.9, ai-parrot-server 0.27.1, ai-parrot-visualizations 1.0.7, apscheduler 3.11.2._
