---
type: Wiki Overview
title: 'TASK-1325: `enhance_infographic` agent method + HTML SRI validator + prompts'
id: doc:sdd-tasks-completed-task-1325-enhance-pipeline-and-sri-validator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 2 from the spec — the optional LLM-augmented JavaScript
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.tools._enhance_html_check
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1325: `enhance_infographic` agent method + HTML SRI validator + prompts

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 2)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1319, TASK-1323
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

Module 2 from the spec — the optional LLM-augmented JavaScript
interactivity pass. When the toolkit's `render` is invoked with
`mode="enhance"`, the deterministic skeleton is handed to the agent's
new `enhance_infographic` method along with the data context and the
template's `js_bundles` whitelist. The LLM returns enhanced HTML; we
validate it (post-output HTML walk) and either accept it (`enhanced=True`)
or silently fall back to the skeleton (`enhanced=False` + WARNING log).

This task wires the enhancement plumbing into the toolkit's
`_maybe_enhance` placeholder shipped by TASK-1323.

---

## Scope

- Add `async def enhance_infographic(...)` on the agent class that
  already hosts `get_infographic` (search for the existing method via
  `grep -rn "def get_infographic" packages/ai-parrot/src/parrot/bots/`).
  Signature per spec:
  ```python
  async def enhance_infographic(
      self,
      *,
      skeleton: str,
      brief: str,
      data_context: Dict[str, Any],
      js_bundles_available: List[JSBundle],
  ) -> str: ...
  ```
- Add the new `INFOGRAPHIC_ENHANCE_PROMPT` to
  `parrot/bots/prompts/__init__.py`. It MUST:
  - Show the LLM the skeleton and the data context.
  - List the allowed `js_bundles` (names + scope + sri_hash).
  - Forbid `<script src>` / `<link rel="stylesheet">` outside that list.
  - Forbid inline `<script>` blocks that fetch remote resources.
- Add the HTML validator helper `parrot/tools/_enhance_html_check.py`:
  ```python
  def validate_enhanced_html(
      html: str,
      allowed_bundles: Iterable[JSBundle],
  ) -> None: ...   # raises InfographicValidationError(code="ENHANCE_OUTPUT_INVALID")
  ```
  Use `html.parser.HTMLParser` (stdlib) — do NOT pull a new dependency.
  Checks:
  - Every `<script src="...">` URL has a matching `JSBundle(scope='cdn',
    url=url, sri_hash=...)` AND the rendered `<script integrity="sha384-…">`
    attribute matches `sri_hash`.
  - Every `<link rel="stylesheet" href="...">` URL has a matching allowed
    bundle (extend whitelist semantics similarly).
  - Inline `<script>...</script>` is allowed (CSP is `'unsafe-inline'`).
  - Inline `<style>` is allowed.
- Wire `InfographicToolkit._maybe_enhance` to call
  `bot.enhance_infographic(...)`, validate, and fall back on failure.
- Tests:
  - SRI whitelist match → accepted.
  - External `<script src>` not in the whitelist → rejected.
  - External `<link rel="stylesheet">` not allowed → rejected.
  - Inline `<script>` accepted.
  - On `ENHANCE_OUTPUT_INVALID`, toolkit returns the skeleton with
    `enhanced=False` AND emits a `self.logger.warning(...)` call.

**NOT in scope**:
- CSP header for the HTML-serving route — that's TASK-1322.
- Streaming the enhanced HTML to the client mid-generation — full text
  exchange only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` (or wherever `get_infographic` lives) | MODIFY | Add `async def enhance_infographic(...)`. |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | Add `INFOGRAPHIC_ENHANCE_PROMPT`. |
| `packages/ai-parrot/src/parrot/tools/_enhance_html_check.py` | CREATE | `validate_enhanced_html(...)` helper. |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | Wire `_maybe_enhance` to call the bot + validate + fall back. |
| `packages/ai-parrot/tests/unit/tools/test_enhance_html_check.py` | CREATE | SRI / external resource tests. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_enhance.py` | CREATE | Toolkit enhance fallback path. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.infographic import JSBundle              # from TASK-1319

from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicValidationError,
)                                                            # from TASK-1323
```

### Existing Signatures to Use

```python
# bots/agent.py — the class hosting get_infographic (NAME VARIES;
# verify via `grep -n "def get_infographic" packages/ai-parrot/src/parrot/bots/`)
class <BasicAgentOrSimilar>:
    async def get_infographic(self, *args, **kwargs) -> Any: ...
    # The class uses self._llm_client (AbstractClient) for completions —
    # check the existing get_infographic body and reuse the same path.
