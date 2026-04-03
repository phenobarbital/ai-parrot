"""Example: aiohttp server with HTML UI for creating and serving forms via natural language.

Open http://localhost:8080 in a browser to:
1. Describe a form in plain language
2. Fill in the generated HTML5 form
3. Submit and see validated results

Also exposes a JSON API:
- POST /api/forms      — create a form (JSON body: {"prompt": "..."})
- GET  /api/forms      — list all created forms
- GET  /forms/{id}     — render the form
- POST /forms/{id}     — validate a submission

Usage:
    source .venv/bin/activate
    python examples/forms/form_server.py
"""

import asyncio
import json
from html import escape

from aiohttp import web

from parrot.clients.factory import LLMFactory
from parrot.forms import (
    CreateFormTool,
    FormRegistry,
    FormValidator,
    StyleSchema,
)
from parrot.forms.renderers.html5 import HTML5Renderer
from parrot.forms.style import LayoutType
from parrot.models.google import GoogleModel

# ---------------------------------------------------------------------------
# Shared CSS used by every page
# ---------------------------------------------------------------------------

_CSS = """\
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

    /* --- cards --- */
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1.5rem; margin-bottom: 1.5rem;
    }

    /* --- prompt builder --- */
    .prompt-area {
      width: 100%; min-height: 100px; padding: .75rem;
      border: 1px solid var(--border); border-radius: var(--radius);
      font: inherit; resize: vertical;
    }
    .prompt-area:focus { outline: 2px solid var(--primary); border-color: transparent; }

    /* --- buttons --- */
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

    /* --- spinner --- */
    .spinner {
      display: inline-block; width: 1em; height: 1em;
      border: 2px solid rgba(255,255,255,.3); border-top-color: #fff;
      border-radius: 50%; animation: spin .6s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* --- form field defaults (from renderer) --- */
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

    /* --- form list --- */
    .form-list { list-style: none; padding: 0; margin: 1rem 0 0; }
    .form-list li {
      padding: .5rem 0; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center;
    }
    .form-list li:last-child { border-bottom: none; }

    /* --- success / error --- */
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

    /* --- nav --- */
    .nav { margin-bottom: 1.5rem; font-size: .9rem; }
    .nav a { margin-right: 1rem; }

    /* --- examples --- */
    .examples { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .75rem; }
    .example-chip {
      padding: .3rem .7rem; background: #eef; border: 1px solid #cce;
      border-radius: 1rem; font-size: .82rem; cursor: pointer;
      transition: background .15s;
    }
    .example-chip:hover { background: #ddf; }
"""


def _page(title: str, body: str, locale: str = "en", nav: bool = True) -> str:
    """Wrap body HTML in a full page shell."""
    nav_html = ""
    if nav:
        nav_html = '<div class="nav"><a href="/">New Form</a><a href="/gallery">Gallery</a></div>'
    return f"""\
<!DOCTYPE html>
<html lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - AI Form Builder</title>
  <style>{_CSS}</style>
</head>
<body>
  {nav_html}
  {body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def create_app() -> web.Application:
    """Build and return the aiohttp Application."""
    app = web.Application()

    llm_client = LLMFactory.create("google")
    registry = FormRegistry()
    renderer = HTML5Renderer()
    validator = FormValidator()
    create_tool = CreateFormTool(
        client=llm_client,
        registry=registry,
        model=GoogleModel.GEMINI_3_FLASH_LITE_PREVIEW.value,
    )

    app["registry"] = registry
    app["renderer"] = renderer
    app["validator"] = validator
    app["create_tool"] = create_tool

    # HTML pages
    app.router.add_get("/", handle_index)
    app.router.add_get("/gallery", handle_gallery)
    app.router.add_get("/forms/{form_id}", handle_get_form)
    app.router.add_post("/forms/{form_id}", handle_submit_form)

    # JSON API
    app.router.add_post("/api/forms", handle_api_create_form)
    app.router.add_get("/api/forms", handle_api_list_forms)

    return app


# ---------------------------------------------------------------------------
# HTML Handlers
# ---------------------------------------------------------------------------

async def handle_index(request: web.Request) -> web.Response:
    """GET / — Landing page with prompt input to create a form."""
    body = """\
