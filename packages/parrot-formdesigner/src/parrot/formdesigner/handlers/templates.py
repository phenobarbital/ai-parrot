"""HTML page templates and CSS for parrot-formdesigner HTTP handlers.

All template builders accept an optional ``prefix`` argument (default
``""``). When the form-designer routes are mounted behind a URL prefix via
``setup_form_routes(app, prefix="/form")``, callers resolve the prefix
with ``request.app.get("_form_prefix", "")`` and pass it through so that
every rendered link and JS ``fetch()`` target matches the real route.

Extracted from examples/forms/form_server.py.
"""

from html import escape

CSS = """\
    :root {
      --bg: #f8f9fa; --surface: #fff; --text: #1a1a2e;
      --primary: #0066cc; --primary-hover: #0055aa;
      --border: #ddd; --muted: #666; --error: #c00;
      --success-bg: #e6ffe6; --success-border: #090;
      --radius: 6px;
    }
    *, *::before, *::after { box-sizing: border-box; }
    body {
      font-family: system-ui, -apple-system, sans-serif;
      max-width: 680px; margin: 0 auto; padding: 2rem 1rem;
      background: var(--bg); color: var(--text); line-height: 1.5;
    }
    h1, h2 { margin-top: 0; }
    a { color: var(--primary); }
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1.5rem; margin-bottom: 1.5rem;
    }
    .prompt-area {
      width: 100%; min-height: 100px; padding: .75rem;
      border: 1px solid var(--border); border-radius: var(--radius);
      font: inherit; resize: vertical;
    }
    .prompt-area:focus { outline: 2px solid var(--primary); border-color: transparent; }
    .db-inputs { display: flex; gap: 1rem; margin: .75rem 0 1rem; }
    .db-inputs label { flex: 1; display: flex; flex-direction: column; gap: .3rem;
                       font-weight: 600; font-size: .95rem; }
    .db-inputs input[type=number] { width: 100%; padding: .55rem;
      border: 1px solid var(--border); border-radius: var(--radius); font: inherit; }
    .btn {
      display: inline-flex; align-items: center; gap: .4rem;
      padding: .65rem 1.4rem; border: none; border-radius: var(--radius);
      font: inherit; font-size: .95rem; cursor: pointer;
      transition: background .15s, opacity .15s;
    }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-secondary { background: var(--border); color: var(--text); }
    .btn:disabled { opacity: .55; cursor: not-allowed; }
    .spinner {
      display: inline-block; width: 1em; height: 1em;
      border: 2px solid rgba(255,255,255,.3); border-top-color: #fff;
      border-radius: 50%; animation: spin .6s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .form-field { margin-bottom: 1rem; }
    .form-field label { display: block; font-weight: 600; margin-bottom: .25rem; }
    .form-field__help { display: block; font-size: .85rem; color: var(--muted); margin-bottom: .25rem; }
    .form-field__error { display: block; color: var(--error); font-size: .85rem; margin-top: .25rem; }
    input, select, textarea {
      width: 100%; padding: .55rem; border: 1px solid var(--border);
      border-radius: var(--radius); font: inherit;
    }
    input:focus, select:focus, textarea:focus { outline: 2px solid var(--primary); border-color: transparent; }
    textarea { min-height: 100px; }
    .form-actions { margin-top: 1.25rem; display: flex; gap: .75rem; }
    .form-list { list-style: none; padding: 0; margin: 1rem 0 0; }
    .form-list li {
      padding: .5rem 0; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center;
    }
    .form-list li:last-child { border-bottom: none; }
    .success {
      background: var(--success-bg); border: 1px solid var(--success-border);
      padding: 1rem; border-radius: var(--radius); margin-bottom: 1rem;
    }
    .error-banner {
      background: #ffe6e6; border: 1px solid var(--error);
      padding: .75rem 1rem; border-radius: var(--radius); margin-bottom: 1rem;
      color: var(--error);
    }
    pre {
      background: #f4f4f4; padding: 1rem; border-radius: var(--radius);
      overflow-x: auto; font-size: .85rem;
    }
    .nav { margin-bottom: 1.5rem; font-size: .9rem; }
    .nav a { margin-right: 1rem; }
    .examples { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .75rem; }
    .example-chip {
      padding: .3rem .7rem; background: #eef; border: 1px solid #cce;
      border-radius: 1rem; font-size: .82rem; cursor: pointer;
      transition: background .15s;
    }
    .example-chip:hover { background: #ddf; }
    .section-divider {
      display: flex; align-items: center; gap: .75rem;
      color: var(--muted); font-size: .85rem; margin: .5rem 0 1.5rem;
    }
    .section-divider::before, .section-divider::after {
      content: ''; flex: 1; border-top: 1px solid var(--border);
    }
"""


