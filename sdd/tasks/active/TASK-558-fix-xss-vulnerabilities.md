# TASK-558: Fix XSS vulnerabilities in renderer and templates

**Feature**: FEAT-080 formdesigner-package-fixes
**Status**: pending
**Priority**: critical
**Estimated effort**: medium

## Context

Code review found multiple XSS injection points where user-controlled data is interpolated into HTML without escaping. The `html.escape` function is already imported but not applied in several critical locations.

## Tasks

### 1. Escape all user-controlled values in HTML5 renderer (C4)

**File**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py`

Apply `html.escape()` at these locations:

**Line ~304** — field value in `<input>` attributes:
```python
# BEFORE
attrs.append(f'value="{value}"')
# AFTER
attrs.append(f'value="{html.escape(str(value), quote=True)}"')
```

**Line ~304 in `_render_textarea`** — textarea content:
```python
# BEFORE
text_content = str(value) if value is not None else ""
return f'<textarea {" ".join(attrs)}>{text_content}</textarea>'
# AFTER
text_content = html.escape(str(value)) if value is not None else ""
return f'<textarea {" ".join(attrs)}>{text_content}</textarea>'
```

**Line ~201** — `data-depends-on` JSON attribute:
```python
# BEFORE
depends_attr = f' data-depends-on="{json.dumps(field.depends_on.model_dump())}"'
# AFTER
safe_json = html.escape(json.dumps(field.depends_on.model_dump()), quote=True)
depends_attr = f' data-depends-on="{safe_json}"'
```

### 2. Escape `locale` in `page_shell()` (C6)

**File**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/templates.py` (line ~104)

```python
# BEFORE
return f"""<html lang="{locale}">"""
# AFTER
from html import escape
return f"""<html lang="{escape(locale)}">"""
```

### 3. Fix `html` variable shadow (I11)

**File**: `renderers/html5.py` (line ~147)

The local variable `html = template.render(...)` shadows the `import html` at module level. Rename:
```python
# BEFORE
html = template.render(...)
return RenderedForm(content=html, ...)
# AFTER
rendered_html = template.render(...)
return RenderedForm(content=rendered_html, ...)
```

### 4. Document XSS trust boundary

Add docstring warnings to `gallery_page()`, `form_page()`, and `submit_form()` in `templates.py` stating that raw HTML parameters MUST be pre-escaped by the caller. Example:

```python
def gallery_page(form_items_html: str) -> str:
    """Render the form gallery page.

    Warning:
        ``form_items_html`` is inserted raw — the caller MUST escape
        all user-controlled content before passing it here.
    """
```

## Acceptance Criteria

- [ ] All `<input value="...">` attributes escaped with `html.escape(quote=True)`
- [ ] All `<textarea>` content escaped with `html.escape()`
- [ ] All `data-*` attributes escaped
- [ ] `locale` parameter escaped in `page_shell()`
- [ ] No variable shadows on `html` import
- [ ] XSS trust boundary documented on template functions
- [ ] Unit tests for renderer with special characters (quotes, `<script>`, etc.)