<h1>AI Form Builder</h1>
<p>Describe the form you need in plain language and the AI will generate it for you.</p>

<div class="card">
  <form id="create-form">
    <label for="prompt" style="font-weight:600; display:block; margin-bottom:.5rem;">
      What form do you need?
    </label>
    <textarea
      id="prompt"
      name="prompt"
      class="prompt-area"
      placeholder="e.g. A customer feedback form with name, email, a 1-5 star rating, and a comments box"
      required
    ></textarea>

    <div class="examples">
      <span class="example-chip" data-prompt="A contact form with name, email, phone and message">Contact form</span>
      <span class="example-chip" data-prompt="Employee onboarding form with full name, department dropdown (Engineering, Sales, Marketing, HR), start date, and emergency contact info">Onboarding</span>
      <span class="example-chip" data-prompt="Bug report form with title, severity (critical, high, medium, low), steps to reproduce, and screenshot upload">Bug report</span>
      <span class="example-chip" data-prompt="Event RSVP form with name, email, number of guests (1-5), meal preference (vegetarian, chicken, fish), and any dietary restrictions">Event RSVP</span>
      <span class="example-chip" data-prompt="Customer satisfaction survey with overall rating 1-10, what did you like, what can we improve, and would you recommend us (yes/no)">Survey</span>
    </div>

    <div style="margin-top:1rem;">
      <button type="submit" class="btn btn-primary" id="create-btn">
        Generate Form
      </button>
    </div>
  </form>

  <div id="status" style="margin-top:1rem; display:none;"></div>
</div>

<script>
// Example chips fill the prompt
document.querySelectorAll('.example-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.getElementById('prompt').value = chip.dataset.prompt;
    document.getElementById('prompt').focus();
  });
});

// Submit: call API, then redirect to the form
document.getElementById('create-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('create-btn');
  const status = document.getElementById('status');
  const prompt = document.getElementById('prompt').value.trim();
  if (!prompt) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating...';
  status.style.display = 'block';
  status.innerHTML = '<em>The AI is designing your form, this usually takes a few seconds...</em>';

  try {
    const res = await fetch('/api/forms', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt}),
    });
    const data = await res.json();
    if (!res.ok) {
      status.innerHTML = '<div class="error-banner">' + (data.error || 'Something went wrong') + '</div>';
      return;
    }
    // Redirect to the generated form
    window.location.href = data.url;
  } catch (err) {
    status.innerHTML = '<div class="error-banner">Network error: ' + err.message + '</div>';
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Generate Form';
  }
});
</script>"""
    return web.Response(text=_page("Create a Form", body), content_type="text/html")


async def handle_gallery(request: web.Request) -> web.Response:
    """GET /gallery — List all previously generated forms."""
    registry: FormRegistry = request.app["registry"]
    form_ids = await registry.list_form_ids()

    if not form_ids:
        items_html = "<p>No forms created yet. <a href='/'>Create one!</a></p>"
    else:
        items = []
        for fid in form_ids:
            form = await registry.get(fid)
            title = ""
            if form:
                title = form.title if isinstance(form.title, str) else form.title.get("en", fid)
            items.append(
                f'<li>'
                f'<span><strong>{escape(title)}</strong> '
                f'<span style="color:var(--muted);font-size:.85rem">({escape(fid)})</span></span>'
                f'<a href="/forms/{escape(fid)}" class="btn btn-secondary" '
                f'style="padding:.35rem .8rem; font-size:.85rem;">Open</a>'
                f'</li>'
            )
        items_html = f'<ul class="form-list">{"".join(items)}</ul>'

    body = f"""\
<h1>Form Gallery</h1>
<p>All forms you have generated in this session.</p>
<div class="card">
  {items_html}