def _normalize_prefix(prefix: str) -> str:
    """Normalise a URL prefix to the ``""`` or ``"/foo"`` shape.

    The route registrar stores the prefix stripped of trailing slashes
    (see ``routes.py``). This mirrors that behaviour so the templates
    produce ``{prefix}/...`` without double slashes at runtime.

    Args:
        prefix: Raw prefix from ``request.app.get("_form_prefix", "")``.

    Returns:
        Either the empty string or a string that starts with ``/`` and
        has no trailing ``/``.
    """
    if not prefix:
        return ""
    return "/" + prefix.strip("/")


def _auth_script(prefix: str = "") -> str:
    """Build the JWT auth bootstrap ``<script>`` for the admin page shell.

    The script:
    * Reads ``ai_parrot_token`` from ``localStorage`` and redirects to
      ``/admin`` when missing (admin login is served by the host app,
      conventionally at the site root — not under the form prefix).
    * Monkey-patches ``window.fetch`` so that any same-origin URL
      starting with ``{prefix}/api/`` (or plain ``/api/`` when no prefix
      is set) is auto-decorated with ``Authorization: Bearer <token>``.
    * Handles 401 responses by clearing the stored session and
      redirecting to ``/admin``.

    Args:
        prefix: URL prefix where the form-designer routes are mounted
            (e.g. ``"/form"``). Empty string preserves legacy behaviour.

    Returns:
        HTML string containing the ``<script>`` element.
    """
    p = _normalize_prefix(prefix)
    api_match = f"'{p}/api/'" if p else "'/api/'"
    return f"""\
<script>
(function() {{
  // Redirect to login if no JWT token is stored.
  var token = localStorage.getItem('ai_parrot_token');
  if (!token) {{
    window.location.href = '/admin';
    return;
  }}

  // Monkey-patch fetch to inject Authorization header on same-origin API calls.
  var _origFetch = window.fetch;
  window.fetch = function(input, init) {{
    init = init || {{}};
    var url = (typeof input === 'string') ? input : input.url;
    if (url.startsWith({api_match})) {{
      init.headers = new Headers(init.headers || {{}});
      if (!init.headers.has('Authorization')) {{
        init.headers.set('Authorization', 'Bearer ' + token);
      }}
    }}
    return _origFetch.call(this, input, init).then(function(resp) {{
      if (resp.status === 401) {{
        localStorage.removeItem('ai_parrot_token');
        localStorage.removeItem('ai_parrot_session');
        window.location.href = '/admin';
      }}
      return resp;
    }});
  }};
}})();
</script>"""


def page_shell(
    title: str,
    body: str,
    locale: str = "en",
    nav: bool = True,
    prefix: str = "",
) -> str:
    """Wrap body HTML in a full page shell.

    Injects an authentication script that reads the JWT from localStorage
    and attaches it as an ``Authorization: Bearer`` header on every
    ``fetch()`` call targeting the form-designer API. If no token is
    present the user is redirected to ``/admin``.

    Args:
        title: Page title shown in the browser tab.
        body: Inner HTML content.
        locale: HTML lang attribute value.
        nav: Whether to include the top navigation links.
        prefix: URL prefix where the form-designer is mounted. Empty
            string = legacy behaviour (routes at root).

    Returns:
        Complete HTML page string.
    """
    p = _normalize_prefix(prefix)
    nav_html = ""
    if nav:
        nav_html = (
            f'<div class="nav">'
            f'<a href="{p}/">New Form</a>'
            f'<a href="{p}/gallery">Gallery</a>'
            f'</div>'
        )
    return f"""\
<!DOCTYPE html>
<html lang="{escape(locale)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - AI Form Builder</title>
  <style>{CSS}</style>
</head>
<body>
  {_auth_script(p)}
  {nav_html}
  {body}
</body>
</html>"""


