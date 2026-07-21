---
type: Concept
title: handle_msteams_jira_callback()
id: func:parrot.integrations.msteams.oauth_callback.handle_msteams_jira_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Process a Jira OAuth callback originating from the MS Teams integration.
---

# handle_msteams_jira_callback

```python
async def handle_msteams_jira_callback(request: 'web.Request', token_set: Optional['JiraTokenSet'], state_payload: Dict[str, Any]) -> 'web.Response'
```

Process a Jira OAuth callback originating from the MS Teams integration.

Responsibilities:
1. Return an HTML error page when Atlassian reports a consent denial
   (``?error=`` query param is present), and optionally send a proactive
   Teams message to the user.
2. Write an ``auth.user_identities`` row (if
   ``identity_mapping_service`` is available on the app).
3. Fire a proactive Teams notification via
   ``app["msteams_jira_oauth_notifier"]`` (fire-and-forget).
4. Return an HTML success page that instructs the user to return to Teams.

Args:
    request: The incoming aiohttp request.
    token_set: Token and identity data from ``JiraOAuthManager.handle_callback``,
        or ``None`` when invoked on the consent-denial (``?error=``) path.
    state_payload: Full state payload (``channel``, ``user_id``, ``extra``)
        decoded from the CSRF nonce.

Returns:
    HTML :class:`aiohttp.web.Response` for the browser.
