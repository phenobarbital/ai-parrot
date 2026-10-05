# F002 — The success predicate already exists
- query: grep notification_succeeded / read notifications/__init__.py:295-345
- citations:
  - packages/ai-parrot/src/parrot/notifications/__init__.py:303-328 `NotificationMixin.notification_succeeded(result) -> bool` (staticmethod): True only when `result["status"] == "success"`; None = failure. Docstring states every `send_*` reports failures as `{"status": "error"}` instead of raising.
  - same file :330+ `_notification_error(exc, provider)`; returned at :440, :575, :1613, :1671, :1731, :1808.
  - same file :1521 `send_email(...) -> Dict[str, Any]`, :1742 `send_teams_card`.
  - git: 43f1989277 "restore notification_succeeded clobbered by the homologation"; 32287f3586 homologated the send_* wrappers.
- Tests exist: packages/ai-parrot/tests/notifications/test_notification_wrappers.py.
