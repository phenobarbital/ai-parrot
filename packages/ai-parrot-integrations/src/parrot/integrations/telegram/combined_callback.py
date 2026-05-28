"""Combined BasicAuth + secondary OAuth callback for the Telegram WebApp.

After the login page completes BasicAuth and redirects the user to a
secondary OAuth provider (Jira in the current feature scope), the provider
redirects the browser back here. This endpoint returns HTML that packages
the ``code`` / ``state`` into a ``WebApp.sendData`` payload keyed under the
provider name (``jira`` by default) so ``TelegramAgentWrapper.
handle_web_app_data`` can detect the combined flow.

The BasicAuth result itself is carried across the Jira redirect via the
``extra_state`` parameter of ``JiraOAuthManager.create_authorization_url``
(stored alongside the CSRF nonce in Redis). This handler does NOT look up
or consume the nonce; it simply forwards ``code`` + ``state`` to the
wrapper, which has the Redis client and will resolve it there.
"""
from __future__ import annotations

import html as html_mod

from aiohttp import web
from navconfig.logging import logging

from parrot.integrations.telegram.oauth2_callback import (
    _ERROR_HTML_TEMPLATE,
    _json_escape,
)

logger = logging.getLogger(__name__)

COMBINED_CALLBACK_PATH = "/api/auth/telegram/combined-callback"

# HTML template mirrors `_SUCCESS_HTML_TEMPLATE` from oauth2_callback.py but
# sends a payload shaped as `{<provider>: {code, state}}` so the wrapper
# can route the result to the appropriate PostAuthProvider.
_COMBINED_SUCCESS_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Authentication Complete</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      margin: 0;
      background: #f5f5f5;
      color: #333;
    }}
    .container {{ text-align: center; padding: 2rem; }}
    .spinner {{
      border: 3px solid #e0e0e0;
      border-top: 3px solid #2481cc;
      border-radius: 50%;
      width: 40px;
      height: 40px;
      animation: spin 1s linear infinite;
      margin: 1rem auto;
    }}
    @keyframes spin {{
      0% {{ transform: rotate(0deg); }}
      100% {{ transform: rotate(360deg); }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="spinner"></div>
    <p>Authentication complete. Returning to Telegram...</p>
  </div>
  <script>
    try {{
      const provider = {provider_json};
      const payload = {{}};
      payload[provider] = {{
        code: {code_json},
        state: {state_json}
      }};
      if (window.Telegram && Telegram.WebApp) {{
        Telegram.WebApp.sendData(JSON.stringify(payload));
        setTimeout(function() {{ Telegram.WebApp.close(); }}, 500);
      }}
    }} catch (e) {{
      document.querySelector('.container').innerHTML =
        '<p>Error: ' + e.message + '</p>';
    }}
  </script>
</body>
</html>"""


async def combined_auth_callback_handler(
    request: web.Request,
) -> web.Response:
    """Handle the combined BasicAuth + secondary OAuth redirect.

    Query parameters:
        code: Authorization code from the OAuth provider (required on success).
        state: CSRF nonce echoed back by the provider (required on success).
        provider: Name of the secondary provider (defaults to ``"jira"``).
        error, error_description: Present if the user denied consent.

    Returns:
        HTML response. Success path returns 200 with a page that calls
        ``Telegram.WebApp.sendData`` and closes the WebApp. Missing
        parameters return 400; provider-reported errors return 200 with
        an error page (so the WebApp closes cleanly).
    """
    provider = request.query.get("provider", "jira")

    error = request.query.get("error")
    if error:
        error_desc = request.query.get("error_description", error)
        logger.warning(
            "Combined auth callback error: %s — %s", error, error_desc
        )
        safe_desc = html_mod.escape(error_desc)
        return web.Response(
            text=_ERROR_HTML_TEMPLATE.format(
                error_message=(
                    f"Authentication failed: {safe_desc}"
                )
            ),
            content_type="text/html",
            status=200,
        )

    code = request.query.get("code")
    state = request.query.get("state")

    if not code:
        logger.warning("Combined auth callback missing 'code' parameter")
        return web.Response(
            text=_ERROR_HTML_TEMPLATE.format(
                error_message=(
                    "Authentication failed: missing authorization code."
                )
            ),
            content_type="text/html",
            status=400,
        )

    if not state:
        logger.warning("Combined auth callback missing 'state' parameter")
        return web.Response(
            text=_ERROR_HTML_TEMPLATE.format(
                error_message=(
                    "Authentication failed: missing state parameter."
                )
            ),
            content_type="text/html",
            status=400,
        )

    state_log = state[:8] if len(state) > 8 else state
    logger.info(
        "Combined auth callback received provider=%s state=%s...",
        provider,
        state_log,
    )

    html_text = _COMBINED_SUCCESS_HTML_TEMPLATE.format(
        provider_json=_json_escape(provider),
        code_json=_json_escape(code),
        state_json=_json_escape(state),
    )
    return web.Response(
        text=html_text, content_type="text/html", status=200
    )


def setup_combined_auth_routes(
    app: web.Application,
    path: str = COMBINED_CALLBACK_PATH,
) -> None:
    """Register the combined callback route and exclude it from auth.

    Args:
        app: The aiohttp application instance.
        path: URL path for the combined callback endpoint.
    """
    app.router.add_get(path, combined_auth_callback_handler)
    logger.info("Registered combined auth callback at %s", path)

    # Ensure the route is not subjected to navigator-auth middleware —
    # it handles pre-authentication data for the WebApp.
    try:  # pragma: no cover - navigator_auth is optional in tests
        from navigator_auth.conf import exclude_list  # type: ignore

        if path not in exclude_list:
            exclude_list.append(path)
    except ImportError:
        pass
