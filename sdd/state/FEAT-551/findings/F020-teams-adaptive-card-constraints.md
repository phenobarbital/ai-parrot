---
id: F020
query_id: Q022
type: web
intent: External check: Teams Adaptive Card file/image upload support
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F020 — Microsoft Teams docs — Adaptive Card constraints (no uploads, v1.6 max, styling)

## Summary
Microsoft Learn "Create & Explore Card Types in Teams" (cards-reference, updated 2026-08-19) states verbatim: "Adaptive Cards within Teams don't provide support for file or image uploads." Also: Teams supports "v1.6 or earlier" of Adaptive Cards; "Positive or destructive action styling is not supported in Adaptive Cards on the Teams platform"; `isEnabled` on `Action.Submit` unsupported; for Incoming Webhooks "all native Adaptive Card schema elements, except Action.Submit, are fully supported" (OpenUrl/ShowCard/ToggleVisibility/Execute only). Inline card images must be public HTTPS ≤1024×1024 PNG/JPEG/GIF. The `HttpPOST`-style action exists only for the Microsoft 365 Groups connector card, where in a bot it "triggers an invoke activity" — i.e. still bot-mediated.

## Citations
- url: https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-reference
  section: "Support for Adaptive Cards" notes
  excerpt: |
    Teams platform supports v1.6 or earlier of Adaptive Card features for bot sent cards ...
    Positive or destructive action styling is not supported in Adaptive Cards on the Teams platform.
    Adaptive Cards within Teams don't provide support for file or image uploads.
    The `isEnabled` property for `Action.Submit` type in an Adaptive Card isn't supported in Teams.
- url: same
  section: "Features that support different card types" note
  excerpt: |
    For Adaptive Cards in Incoming Webhooks, all native Adaptive Card schema elements, except Action.Submit, are fully supported.
- url: same
  section: "Connector card for Microsoft 365 Groups"
  excerpt: |
    Connector: The endpoint receives the card payload through HTTP POST. | Bot: The HttpPOST action triggers an invoke activity that sends only the action ID and body to the bot.

## Notes
The WebSearch tool failed (model access error); this single primary-source fetch is the external evidence. It directly answers the "can we upload pictures" question: not inside the card.
