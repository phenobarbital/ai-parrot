# F004 — async-notify Jinja support: file-based only (brainstorm claim partly WRONG)

**Query:** Q007 (direct read of installed package)
**Citations:** `notify/templates.py` :: `TemplateParser.get_template` (L67-81),
  `render` (L99), `render_async` (L112); `notify/providers/base.py` L140-184;
  `notify/conf.py` L6-10
**Package:** async-notify `1.5.5` (installed in `.venv`)
**Confidence:** high (direct source read of the installed version)

## Confirmed

- Jinja2 IS long-standing built-in functionality — `TemplateParser` wraps a Jinja2
  `Environment` with `enable_async=True`, `i18n` + `loopcontrols` extensions, and
  precompiled templates. Both `render()` and `render_async()` exist.
- Providers render automatically: `base.py::_render_()` injects
  `recipient`, `username`, `message`, `subject`, plus arbitrary `**kwargs` —
  so `report_title` / `generated_at` / `share_url` inject with no new code.
- **No new rendering engine is needed.** Brainstorm rev2 #7 is correct on this point.

## CONTRADICTED: inline Jinja2 stream is NOT supported

Brainstorm rev2 #7 and §4.1.D claim async-notify "accepts a Jinja2 stream as text
(`template={jinja2 stream}`)". The installed code does not support this:

```python
if template:
    self._template = self._tpl.get_template(template)   # providers/base.py L141
```

and

```python
def get_template(self, filename: str):
    self.template = self.env.get_template(str(filename))   # FileSystemLoader lookup
```

`template=` is resolved as a **filename** through a `FileSystemLoader` rooted at the
template directory. `TemplateParser` exposes no `from_string()`, and there is no
`Environment.from_string` call anywhere in the package. Passing a raw Jinja2 string
raises `FileNotFoundError: Template cannot be found: ...`.

## Also: the config key is `TEMPLATE_DIR`, not `TEMPLATES_DIR`

`notify/conf.py`: `config.get('TEMPLATE_DIR')`, defaulting to `BASE_DIR/templates`.
The brainstorm consistently writes `TEMPLATES_DIR` (§3.2, §4.1.D, §4.1.E).

## Impact

Bounded and does not break HI-5. v1 should ship 1-2 **template files** under
`TEMPLATE_DIR` (which §4.1.D already proposes as the primary path, and §4.1.E already
limits the UI to "the available TEMPLATES_DIR set"). What must be dropped is the
"or inline Jinja2 stream" alternative — unless SPEC-A adds a `from_string` path to
async-notify, which is out of scope and would be an upstream change.
