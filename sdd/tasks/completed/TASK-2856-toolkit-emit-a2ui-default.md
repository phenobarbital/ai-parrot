# TASK-2856: `InfographicToolkit.emit_a2ui` defaults to True; drop the HTML-lane DeprecationWarning

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 G1, §2 Overview step 1, §3 Module 1. Today `InfographicToolkit(emit_a2ui=False)` is
the default and no production caller flips it, so every AgentTalk infographic turn is
HTML-only. The toolkit also constructs the legacy `InfographicHTMLRenderer` through
`get_infographic_html_renderer()`, which emits an unconditional FEAT-273 G7
`DeprecationWarning` on every toolkit construction. FEAT-527 resolves U1 as
**dual-emit permanently**: the HTML lane is a sibling emission, not deprecated.

---

## Scope

- Change `InfographicToolkit.__init__` keyword default `emit_a2ui: bool = False` → `True`
  (`infographic_toolkit.py:219`); update the module docstring (`:1-13`) and the
  constructor docstring (`:235-237`) to describe the dual-emit contract.
- Remove the `warnings.warn(... DeprecationWarning ...)` call inside
  `get_infographic_html_renderer()` (`outputs/formats/__init__.py:133-139`). Keep the
  `ImportError` translation for a missing `ai-parrot-visualizations` satellite and the
  `get_renderer(OutputMode.INFOGRAPHIC)` lazy-load trigger. Reword the docstring: the
  infographic-HTML renderer is the "HTML sibling emission of the A2UI Infographic lane
  (FEAT-527)"; the `# FEAT-273 (G7)` comment is replaced accordingly.
- Do NOT touch `_A2UI_REPLACEMENTS` / `_warn_if_deprecated` (other legacy modes stay deprecated).
- Add regression tests proving the three production constructors now emit by default:
  `InfographicAuthoringMixin` (`bots/mixins/infographic_authoring.py:85-89`),
  `InfographicTalk._get_render_toolkit` (`handlers/infographic.py:535-538`),
  `ResultAgent` (`bots/flows/result_agent.py:142,171`) — assert `toolkit._emit_a2ui is True`
  without changing those call sites.
- Update `examples/agents/a2ui/a2ui_dashboard_walkthrough.py:9,155,195-197` comments/prose
  so they no longer claim `emit_a2ui=True` is required (the explicit kwarg may stay).

**NOT in scope**: bot finalizer routing (TASK-2857), AgentTalk envelope keys (TASK-2858),
`render_template` / `render_data_template` envelope shape (TASK-2864), docs pages (TASK-2869).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | default flip + docstrings |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | remove DeprecationWarning in `get_infographic_html_renderer` |
| `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` | MODIFY | prose no longer says the flag is required |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py` | MODIFY | default/opt-out tests |
| `packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py` | MODIFY | constructor-default assertions for mixin / handler / ResultAgent |
| `packages/ai-parrot/tests/unit/outputs/test_formats_infographic_html_renderer.py` | CREATE | no-DeprecationWarning test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult  # infographic_toolkit.py:180,159
from parrot.outputs.formats import get_infographic_html_renderer                        # outputs/formats/__init__.py:119
from parrot.models.outputs import OutputMode                                            # models/outputs.py:58 INFOGRAPHIC, :64 A2UI
from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin           # bots/mixins/infographic_authoring.py
from parrot.bots.flows.result_agent import ResultAgent                                  # bots/flows/result_agent.py (uses InfographicToolkit at :142,:171)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                                  # :180
    def __init__(self, artifact_store, *, ..., template_dirs: Optional[Any] = None,
                 templates: Optional[Dict[str, str]] = None,
                 emit_a2ui: bool = False, ...) -> None                        # :213-219  ← flip default
        self._emit_a2ui = emit_a2ui                                          # :252
        self._renderer = get_infographic_html_renderer()()                   # :253  (warning trip site today)
    async def render(...) -> InfographicRenderResult                         # :402 ; `if self._emit_a2ui:` :508
    async def render_template(...) -> InfographicRenderResult                # :524 ; `if self._emit_a2ui:` :614
    async def render_data_template(...) -> InfographicRenderResult           # :643 ; `if self._emit_a2ui:` :753
    def _build_a2ui_envelope(self, response, artifact_id, *, title=None) -> Optional[Dict]  # :846

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
def get_infographic_html_renderer():                                        # :119
    # docstring :120-131 ; warnings.warn(... DeprecationWarning, stacklevel=2) :133-139  ← REMOVE
    # try: from .infographic_html import InfographicHTMLRenderer as _Cls :140-152 (KEEP, incl. ImportError text)
    # get_renderer(OutputMode.INFOGRAPHIC) :155 ; return _Cls :156

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
class InfographicAuthoringMixin:
    def __init__(self, *args, infographic_toolkit=None, artifact_store=None, recipe_store=None, template_dirs=None, **kwargs)  # :75-82
        infographic_toolkit = InfographicToolkit(artifact_store=artifact_store, recipe_store=recipe_store, template_dirs=template_dirs)  # :85-89

# packages/ai-parrot-server/src/parrot/handlers/infographic.py
def _get_render_toolkit(self) -> InfographicToolkit                         # :497 ; InfographicToolkit(artifact_store=app.get("artifact_store"), template_dirs=template_dirs) :535-538

# test fixture pattern — tests/tools/test_infographic_toolkit_a2ui_wiring.py:19-43
#   cls = importlib.import_module("parrot.tools.infographic_toolkit").InfographicToolkit
#   instance = cls.__new__(cls); instance.logger = logging.getLogger(...)   (bypasses __init__; ArtifactStore not needed)
```

