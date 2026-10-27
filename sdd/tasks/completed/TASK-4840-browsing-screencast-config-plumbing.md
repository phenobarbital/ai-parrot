# TASK-4840: Screencast config plumbing

**Feature**: FEAT-763 — browsing-playwright-default-and-screencast
**Spec**: `sdd/specs/browsing-playwright-default-and-screencast.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4839
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. Playwright already supports native
per-`BrowserContext` video recording (`PlaywrightConfig.record_video_dir`,
already wired into `PlaywrightDriver._build_context_kwargs()`) — but
nothing above the driver layer exposes it: `DriverConfig` has no video
field, and `DriverFactory.create()`'s `"playwright"` branch never
forwards one into `PlaywrightConfig(...)`. This task adds the missing
plumbing: a `record_video: bool` toggle on `WebScrapingToolkit.__init__`
that resolves to a confined `DriverConfig.record_video_dir` path, forwarded
to `PlaywrightConfig` only for `driver_type="playwright"` — never for
`"obscura"` (explicit spec Non-Goal).

This task depends on TASK-4839 only because it edits the **same three
files** (`toolkit_models.py`, `toolkit.py`, `driver_factory.py`) — not
because it needs any new behavior TASK-4839 introduces. Serialize to
avoid a merge conflict (spec's Worktree Strategy).

---

## Scope

- Add `record_video_dir: Optional[str] = None` field to `DriverConfig`
  (`toolkit_models.py`, after `obscura_allow_private_network`).
- Add `record_video: bool = False` parameter to
  `WebScrapingToolkit.__init__` (after `confine_paths`), and resolve it
  into `self._config.record_video_dir` via `self._config.merge({...})`
  **after** `self._plans_dir` is set — `files_root` is not computable
  before that point.
- In `DriverFactory.create()`'s `"playwright"` branch only, forward
  `record_video_dir=config.get("record_video_dir")` into the
  `PlaywrightConfig(...)` constructor call.
- Do **NOT** touch the `"obscura"` branch's `PlaywrightConfig(...)` call —
  `record_video_dir` must never reach it (explicit spec Non-Goal; FEAT-762
  independently found Obscura's video support unverified).
- Write the new unit tests from spec §4 for this module.

**NOT in scope**:
- `PlaywrightDriver.quit()` capturing `recording_path`, or
  `WebBrowsingToolkit.close_browser()` surfacing it — TASK-4841.
- `.parrot/mcp-toolkits.yaml` — TASK-4841.
- Any change to `PlaywrightConfig` itself (`drivers/playwright_config.py`)
  — it already has `record_video_dir`, verified unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` | MODIFY | add `DriverConfig.record_video_dir` field |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | add `record_video` param + resolution logic |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | MODIFY | forward `record_video_dir` in the `"playwright"` branch only |
| `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` | MODIFY | add `record_video` resolution tests |
| `packages/ai-parrot-tools/tests/scraping/test_driver_factory.py` | MODIFY | add forwarding tests (playwright yes, obscura never) |

---

