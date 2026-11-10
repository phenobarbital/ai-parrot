"""OAuth2 callback endpoint for Telegram WebApp authentication.

Handles the OAuth2 provider redirect after user authentication.
Captures the authorization code and state, then returns an HTML page
that passes the data back to Telegram via WebApp.sendData().
"""

import html as html_mod

from aiohttp import web
from navconfig.logging import logging
from parrot.integrations.telegram.browser_login import (
    BROWSER_LOGIN_APP_KEY,
    TELEGRAM_WRAPPERS_APP_KEY,
    BrowserVerificationError,
    BrowserVerifierUnavailableError,
    is_browser_state,
    render_browser_error,
    render_browser_success,
)

logger = logging.getLogger(__name__)

_SUCCESS_HTML_TEMPLATE = """\
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
    .container {{
      text-align: center;
      padding: 2rem;
    }}
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
  <!-- Auth data passed via HTML-escaped data attribute, parsed in JS -->
  <div id="auth-data" class="container"
       data-provider="{provider_attr}"
       data-code="{code_attr}"
       data-state="{state_attr}">
    <div class="spinner"></div>
    <p>Authentication complete. Returning to Telegram...</p>
  </div>
  <script>
    try {{
      var el = document.getElementById('auth-data');
      var data = {{
        provider: el.getAttribute('data-provider'),
        code: el.getAttribute('data-code'),
        state: el.getAttribute('data-state')
      }};
      if (window.Telegram && Telegram.WebApp) {{
        Telegram.WebApp.sendData(JSON.stringify(data));
        setTimeout(function() {{ Telegram.WebApp.close(); }}, 500);
      }}
    }} catch (e) {{
      document.querySelector('.container').innerHTML =
        '<p>Error: ' + e.message + '</p>';
    }}
  </script>
</body>
</html>"""

_ERROR_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Authentication Error</title>
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
      color: #c0392b;
    }}
    .container {{ text-align: center; padding: 2rem; }}
  </style>
</head>
<body>
  <div class="container">
    <p>{error_message}</p>
    <p><small>Please close this window and try again.</small></p>
  </div>
  <script>
    if (window.Telegram && Telegram.WebApp) {{
      setTimeout(function() {{ Telegram.WebApp.close(); }}, 3000);
    }}
  </script>