</div>"""
    return web.Response(text=_page("Gallery", body), content_type="text/html")


async def handle_get_form(request: web.Request) -> web.Response:
    """GET /forms/{form_id} — Render the form as an HTML page."""
    form_id = request.match_info["form_id"]
    registry: FormRegistry = request.app["registry"]
    renderer: HTML5Renderer = request.app["renderer"]

    form = await registry.get(form_id)
    if form is None:
        body = '<div class="error-banner">Form not found.</div><a href="/">Go back</a>'
        return web.Response(text=_page("Not Found", body), status=404, content_type="text/html")

    layout_name = request.query.get("layout", "single_column")
    try:
        layout = LayoutType(layout_name)
    except ValueError:
        layout = LayoutType.SINGLE_COLUMN

    style = StyleSchema(layout=layout)
    rendered = await renderer.render(form, style=style)

    # Inject action + method into the <form> tag
    fragment = rendered.content.replace(
        "<form ",
        f'<form action="/forms/{escape(form_id)}" method="post" ',
        1,
    )

    title = form.title if isinstance(form.title, str) else form.title.get("en", "Form")
    body = f'<div class="card">{fragment}</div>'
    return web.Response(text=_page(title, body), content_type="text/html")


async def handle_submit_form(request: web.Request) -> web.Response:
    """POST /forms/{form_id} — Validate submission, re-render with errors or show success."""
    form_id = request.match_info["form_id"]
    registry: FormRegistry = request.app["registry"]
    renderer: HTML5Renderer = request.app["renderer"]
    validator: FormValidator = request.app["validator"]

    form = await registry.get(form_id)
    if form is None:
        return web.Response(text="Form not found", status=404)

    data = await request.post()
    submission = dict(data)
    result = await validator.validate(form, submission)
    title = form.title if isinstance(form.title, str) else form.title.get("en", "Form")

    if result.is_valid:
        sanitized_json = json.dumps(result.sanitized_data, indent=2, default=str)
        body = f"""\
<div class="success">
  <h2>Submitted successfully</h2>
  <p>The form data passed all validations.</p>
</div>
<div class="card">
  <h3>Submitted Data</h3>
  <pre>{escape(sanitized_json)}</pre>
</div>
<div style="display:flex; gap:.75rem;">
  <a href="/forms/{escape(form_id)}" class="btn btn-secondary">Fill again</a>
  <a href="/" class="btn btn-primary">Create another form</a>
</div>"""
        return web.Response(text=_page(f"{title} - Success", body), content_type="text/html")

    # Re-render with errors
    rendered = await renderer.render(form, prefilled=submission, errors=result.errors)
    fragment = rendered.content.replace(
        "<form ",
        f'<form action="/forms/{escape(form_id)}" method="post" ',
        1,
    )
    error_count = len(result.errors)
    banner = (
        f'<div class="error-banner">'
        f'Please fix {error_count} error{"s" if error_count != 1 else ""} below.'
        f'</div>'
    )
    body = f'{banner}<div class="card">{fragment}</div>'
    return web.Response(text=_page(title, body), content_type="text/html")


# ---------------------------------------------------------------------------
# JSON API Handlers
# ---------------------------------------------------------------------------

async def handle_api_create_form(request: web.Request) -> web.Response:
    """POST /api/forms — Create a form from a prompt (JSON API)."""
    body = await request.json()
    prompt = body.get("prompt")
    if not prompt:
        return web.json_response({"error": "prompt is required"}, status=400)

    create_tool: CreateFormTool = request.app["create_tool"]
    result = await create_tool.execute(prompt=prompt, persist=True)

    if not result.success:
        return web.json_response(
            {"error": result.metadata.get("error", "Form creation failed")},
            status=500,
        )

    form_id = result.metadata["form"]["form_id"]
    return web.json_response({
        "form_id": form_id,
        "title": result.result["title"],
        "url": f"/forms/{form_id}",
    })


async def handle_api_list_forms(request: web.Request) -> web.Response:
    """GET /api/forms — List all form IDs."""
    registry: FormRegistry = request.app["registry"]
    form_ids = await registry.list_form_ids()
    return web.json_response({"forms": form_ids})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("AI Form Builder running at http://localhost:8080")
    print("  /             — create a form via natural language")
    print("  /gallery      — browse generated forms")
    print("  /forms/{id}   — fill and submit a form")
    web.run_app(create_app(), host="0.0.0.0", port=8080)
