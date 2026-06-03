---
id: F003
query_id: Q002
type: read
intent: Map ACTION_MAP contents and understand Loop template variable convention
executed_at: 2026-06-04T00:00:00Z
duration_ms: 52576
parent_id: null
depth: 0
---

# F003 — ACTION_MAP has 29 types; Loop uses SINGLE braces {index}, not double {{index}}

## Summary

`ACTION_MAP` (models.py:726-755) registers 29 action types. The `Loop` class (models.py:679-707) has 11 fields including `do_replace`, `start_index`, `values`, `value_name`. **Critical finding**: the actual template substitution in tool.py uses SINGLE braces `{index}`, `{i}`, `{i+1}`, `{value}` — NOT the double-brace `{{index}}` convention stated in the brainstorm document. The substitution is driven by `_substitute_template_vars` (tool.py:3271-3327) using regex `r'\{([^}]*(?:i|index|iteration)[^}]*)\}'` and supports arithmetic expressions.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 726-755
  symbol: `ACTION_MAP`
  excerpt: |
    ACTION_MAP = {
        "navigate": Navigate, "click": Click, "hover": Hover, "fill": Fill,
        "type": Type, "select": Select, "evaluate": Evaluate, "press_key": PressKey,
        "refresh": Refresh, "back": Back, "scroll": Scroll, "get_cookies": GetCookies,
        "set_cookies": SetCookies, "wait": Wait, "authenticate": Authenticate,
        "await_human": AwaitHuman, "await_keypress": AwaitKeyPress,
        "await_browser_event": AwaitBrowserEvent, "loop": Loop, "get_text": GetText,
        "get_html": GetHTML, "extract": Extract, "extract_jsonld": ExtractJsonLd,
        "submit": Submit, "wait_for_download": WaitForDownload,
        "upload_file": UploadFile, "screenshot": Screenshot, "conditional": Conditional
    }

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 679-707
  symbol: `Loop`
  excerpt: |
    class Loop(BrowserAction):
        actions: List["ActionList"]
        iterations: Optional[int] = None
        values: Optional[List[Any]] = None
        value_name: Optional[str] = "value"
        do_replace: bool = True
        start_index: int = 0

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
  lines: 3271-3327
  symbol: `_substitute_template_vars`
  excerpt: |
    # Pattern matches {i}, {index}, {iteration}, {i+1}, etc.
    pattern = r'\{([^}]*(?:i|index|iteration)[^}]*)\}'

## Notes

The brainstorm claims "reutilizando la convención de doble llave del Loop, no str.format". This is factually incorrect: Loop uses SINGLE braces via regex, not double braces. TemplatePlan must choose its own convention. Double braces `{{param}}` are recommended to avoid collisions with CSS selectors containing `{` and with the existing Loop single-brace convention.