def index_page(prefix: str = "") -> str:
    """Return the HTML body for the index page (prompt builder + DB loader).

    The embedded JavaScript declares a ``FORM_PREFIX`` constant so all
    ``fetch()`` calls and ``window.location.href`` redirects respect the
    mount point configured via ``setup_form_routes(..., prefix=...)``.

    Args:
        prefix: URL prefix where the form-designer is mounted.

    Returns:
        HTML body string for the landing page.
    """
    p = _normalize_prefix(prefix)
    return f"""\
<h1>AI Form Builder</h1>
<p>Describe the form you need in plain language, or load an existing form from the database.</p>

<div class="card">
  <h2 style="margin-bottom:.25rem;">Generate from Description</h2>
  <p style="color:var(--muted); margin-top:0; font-size:.9rem;">
    Describe a form in plain language and the AI will generate it for you.
  </p>
  <form id="create-form">
    <label for="prompt" style="font-weight:600; display:block; margin-bottom:.5rem;">
      What form do you need?
    </label>
    <textarea id="prompt" name="prompt" class="prompt-area"
      placeholder="e.g. A customer feedback form with name, email, a 1-5 star rating, and a comments box"
      required></textarea>

    <div class="examples">
      <span class="example-chip" data-prompt="A contact form with name, email, phone and message">Contact form</span>
      <span class="example-chip" data-prompt="Employee onboarding form with full name, department dropdown (Engineering, Sales, Marketing, HR), start date, and emergency contact info">Onboarding</span>
      <span class="example-chip" data-prompt="Bug report form with title, severity (critical, high, medium, low), steps to reproduce, and screenshot upload">Bug report</span>
      <span class="example-chip" data-prompt="Event RSVP form with name, email, number of guests (1-5), meal preference (vegetarian, chicken, fish), and any dietary restrictions">Event RSVP</span>
      <span class="example-chip" data-prompt="Customer satisfaction survey with overall rating 1-10, what did you like, what can we improve, and would you recommend us (yes/no)">Survey</span>
    </div>

    <div style="margin-top:1rem;">
      <button type="submit" class="btn btn-primary" id="create-btn">Generate Form</button>
    </div>
  </form>
  <div id="create-status" style="margin-top:1rem; display:none;"></div>
</div>

<div class="section-divider">or</div>

<div class="card">
  <h2 style="margin-bottom:.25rem;">Load from Database</h2>
  <p style="color:var(--muted); margin-top:0; font-size:.9rem;">
    Enter a Form ID and Org ID to load an existing form definition from PostgreSQL.
  </p>
  <div class="db-inputs">
    <label for="formid">Form ID<input type="number" id="formid" placeholder="e.g. 4" min="1" /></label>
    <label for="orgid">Org ID<input type="number" id="orgid" placeholder="e.g. 71" min="1" /></label>
  </div>
  <button class="btn btn-primary" id="db-btn" onclick="loadFromDB()">Load from Database</button>
  <div id="db-status" style="margin-top:1rem; display:none;"></div>
</div>

<script>
const FORM_PREFIX = {p!r};
function showError(container, message) {{
  const banner = document.createElement('div');
  banner.className = 'error-banner';
  banner.textContent = message;
  container.innerHTML = '';
  container.appendChild(banner);
  container.style.display = 'block';
}}
document.querySelectorAll('.example-chip').forEach(chip => {{
  chip.addEventListener('click', () => {{
    document.getElementById('prompt').value = chip.dataset.prompt;
    document.getElementById('prompt').focus();
  }});
}});
document.getElementById('create-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const btn = document.getElementById('create-btn');
  const status = document.getElementById('create-status');
  const prompt = document.getElementById('prompt').value.trim();
  if (!prompt) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating...';
  status.style.display = 'block';
  status.innerHTML = '<em>Generating form...</em>';
  try {{
    const res = await fetch(FORM_PREFIX + '/api/v1/forms', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{prompt}})}});
    const data = await res.json();
    if (!res.ok) {{ showError(status, data.error || 'Something went wrong'); return; }}
    window.location.href = data.url;
  }} catch (err) {{ showError(status, 'Network error: ' + err.message);
  }} finally {{ btn.disabled = false; btn.innerHTML = 'Generate Form'; }}
}});
async function loadFromDB() {{
  const btn = document.getElementById('db-btn');
  const status = document.getElementById('db-status');
  const formid = parseInt(document.getElementById('formid').value, 10);
  const orgid = parseInt(document.getElementById('orgid').value, 10);
  if (!formid || !orgid) {{ showError(status, 'Please enter both Form ID and Org ID.'); return; }}
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Loading...';
  status.style.display = 'block'; status.innerHTML = '<em>Loading...</em>';
  try {{
    const res = await fetch(FORM_PREFIX + '/api/v1/forms/from-db', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{formid, orgid}})}});
    const data = await res.json();
    if (!res.ok) {{ showError(status, data.error || 'Failed to load'); return; }}
    window.location.href = data.url;
  }} catch (err) {{ showError(status, 'Network error: ' + err.message);
  }} finally {{ btn.disabled = false; btn.innerHTML = 'Load from Database'; }}
}}
</script>"""


