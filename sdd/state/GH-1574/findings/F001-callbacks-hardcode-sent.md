# F001 — Delivery callbacks hard-code success
- query: grep send_email_report / read scheduler/functions/__init__.py
- citations:
  - packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py:68-92 `SendEmailReportCallback.run` awaits `self.send_email(...)` then returns `{"status": "sent", ...}` unconditionally; the provider response is only nested under `"response"`.
  - same file :168-192 `SendNotifyReportCallback.run` — identical pattern around `self.send_notification(...)`.
  - same file :145-153 `SaveDataCallback.run` — stores the email response under `response["email"]` with top-level `status: "saved"`; email failure invisible.
  - same file :16-65 `BaseSchedulerCallback(NotificationMixin)` — callbacks inherit `notification_succeeded`.
- Consequence: a provider failure (`{"status": "error", ...}`) is reported as "sent".