Implementation correction: the live toolkit session uses `_PlaywrightSetup.get_driver()` in
`driver_context.py`, not `DriverFactory.create()`. Forward the recording directory there too.

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py` | MODIFY | Forward recording directory on live toolkit path |
| `packages/ai-parrot-tools/tests/scraping/test_driver_context.py` | MODIFY | Exercise live registry config forwarding and backend isolation |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.toolkit_models import DriverConfig   # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:71
from parrot_tools.scraping.toolkit import WebScrapingToolkit     # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:266
from parrot_tools.scraping.driver_factory import DriverFactory   # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:31
```
Tests use the legacy redirected path (`from parrot.tools.scraping...`) —
match each existing test file's current import style.

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:71-136
class DriverConfig(BaseModel):
    ...
    obscura_allow_private_network: bool = False   # line 134 — last field; new field goes right after

    def merge(self, overrides: Optional[Dict[str, Any]] = None) -> DriverConfig:  # line 136
        """Return a new DriverConfig with overrides applied. Never mutates self."""

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:306-358
class WebScrapingToolkit(AbstractToolkit):
    def __init__(
        self,
        ...,
        confine_paths: bool = False,   # line 329 — new param goes right after
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config = DriverConfig(...)    # lines ~312-343 — do NOT add record_video_dir here, files_root isn't ready yet
        self._session_based = session_based
        self._session_driver: AbstractDriver | None = None
        self._registry: PlanRegistry | None = None
        self._llm_client = llm_client
        self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")  # line 358 — resolution logic goes right after this line
        self.confine_paths = bool(confine_paths)
        self.logger = logging.getLogger(__name__)

    @property
    def files_root(self) -> Path:   # line 370
        """Where the actions of a confined toolkit may read and write files: <plans_dir>/files."""
        return self._plans_dir / "files"

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:98-129
if driver_type == "playwright":
    ...
    pw_config = PlaywrightConfig(           # line 108
        browser_type=pw_browser,
        headless=headless,
        slow_mo=config.get("slow_mo", 0),
        timeout=config.get("default_timeout", 30),
        viewport=config.get("viewport"),
        locale=config.get("locale"),
        timezone=config.get("timezone"),
        proxy=config.get("proxy"),
        mobile=config.get("mobile", False),
        device_name=config.get("device_name"),
        ignore_https_errors=config.get("ignore_https_errors", False),
        storage_state=config.get("storage_state"),
        user_data_dir=config.get("user_data_dir"),
        channel=channel,
        executable_path=resolve_browser_binary(      # line 123 — new kwarg goes right after this call's closing paren
            config.get("browser_binary") or config.get("executable_path"), browser, channel
        ),
    )                                        # line 127
    return PlaywrightDriver(pw_config)        # line 128
if driver_type == "obscura":                  # line ~131 — DO NOT add record_video_dir to this branch's PlaywrightConfig(...) at line 141
```

```python
# drivers/playwright_config.py — PlaywrightConfig already has this field, no change needed:
@dataclass
class PlaywrightConfig:
    record_video_dir: Optional[str] = None
```

### Does NOT Exist
- ~~`DriverConfig.record_video` (bool field)~~ — the field on `DriverConfig`
  is `record_video_dir: Optional[str]`. The bare `bool` toggle lives only
  on `WebScrapingToolkit.__init__`'s `record_video` parameter — it is
  resolved into the string path before it ever reaches `DriverConfig`.
- ~~A `record_video_dir` key in the `"obscura"` branch's `PlaywrightConfig(...)`
  call~~ — must never be added there (spec Non-Goal).
- ~~Computing `files_root` inside the `DriverConfig(...)` constructor
  call~~ — `self._plans_dir` does not exist yet at that point in
  `__init__`; the resolution MUST happen after `self._plans_dir` is
  assigned (`toolkit.py:358`).

### Edit Sites (from spec §6, re-verified 2026-10-27 — HEAD `f7a5ff24d`; re-check with
`grep -c` before use since TASK-4839 lands first — its edits are
single-line literal swaps that do not shift any line numbers below)
| File | Anchor | Occurrences |
|---|---|---|
| `toolkit_models.py:134` | `obscura_allow_private_network: bool = False` | 1 |
| `toolkit.py:329` | `confine_paths: bool = False,` | 1 |
| `toolkit.py:358` | `self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")` | 1 |
| `driver_factory.py:123` | `executable_path=resolve_browser_binary(` | 1 |

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_driver_factory.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py#DriverConfig",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py#WebScrapingToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py#DriverFactory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `DriverConfig.merge()` never mutates in place — always
  `self._config = self._config.merge({...})`, matching
  `WebBrowsingToolkit.__init__`'s existing pattern for
  `user_data_dir`/`profile_directory`/`browser_channel`.
- `files_root` returns `self._plans_dir / "files"` (a `pathlib.Path`) —
  the recordings dir is `self.files_root / "recordings"`, converted to
  `str(...)` before it goes into `DriverConfig.record_video_dir` (a plain
  `Optional[str]`, not a `Path`).
- No filesystem directory creation needed here — Playwright itself
  creates `record_video_dir` on disk if it doesn't exist when the context
  starts recording (standard Playwright behavior); this task only wires
  the path through.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py:139-148` —
  `WebBrowsingToolkit.__init__`'s existing `self._config = self._config.merge({...})`
  call is the established pattern for post-construction config overrides.

---

## Implementation Blueprint

### Steps (in order)
1. Add `record_video_dir: Optional[str] = None` to `DriverConfig` right
   after `obscura_allow_private_network` — *why*: keeps the new field
   grouped with the other optional/advanced fields, consistent with the
   class's existing layout.
2. Add `record_video: bool = False` to `WebScrapingToolkit.__init__`'s
   signature right after `confine_paths` — *why*: mirrors `confine_paths`,
   the closest existing analogue (a boolean opt-in flag resolved after
   construction, not baked into the initial `DriverConfig(...)` call).
3. Insert the resolution block right after
   `self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")`
   — *why*: `files_root` (`self._plans_dir / "files"`) is only computable
   once `self._plans_dir` exists; inlining this into the earlier
   `DriverConfig(...)` call would reference `self._plans_dir` before it
   is set (`AttributeError`).
4. Add `record_video_dir=config.get("record_video_dir")` to the
   `"playwright"` branch's `PlaywrightConfig(...)` call only — *why*:
   `config.get(...)` returns `None` when absent (safe default,
   `PlaywrightConfig.record_video_dir` already defaults to `None`), and
   restricting this to the `"playwright"` branch keeps the `"obscura"`
   branch's own `PlaywrightConfig(...)` call (a few lines below,
   `driver_factory.py:141`) untouched — do not edit it.