```

### Does NOT Exist
- ~~`bot.enhance_infographic`~~ — created by this task.
- ~~`INFOGRAPHIC_ENHANCE_PROMPT`~~ — created by this task.
- ~~`validate_enhanced_html`~~ — created by this task.
- ~~lxml dependency~~ — do NOT add. Stick with stdlib `html.parser`.

---

## Implementation Notes

### `enhance_infographic` pattern

```python
async def enhance_infographic(
    self,
    *,
    skeleton: str,
    brief: str,
    data_context: Dict[str, Any],
    js_bundles_available: List[JSBundle],
) -> str:
    from parrot.bots.prompts import INFOGRAPHIC_ENHANCE_PROMPT
    prompt = INFOGRAPHIC_ENHANCE_PROMPT.format(
        skeleton=skeleton,
        brief=brief,
        data_context_json=json.dumps(data_context, default=str),
        js_bundles=json.dumps([b.model_dump() for b in js_bundles_available]),
    )
    completion = await self._llm_client.completion(prompt=prompt, ...)
    return completion.text  # caller validates against the whitelist
```

### `validate_enhanced_html`

```python
# parrot/tools/_enhance_html_check.py
from __future__ import annotations
from html.parser import HTMLParser
from typing import Iterable, List
from parrot.models.infographic import JSBundle


class _ExternalResourceCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: List[Dict[str, Optional[str]]] = []   # [{src, integrity}]
        self.links: List[Dict[str, Optional[str]]] = []     # [{rel, href, integrity}]

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_d = dict(attrs)
        if tag == "script" and attrs_d.get("src"):
            self.scripts.append({"src": attrs_d["src"],
                                  "integrity": attrs_d.get("integrity")})
        elif tag == "link" and attrs_d.get("rel") == "stylesheet" and attrs_d.get("href"):
            self.links.append({"href": attrs_d["href"],
                                "integrity": attrs_d.get("integrity")})


def validate_enhanced_html(html: str, allowed_bundles: Iterable[JSBundle]) -> None:
    """Raise InfographicValidationError(code='ENHANCE_OUTPUT_INVALID') on any
    external resource not present in the allowed_bundles whitelist."""
    from parrot.tools.infographic_toolkit import InfographicValidationError
    collector = _ExternalResourceCollector()
    collector.feed(html)
    cdn_index = {(b.url, b.sri_hash): b for b in allowed_bundles
                 if b.scope == "cdn" and b.url and b.sri_hash}

    for tag in collector.scripts:
        if (tag["src"], tag.get("integrity")) not in cdn_index:
            raise InfographicValidationError(
                "ENHANCE_OUTPUT_INVALID",
                {"reason": "external script outside whitelist",
                 "src": tag["src"], "integrity": tag.get("integrity")},
            )
    for tag in collector.links:
        if (tag["href"], tag.get("integrity")) not in cdn_index:
            raise InfographicValidationError(
                "ENHANCE_OUTPUT_INVALID",
                {"reason": "external stylesheet outside whitelist",
                 "href": tag["href"], "integrity": tag.get("integrity")},
            )
```

### Toolkit `_maybe_enhance` wiring

Replace the TASK-1323 placeholder:

```python
async def _maybe_enhance(
    self, *, skeleton: str, brief: Optional[str], mode: str,
    data_context: Dict[str, Any], js_bundles_available: List[JSBundle],
) -> Tuple[str, bool]:
    if mode != "enhance":
        return skeleton, False
    if not brief:
        # mode='enhance' without a brief is a contract violation; log + fall back
        self.logger.warning("enhance requested without brief; falling back")
        return skeleton, False

    bot = getattr(self, "_bot", None)
    if bot is None or not hasattr(bot, "enhance_infographic"):
        self.logger.warning("bound bot lacks enhance_infographic; falling back")
        return skeleton, False

    try:
        enhanced = await bot.enhance_infographic(
            skeleton=skeleton, brief=brief, data_context=data_context,
            js_bundles_available=js_bundles_available,
        )
        validate_enhanced_html(enhanced, js_bundles_available)
        return enhanced, True
    except InfographicValidationError as exc:
        self.logger.warning(
            "Enhanced HTML rejected (%s) — falling back to deterministic skeleton: %s",
            exc.code, exc.detail,
        )
        return skeleton, False
