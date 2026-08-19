# F003 — Adaptive Card support already exists end-to-end

**Query:** Q005 (grep + direct read)
**Citations:** `packages/ai-parrot/src/parrot/notifications/__init__.py`
  :: `NotificationMixin.build_teams_card` (L100-156), `send_teams_card` (L1101+),
     `_is_teams_card` (L76-97), `_teams_card_attach_files` (L874), `_send_teams` (L777)
**Confidence:** high (direct source read)

## Verdict on brainstorm claim §3.2 / rev2 #8

**CONFIRMED, and the gap is even narrower than stated.** The brainstorm says
"extending the callback to feed a rendered Adaptive Card to NotificationMixin is the
actual work". In fact NotificationMixin already ships the full card toolchain:

- `build_teams_card(title, text, *, summary, sections, actions, files, version="1.5")`
  → returns a `TeamsCard`; `actions` take `CardAction` dicts including
  `{"type": "Action.OpenUrl", "title": ..., "url": ...}`
- `send_teams_card(card, recipient, report=None)` → delegates to `send_notification`
  with `provider=NotificationProvider.TEAMS`
- `_is_teams_card()` detects `TeamsCard`, `{"type": "AdaptiveCard"}`,
  `{"@type": "MessageCard"}`, `contentType: application/vnd.microsoft.card.adaptive`,
  and JSON strings — so `send_notification(message=<card>)` auto-routes cards
- Rendering handled downstream by async-notify's Teams provider via
  `TeamsCard.to_adaptative()`

The method docstring's own example is almost verbatim the SPEC-A payload
(title + text + `Action.OpenUrl` to a dashboard URL).

## Consequence for the build delta

Brainstorm §4.2 item 3 ("card-aware callback extension") shrinks to: a new
`SendDashboardCardCallback` (or a `card:` branch) that calls the **existing**
`build_teams_card` with Jinja-rendered `title`/`text` and one `Action.OpenUrl`
carrying the share URL. No card model, no renderer, no schema work.

`TeamsCard`/`CardAction` are imported from async-notify (`notify.models`), so the
card vocabulary is shared with Flowtask's `SendNotify` — consistent with
brainstorm §3.2's "one substrate, two entry points".