def gallery_page(form_items_html: str) -> str:
    """Return the HTML body for the gallery page.

    Args:
        form_items_html: Pre-rendered HTML for the form list items. The
            caller (``FormPageHandler.gallery``) is responsible for
            prefixing hrefs inside this fragment — ``gallery_page`` never
            touches URLs.

    Returns:
        HTML body string for the gallery page.

    Warning:
        ``form_items_html`` is inserted raw — the caller MUST escape
        all user-controlled content before passing it here.
    """
    return f"""\
<h1>Form Gallery</h1>
<p>All forms generated or loaded in this session.</p>
<div class="card">
  {form_items_html}
</div>"""


def form_page(form_fragment: str) -> str:
    """Return the HTML body wrapping a rendered form fragment.

    Args:
        form_fragment: Rendered HTML5 form fragment.

    Returns:
        HTML body string with the form wrapped in a card.

    Warning:
        ``form_fragment`` is inserted raw — the caller MUST ensure the
        fragment was produced by a trusted renderer (e.g. HTML5Renderer)
        and contains no unescaped user-controlled content.
    """
    return f'<div class="card">{form_fragment}</div>'


def schema_page(
    form_id: str,
    title: str,
    schema_json: str,
    style_json: str,
    prefix: str = "",
) -> str:
    """Return the HTML body for the JSON Schema view page.

    Args:
        form_id: The form identifier.
        title: Human-readable form title.
        schema_json: Pretty-printed JSON Schema string.
        style_json: Pretty-printed Style Schema string.
        prefix: URL prefix where the form-designer is mounted.

    Returns:
        HTML body string with the JSON schema display.
    """
    p = _normalize_prefix(prefix)
    return f"""\
<h1>JSON Schema: {escape(title)}</h1>
<p>Structural JSON Schema for form <code>{escape(form_id)}</code>.</p>

<div style="display:flex; gap:.75rem; margin-bottom:1rem;">
  <a href="{p}/forms/{escape(form_id)}" class="btn btn-secondary">View Form</a>
  <a href="{p}/gallery" class="btn btn-secondary">Gallery</a>
</div>

<div class="card">
  <h2 style="margin-bottom:.5rem;">Schema</h2>
  <pre>{escape(schema_json)}</pre>
</div>

<div class="card">
  <h2 style="margin-bottom:.5rem;">Style</h2>
  <pre>{escape(style_json)}</pre>
</div>

<div class="card">
  <h2 style="margin-bottom:.5rem;">API Endpoints</h2>
  <ul style="margin:0; padding-left:1.2rem;">
    <li><code>GET {p}/api/v1/forms/{escape(form_id)}</code> — Full FormSchema (JSON)</li>
    <li><code>GET {p}/api/v1/forms/{escape(form_id)}/schema</code> — JSON Schema</li>
    <li><code>GET {p}/api/v1/forms/{escape(form_id)}/style</code> — Style Schema</li>
    <li><code>GET {p}/api/v1/forms/{escape(form_id)}/html</code> — Rendered HTML fragment</li>
  </ul>
</div>"""


def error_page(message: str, prefix: str = "") -> str:
    """Return an error page body.

    Args:
        message: Human-readable error message.
        prefix: URL prefix where the form-designer is mounted.

    Returns:
        HTML body string with the error banner.
    """
    p = _normalize_prefix(prefix)
    return (
        f'<div class="error-banner">{escape(message)}</div>'
        f'<a href="{p}/">Go back</a>'
    )