```

### Key Constraints
- Fall back is SILENT to the user. Surface the security event via
  `self.logger.warning(...)` ONLY.
- Use stdlib `html.parser` — no new deps.
- `INFOGRAPHIC_ENHANCE_PROMPT` must be a `string.Template`-friendly or
  f-string-friendly template. Document the placeholders.

---

## Acceptance Criteria

- [ ] `bot.enhance_infographic(skeleton=..., brief=..., data_context=...,
      js_bundles_available=[...])` returns a string.
- [ ] `validate_enhanced_html("<script src='https://cdn/x.js' integrity='sha384-A'></script>", [JSBundle(...cdn, url=https://cdn/x.js, sri=sha384-A)])` returns `None`.
- [ ] `validate_enhanced_html("<script src='https://evil/x.js'></script>", [...])` raises `InfographicValidationError(code="ENHANCE_OUTPUT_INVALID")`.
- [ ] `validate_enhanced_html("<link rel='stylesheet' href='https://evil/x.css'>", [...])` raises `ENHANCE_OUTPUT_INVALID`.
- [ ] Inline `<script>console.log(1)</script>` is accepted.
- [ ] `InfographicToolkit.render(mode="enhance", ...)` with a bot stub
      that returns malicious HTML produces an `InfographicRenderResult`
      with `enhanced=False` AND `self.logger.warning(...)` is called.
- [ ] `InfographicToolkit.render(mode="enhance", ...)` with bot returning
      whitelisted HTML produces `enhanced=True`.
- [ ] `pytest packages/ai-parrot/tests/unit/tools/test_enhance_html_check.py packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_enhance.py -v` passes.
- [ ] `ruff check` clean on all touched files.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_enhance_html_check.py
import pytest
from parrot.tools._enhance_html_check import validate_enhanced_html
from parrot.tools.infographic_toolkit import InfographicValidationError
from parrot.models.infographic import JSBundle


def _bundle():
    return JSBundle(name="echarts", scope="cdn",
                    url="https://cdn.example/echarts.min.js",
                    sri_hash="sha384-AAAA")


def test_inline_script_ok():
    validate_enhanced_html("<script>alert(1)</script>", [])


def test_whitelisted_cdn_script_ok():
    html = ('<script src="https://cdn.example/echarts.min.js" '
            'integrity="sha384-AAAA"></script>')
    validate_enhanced_html(html, [_bundle()])


def test_external_script_blocked():
    with pytest.raises(InfographicValidationError) as ei:
        validate_enhanced_html('<script src="https://evil/x.js"></script>',
                                [_bundle()])
    assert ei.value.code == "ENHANCE_OUTPUT_INVALID"


def test_wrong_sri_blocked():
    html = ('<script src="https://cdn.example/echarts.min.js" '
            'integrity="sha384-BBBB"></script>')
    with pytest.raises(InfographicValidationError):
        validate_enhanced_html(html, [_bundle()])


def test_external_stylesheet_blocked():
    with pytest.raises(InfographicValidationError):
        validate_enhanced_html(
            '<link rel="stylesheet" href="https://evil/x.css">',
            [_bundle()],
        )
```

```python
# packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_enhance.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.infographic_toolkit import InfographicToolkit


@pytest.fixture
def toolkit_with_bot():
    store = MagicMock()
    store.save_artifact = AsyncMock()
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    tk = InfographicToolkit(artifact_store=store)
    tk._bot = MagicMock()
    tk._bot._get_repl_locals = MagicMock(return_value={"r": __import__("pandas").DataFrame([{"x": 1}])})
    tk._bot.user_id = "u"; tk._bot.agent_id = "agt"; tk._bot.session_id = "s"
    return tk


async def test_enhance_fallback_on_invalid_html(toolkit_with_bot, hero_cards_template, caplog):
    toolkit_with_bot._bot.enhance_infographic = AsyncMock(
        return_value='<script src="https://evil/x.js"></script>')
    result = await toolkit_with_bot.render(
        template_name=hero_cards_template.name, theme=None, mode="enhance",
        enhance_brief="please make charts interactive",
        blocks=[{"type": "hero_card",
                 "cards": [{"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}]}],
        data_variables=["r"],
    )
    assert result.enhanced is False
    assert any("ENHANCE_OUTPUT_INVALID" in r.message for r in caplog.records)


async def test_enhance_accepted_on_whitelisted_html(toolkit_with_bot, hero_cards_template, monkeypatch):
    # Use the template's js_bundles (set fixture w/ a bundle) and a matching script tag.
    ...
```

---

## Agent Instructions

1. Confirm TASK-1319 (JSBundle) and TASK-1323 (toolkit core) are merged.
2. Search for `get_infographic` in `parrot/bots/` to find the host class
   (likely `BasicAgent`). Add `enhance_infographic` next to it.
3. Implement `validate_enhanced_html` standalone with its own tests
   first.
4. Wire `_maybe_enhance` and write the enhance-path tests.
5. Run `pytest packages/ai-parrot/tests/unit/tools/ -v`.
6. Move to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