5. Add the net-new tests from spec §4 for this module.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'obscura_allow_private_network: bool = False' packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py)
# AFTER — insert below `obscura_allow_private_network: bool = False` (verified: toolkit_models.py:134)
    record_video_dir: Optional[str] = None
    """Confined directory Playwright should write session ``.webm``
    recordings to. Set by :class:`WebScrapingToolkit` when
    ``record_video=True``; ``None`` means recording is off. Only consumed
    by :meth:`DriverFactory.create`'s ``"playwright"`` branch — never
    forwarded for ``"obscura"`` or ``"selenium"``."""
```
**Why this shape**: a plain optional field, same style as the other
`Optional[str] = None` fields already on this `BaseModel`. The docstring
documents who sets it and the `"obscura"` exclusion up front, so a future
reader does not need to chase the driver_factory.py branch to learn it.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'confine_paths: bool = False,' packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py)
# AFTER — insert below `confine_paths: bool = False,` (verified: toolkit.py:329), as a new __init__ parameter:
        record_video: bool = False,
```
```python
# occurrences: 1 (verified: grep -c 'self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")' packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py)
# AFTER — insert below `self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")` (verified: toolkit.py:358)
        if record_video:
            self._config = self._config.merge(
                {"record_video_dir": str(self.files_root / "recordings")}
            )
```
**Why this shape**: `record_video` is a plain opt-in toggle, resolved
into a confined absolute path the moment `self._plans_dir` exists —
`self.files_root` is already a `@property` on this class
(`toolkit.py:370`), so no duplicate path-building logic is introduced.
When `record_video=False` (the default), `self._config.record_video_dir`
stays `None` — no `merge()` call at all, zero overhead for the common
case.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'executable_path=resolve_browser_binary(' packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py)
# AFTER — insert below the `executable_path=resolve_browser_binary(...)` call, inside the SAME
# PlaywrightConfig(...) constructor call for the "playwright" branch (verified: driver_factory.py:123-126, closing paren at :126 before the outer PlaywrightConfig(...) close at :127)
            pw_config = PlaywrightConfig(
                browser_type=pw_browser,
                headless=headless,
                slow_mo=config.get("slow_mo", 0),
                timeout=config.get("default_timeout", 30),
                viewport=config.get("viewport"),
                locale=config.get("locale"),
                timezone=config.get("timezone"),
                proxy=config.get("proxy"),
                mobile=config.get("mobile", False),
                device_name=config.get("device_name"),
                ignore_https_errors=config.get("ignore_https_errors", False),
                storage_state=config.get("storage_state"),
                user_data_dir=config.get("user_data_dir"),
                channel=channel,
                executable_path=resolve_browser_binary(
                    config.get("browser_binary") or config.get("executable_path"), browser, channel
                ),
                record_video_dir=config.get("record_video_dir"),
            )
```
**Why this shape**: this is the FULL existing `pw_config = PlaywrightConfig(...)`
call for the `"playwright"` branch with exactly one new kwarg appended —
every other line is unchanged, shown in full so the single insertion
point is unambiguous. **Do NOT apply this same addition to the
`"obscura"` branch's separate `PlaywrightConfig(...)` call a few lines
below (`driver_factory.py:141-156`)** — that call must stay exactly as it
is today (spec Non-Goal).

