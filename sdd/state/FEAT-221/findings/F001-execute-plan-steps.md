---
id: F001
query_id: Q001
type: read
intent: Understand execute_plan_steps signature, return type, and driver interaction model
executed_at: 2026-06-04T00:00:00Z
duration_ms: 48687
parent_id: null
depth: 0
---

# F001 — execute_plan_steps is a stateless step runner that receives a pre-initialized driver

## Summary

`execute_plan_steps` (executor.py:41-186) is an async function that runs a list of scraping steps sequentially on a provided `AbstractDriver`. It does NOT manage driver lifecycle, page creation, or browser context — the caller must provide a fully initialized driver. Returns `ScrapingResult` (a dataclass). Error handling is selective abort: `navigate`/`authenticate` failures abort the pipeline; all other action failures are logged and skipped. No retry mechanism. Loop action is **skipped** in the standalone executor (returns True with a warning at line 280-292) — the full Loop implementation lives in `WebScrapingTool` (tool.py:2590-2664).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
  lines: 41-186
  symbol: `execute_plan_steps`
  excerpt: |
    async def execute_plan_steps(
        driver: AbstractDriver,
        plan: Optional[ScrapingPlan] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        selectors: Optional[List[Dict[str, Any]]] = None,
        config: Optional[DriverConfig] = None,
        base_url: Optional[str] = None,
    ) -> ScrapingResult:

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
  lines: 280-292
  symbol: `_dispatch_step` (loop branch)
  excerpt: |
    elif action_type in ("get_cookies", "set_cookies", "authenticate",
        "await_human", "await_keypress", "await_browser_event",
        "upload_file", "wait_for_download", "loop", "conditional"):
        logger.warning("Action '%s' requires the full WebScrapingTool; skipping in standalone executor.", action_type)
        return True

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 834-844
  symbol: `ScrapingResult`
  excerpt: |
    @dataclass
    class ScrapingResult:
        url: str
        content: str
        bs_soup: BeautifulSoup
        extracted_data: Dict[str, Any] = field(default_factory=dict)
        metadata: Dict[str, Any] = field(default_factory=dict)
        timestamp: str = ""
        success: bool = True
        error_message: Optional[str] = None

## Notes

Critical implication for FlowExecutor: since execute_plan_steps expects a pre-initialized driver and doesn't manage pages/contexts, the FlowExecutor must create a driver-like wrapper per Page and pass it in. Also, Loop actions won't work through execute_plan_steps — FlowExecutor nodes that need loops must use WebScrapingTool or reimplement loop dispatch.