### Does NOT Exist
- ~~`InfographicToolkit.emit_a2ui`~~ public attribute — only the private `self._emit_a2ui`.
- ~~`parrot.outputs.infographic`~~ package — renderers live in the visualizations satellite (`parrot.outputs.formats.infographic_html`).
- ~~a production `emit_a2ui=True` call site~~ — only `examples/agents/a2ui/a2ui_dashboard_walkthrough.py:197`.
- ~~`_A2UI_REPLACEMENTS[OutputMode.INFOGRAPHIC]`~~ — INFOGRAPHIC is intentionally absent from that table; do not add it.

---

## Implementation Notes

### Pattern to Follow
The additive-lane policy already in `_build_a2ui_envelope` (`:846-899`): a build failure
logs `self.logger.warning(..., exc_info=True)` and returns `None` → HTML-only result.
Flipping the default must not change that policy.

### Key Constraints
- Constructing the toolkit requires an `ArtifactStore`; for unit tests use the
  `cls.__new__(cls)` fixture style or a `MagicMock()` store as
  `tests/unit/tools/test_infographic_toolkit.py` already does.
- Constructor tests for `InfographicAuthoringMixin` / `InfographicTalk` / `ResultAgent`
  may patch `parrot.tools.infographic_toolkit.get_infographic_html_renderer` to avoid
  importing the satellite; assert only `_emit_a2ui`.
- `warnings.catch_warnings(record=True)` + `warnings.simplefilter("always")` for the
  no-warning test; import the satellite module first so the test is not skipped by an
  `ImportError` (skip if `ai-parrot-visualizations` is not installed).

### References in Codebase
- `packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py` — wiring tests to extend.
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:12-40` — the deprecation table that must remain untouched.

---

## Acceptance Criteria

- [ ] `InfographicToolkit(artifact_store=MagicMock())._emit_a2ui is True`; `emit_a2ui=False` still yields `False`
- [ ] `render()` result carries `a2ui_envelope` by default (reuse the `_response()` fixture; build failure still returns HTML-only)
- [ ] `get_infographic_html_renderer()` emits no `DeprecationWarning`; missing-satellite `ImportError` text unchanged
- [ ] Mixin / `InfographicTalk._get_render_toolkit` / `ResultAgent` toolkits report `_emit_a2ui is True` without code changes at those call sites
- [ ] All tests pass: `timeout -s KILL 600 pytest packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py packages/ai-parrot/tests/unit/outputs -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/infographic_toolkit.py packages/ai-parrot/src/parrot/outputs/formats/__init__.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/outputs/test_formats_infographic_html_renderer.py
import warnings
import pytest

pytest.importorskip("parrot.outputs.formats.infographic_html")

def test_get_infographic_html_renderer_no_deprecation_warning():
    from parrot.outputs.formats import get_infographic_html_renderer
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cls = get_infographic_html_renderer()
    assert cls.__name__ == "InfographicHTMLRenderer"
    assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]


# packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py (add)
def test_toolkit_default_emits_a2ui(mock_store):
    tk = InfographicToolkit(artifact_store=mock_store)
    assert tk._emit_a2ui is True

def test_toolkit_emit_a2ui_opt_out(mock_store):
    assert InfographicToolkit(artifact_store=mock_store, emit_a2ui=False)._emit_a2ui is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `:219`, `:252-253`, `:133-139` still match before editing
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2856-toolkit-emit-a2ui-default.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Flipped `InfographicToolkit.__init__(emit_a2ui: bool = True)`
default, updated module + constructor docstrings. Removed the unconditional
`DeprecationWarning` in `get_infographic_html_renderer()` (kept the
`ImportError` translation and the `# FEAT-527 (amends FEAT-273 G7)` comment);
`_A2UI_REPLACEMENTS`/`_warn_if_deprecated` untouched. Updated
`examples/agents/a2ui/a2ui_dashboard_walkthrough.py` prose (lines 9, 155-160,
195, 370) to stop implying `emit_a2ui=True` is required; the explicit kwarg
at line 197 was left in place per task note. Added regression tests: default
+ opt-out unit tests in `test_infographic_toolkit.py`
(`TestEmitA2UIDefault`); a new `TestProductionConstructorsEmitByDefault`
class in `test_infographic_toolkit_a2ui_wiring.py` proving
`InfographicAuthoringMixin`, `InfographicTalk._get_render_toolkit`, and
`ResultAgent.agent_tools` all build an emitting toolkit with zero call-site
changes; new `test_formats_infographic_html_renderer.py` asserting no
`DeprecationWarning`. 52/52 targeted tests pass (6 pre-existing failures in
`tests/unit/outputs/cards/` are unrelated Adaptive-Cards schema-version
mismatches, untouched by this task). `ruff check` on touched files shows
only pre-existing E402/F401 findings not introduced by this change.

**Deviations from spec**: none