Also add, inside `class TestDriverFactoryCreate` in
`test_driver_factory.py` (new tests, after
`test_driver_factory_create_explicit_selenium_still_works` from
TASK-4839):
```python
    @patch("parrot.tools.scraping.drivers.playwright_driver.PlaywrightDriver")
    @patch("parrot.tools.scraping.drivers.playwright_config.PlaywrightConfig")
    def test_driver_factory_forwards_record_video_dir_playwright(self, mock_config, mock_cls):
        """record_video_dir reaches PlaywrightConfig for driver_type="playwright" (FEAT-763)."""
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        DriverFactory.create({"driver_type": "playwright", "record_video_dir": "/x/recordings"})
        _, kwargs = mock_config.call_args
        assert kwargs["record_video_dir"] == "/x/recordings"
```
Inside `class TestDriverFactoryObscura` (new test):
```python
    @patch("parrot.tools.scraping.drivers.playwright_driver.PlaywrightDriver")
    @patch("parrot.tools.scraping.drivers.playwright_config.PlaywrightConfig")
    def test_driver_factory_obscura_never_forwards_record_video_dir(self, mock_config, mock_cls):
        """record_video_dir is never forwarded for driver_type="obscura" (FEAT-763 Non-Goal)."""
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        DriverFactory.create({"driver_type": "obscura", "record_video_dir": "/x/recordings"})
        _, kwargs = mock_config.call_args
        assert "record_video_dir" not in kwargs
```
**Why**: directly exercises the one behavioral fork this task must get
right — forwarded for `"playwright"`, never for `"obscura"`. Read the
existing `TestDriverFactoryObscura.test_factory_creates_obscura_playwright_driver`
(`test_driver_factory.py:68-...`) first to confirm the exact mock-call
pattern this file already uses for the obscura branch before writing the
new test.

### `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` (MODIFY)
Add, inside `class TestConstructor` (new tests):
```python
    def test_record_video_resolves_confined_dir(self, tmp_path, mock_llm_client):
        tk = WebScrapingToolkit(
            record_video=True,
            plans_dir=tmp_path / "plans",
            llm_client=mock_llm_client,
        )
        assert tk._config.record_video_dir == str(tmp_path / "plans" / "files" / "recordings")

    def test_record_video_false_leaves_record_video_dir_none(self, toolkit):
        assert toolkit._config.record_video_dir is None
```
**Why**: pins the exact resolved path (spec Acceptance Criteria) and the
no-op default case, using the file's existing `toolkit`/`mock_llm_client`
fixtures (`test_toolkit.py:33-44`) — no new fixtures needed.

### FILL IN checklist
*(none — every edit above is fully decided; no judgement calls remain)*

---

## Acceptance Criteria

- [ ] `WebScrapingToolkit(record_video=True)` resolves `._config.record_video_dir` to `<files_root>/recordings`.
- [ ] `WebScrapingToolkit()` (default `record_video=False`) leaves `._config.record_video_dir` as `None`.
- [ ] `DriverFactory.create({"driver_type": "playwright", "record_video_dir": "/x"})` passes `record_video_dir="/x"` into `PlaywrightConfig(...)`.
- [ ] `DriverFactory.create({"driver_type": "obscura", "record_video_dir": "/x"})` never passes `record_video_dir` into that branch's `PlaywrightConfig(...)`.
- [ ] `DriverFactory.create({"driver_type": "selenium", ...})` is unaffected (no `record_video_dir` concept on the Selenium path).
- [ ] All tests in the Validation Commands below pass.
- [ ] `ruff check` clean on the three modified source files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_driver_factory.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py -q`

---

## Test Specification

See the Implementation Blueprint above — every new test body is given
verbatim there (spec §4's M2 test list:
`test_record_video_resolves_confined_dir`,
`test_record_video_false_leaves_record_video_dir_none`,
`test_driver_factory_forwards_record_video_dir_playwright`,
`test_driver_factory_obscura_never_forwards_record_video_dir`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
2. **Read the spec** at `sdd/specs/browsing-playwright-default-and-screencast.spec.md` for full context
3. **Check dependencies** — `TASK-4839` must be `"done"` in the per-spec index before starting (file overlap: same 3 source files)
4. **Verify the Codebase Contract** — before writing ANY code, re-run the
   `grep -c` commands above to confirm anchors still hold after
   TASK-4839's edits landed (its edits are same-line literal swaps —
   should not shift any of this task's anchors)
5. **Update status** in `sdd/tasks/index/browsing-playwright-default-and-screencast.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — apply the Implementation Blueprint edits exactly
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4840 browsing-playwright-default-and-screencast verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4840
- Feature: browsing-playwright-default-and-screencast
- Implementation SHA: 495af874bd085be5def985b779f4f875cde3d903
- Closed at (UTC): 2026-10-27T21:39:19+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 2 |
| fix_commits | 0 |
| summary | Opt-in recording config wired through factory and live session registry; 98 tests passed. |
