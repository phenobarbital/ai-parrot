---
id: F001
query_id: Q001
type: read
intent: Locate the WebscrapingToolkit and its JSON/DSL definition layer — the reuse anchor for the whole proposal
executed_at: 2026-08-23T09:22:00Z
depth: 0
parent_id: null
---

# F001 — The JSON browser-action DSL already exists: 27 typed `BrowserAction` Pydantic models

## Summary

The "lenguaje json para definir directivas de accion" the source proposes to
*create* is already implemented. `parrot_tools/scraping/models.py` defines an
abstract `BrowserAction(BaseModel, ABC)` with `get_action_type()` and **27
concrete typed action subclasses**, covering navigation, form interaction,
extraction, session/cookie handling, human-in-the-loop pauses, file upload and
download, plus control flow (`Loop`, `Conditional`). Crucially the set already
includes the four primitives the Hooba use case depends on most —
`Authenticate`, `AwaitHuman`, `UploadFile`, `WaitForDownload`.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 14-35
  symbol: `BrowserAction`
  excerpt: |
    class BrowserAction(BaseModel, ABC):
        ...
        def get_action_type(self) -> str:

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 37-757
  symbol: "27 BrowserAction subclasses"
  excerpt: |
    Navigate(37) Click(45) Fill(66) Hover(76) Type(87) Extract(146)
    ExtractJsonLd(192) Submit(230) Select(242) Evaluate(293) PressKey(316)
    Refresh(326) Back(334) Scroll(342) GetCookies(388) SetCookies(397)
    Wait(407) Authenticate(478) AwaitHuman(514) AwaitKeyPress(534)
    AwaitBrowserEvent(549) GetText(570) Screenshot(579) GetHTML(598)
    WaitForDownload(612) UploadFile(633) Conditional(651) Loop(679)

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 758-835
  symbol: `ScrapingStep`, `ScrapingSelector`, `ScrapingResult`
  excerpt: |
    class ScrapingStep:   # wraps one BrowserAction + metadata

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py`
  lines: 59-110
  symbol: `ScrapingPlan`
  excerpt: |
    class ScrapingPlan(BaseModel):
        url: str
        objective: str
        steps: List[Dict[str, Any]]       # <-- steps are stored UNTYPED
        selectors: Optional[List[Dict[str, Any]]] = None
        browser_config: Optional[Dict[str, Any]] = None
        fingerprint: str = ""

## Notes

Tension worth recording: `ScrapingPlan.steps` is `List[Dict[str, Any]]` — the
persisted JSON is *not* validated against the typed `BrowserAction` union at
plan-load time. The legacy `tool.py` parses dicts into `ScrapingStep`/typed
actions at execution time. So the DSL is typed in flight but untyped at rest.
For financial operations this is the difference between "malformed plan fails
at step 7 mid-invoice" and "malformed plan is rejected before the browser opens".