</body>
</html>"""


def _json_escape(value: str) -> str:
    """Escape a string for safe embedding in a JS template.

    Args:
        value: Raw string value.

    Returns:
        JSON-safe quoted string.
    """
    import json as json_mod
    # Replace HTML-special chars with unicode escapes to prevent XSS.
    # Order matters: replace < and > first (they won't produce &), then &.
    return (
        json_mod.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _browser_html(page: str, status: int) -> web.Response:
    """Return a browser-mode HTML response with the requested status."""
    return web.Response(text=page, content_type="text/html", status=status)


async def _browser_oauth2_callback(request: web.Request, state: str) -> web.Response:
    """Complete a browser-mode OAuth2 login server-side (FEAT-854). No sendData involved."""
    registry = request.app.get(BROWSER_LOGIN_APP_KEY)
    entry = registry.consume(state) if registry is not None else None
    if entry is None:
        logger.warning("Browser OAuth2 callback with unknown or expired state %s...", state[:8])
        return _browser_html(
            render_browser_error(
                "This sign-in link has expired or was already used. Send /login in Telegram to start again."
            ),
            410,
        )

    code = request.query.get("code")
    if request.query.get("error") or not code:
        logger.warning("Browser OAuth2 callback without a code (provider error or cancel)")
        return _browser_html(
            render_browser_error("Sign-in was cancelled or failed. Send /login in Telegram to try again."),
            400,
        )

    wrappers = request.app.get(TELEGRAM_WRAPPERS_APP_KEY, {})
    wrapper = wrappers.get(entry.bot_id)
    if wrapper is None:
        logger.warning("Browser OAuth2 callback has no wrapper for bot %s", entry.bot_id)
        return _browser_html(
            render_browser_error("The bot is temporarily unavailable. Please try again later."),
            503,
        )

    try:
        completed = await wrapper._complete_auth_payload(
            {"auth_method": "oauth2", "code": code, "state": state},
            telegram_id=entry.telegram_id,
            chat_id=entry.chat_id,
            browser_entry=entry,
        )
    except BrowserVerificationError:
        logger.warning("Browser OAuth2 callback failed identity verification")
        return _browser_html(
            render_browser_error("Sign-in could not be verified. Send /login in Telegram to try again."),
            401,
        )
    except BrowserVerifierUnavailableError:
        logger.warning("Browser OAuth2 callback verifier is unavailable")
        return _browser_html(
            render_browser_error("The bot is temporarily unavailable. Please try again later."),
            503,
        )

    if not completed:
        return _browser_html(
            render_browser_error("Sign-in could not be verified. Send /login in Telegram to try again."),
            401,
        )

    session = wrapper._user_sessions.get(entry.telegram_id)
    display_name = session.display_name if session is not None and session.authenticated else ""
    return _browser_html(render_browser_success(entry.bot_username, display_name), 200)


async def oauth2_callback_handler(request: web.Request) -> web.Response:
    """Handle OAuth2 provider redirect with authorization code.

    Extracts ``code`` and ``state`` from query parameters and returns
    an HTML page that passes them back to Telegram via WebApp.sendData().
    Browser-namespace states complete server-side; all other states retain the legacy page.

    Args:
        request: The aiohttp request from the OAuth2 provider redirect.

    Returns:
        HTML response with Telegram WebApp integration script.
    """
    # FEAT-854: route by the browser-state namespace BEFORE any legacy rendering.
    browser_state = request.query.get("state")
    if is_browser_state(browser_state):
        return await _browser_oauth2_callback(request, browser_state)

    code = request.query.get("code")
    state = request.query.get("state")
    provider = request.query.get("provider", "google")

    # Check for OAuth2 error response from provider
    error = request.query.get("error")
    if error:
        error_desc = request.query.get("error_description", error)
        logger.warning("OAuth2 callback error: %s — %s", error, error_desc)
        safe_desc = html_mod.escape(error_desc)
        html = _ERROR_HTML_TEMPLATE.format(
            error_message=f"Authentication failed: {safe_desc}"
        )
        return web.Response(text=html, content_type="text/html", status=200)

    if not code:
        logger.warning("OAuth2 callback missing 'code' parameter")
        html = _ERROR_HTML_TEMPLATE.format(
            error_message="Authentication failed: missing authorization code."
        )
        return web.Response(text=html, content_type="text/html", status=400)

    if not state:
        logger.warning("OAuth2 callback missing 'state' parameter")
        html = _ERROR_HTML_TEMPLATE.format(
            error_message="Authentication failed: missing state parameter."
        )
        return web.Response(text=html, content_type="text/html", status=400)

    logger.info(
        "OAuth2 callback received for provider=%s, state=%s...",
        provider,
        state[:8] if len(state) > 8 else state,
    )

    # Sanitize user-provided values via html.escape for safe embedding
    # in HTML data-attributes (prevents XSS).
    html = _SUCCESS_HTML_TEMPLATE.format(
        provider_attr=html_mod.escape(provider, quote=True),
        code_attr=html_mod.escape(code, quote=True),
        state_attr=html_mod.escape(state, quote=True),
    )
    return web.Response(text=html, content_type="text/html", status=200)


def setup_oauth2_routes(
    app: web.Application,
    path: str = "/oauth2/callback",
) -> None:
    """Register OAuth2 callback route on the aiohttp application.

    Args:
        app: The aiohttp application instance.
        path: URL path for the callback endpoint.
    """
    app.router.add_get(path, oauth2_callback_handler)
    logger.info("Registered OAuth2 callback endpoint at %s", path)
