"""OAuth2 callback endpoint for Telegram WebApp authentication.

Handles the OAuth2 provider redirect after user authentication.
Captures the authorization code and state, then returns an HTML page
that passes the data back to Telegram via WebApp.sendData().
"""

import html as html_mod

from aiohttp import web
from navconfig.logging import logging

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
  <div class="container">
    <div class="spinner"></div>
    <p>Authentication complete. Returning to Telegram...</p>
  </div>
  <script>
    try {{
      const data = {{
        provider: {provider_json},
        code: {code_json},
        state: {state_json}
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


async def oauth2_callback_handler(request: web.Request) -> web.Response:
    """Handle OAuth2 provider redirect with authorization code.

    Extracts ``code`` and ``state`` from query parameters and returns
    an HTML page that passes them back to Telegram via WebApp.sendData().

    Args:
        request: The aiohttp request from the OAuth2 provider redirect.

    Returns:
        HTML response with Telegram WebApp integration script.
    """
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

    html = _SUCCESS_HTML_TEMPLATE.format(
        provider_json=_json_escape(provider),
        code_json=_json_escape(code),
        state_json=_json_escape(state),
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
