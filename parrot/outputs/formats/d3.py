# ai_parrot/outputs/formats/charts/d3.py
import contextlib
from typing import Any, Optional, Tuple, Dict, List
import json
import html
import re
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


D3_SYSTEM_PROMPT = """🚨 CRITICAL – OUTPUT FORMAT IS STRICT 🚨

You are generating **text only** — specifically a single fenced ```json block that contains:
- "teaching_steps": array of 3–6 short bullets.
- "javascript": string with **D3 code only** (newlines escaped as \\n).
- Optional: "notes": short string.

ABSOLUTE RULES
1) Do **NOT** use any fence other than ```json. Never use ```javascript.
2) The "javascript" must target **'#chart'** and assume **global d3** (no imports/exports).
3) **No HTML/CSS**: no <!DOCTYPE>, <html>, <head>, <body>, <script>, <style>, <link>.
4) Do not include external scripts, ESM imports, require(), module, etc.
5) If you think HTML is required: **STOP** and instead return the JSON with only D3 code.

🚫 If your output contains any of these substrings, it will be rejected:
"<!DOCTYPE", "<html", "<head", "<body", "<script", "<link", "<style", "import ", "export ", "require("

✅ EXAMPLE (illustrative):
```json
{
  "teaching_steps": [
    "Append an SVG into #chart with margins.",
    "Create time and linear scales.",
    "Render axes and a line path."
  ],
  "javascript": "const margin={top:20,right:20,bottom:30,left:40};\\nconst width=640,height=400;\\nconst svg=d3.select('#chart').append('svg').attr('width',width).attr('height',height);\\n/* more d3 code here */",
  "notes": "Optional clarifications."
}
```
Remember:
* Container is always '#chart'.
* Use the global d3 (no imports).
* Provide complete, runnable D3 code only (no HTML or script tags).
"""


@register_renderer(OutputMode.D3, system_prompt=D3_SYSTEM_PROMPT)
class D3Renderer(BaseChart):
    """Renderer for D3.js visualizations"""

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """
        For D3, we don't execute JavaScript - just validate and return it.
        """
        try:
            # Basic validation - check if it looks like D3 code
            if 'd3.' not in code and 'D3' not in code:
                return None, "Code doesn't appear to use D3.js (no d3. references found)"

            # Return the code itself as the "chart object"
            return code, None

        except Exception as e:
            return None, f"Validation error: {str(e)}"

    def _render_chart_content(
        self,
        chart_obj: Any,
        teaching_steps: Optional[List[str]] = None,
        notes: Optional[str] = None,
        **kwargs
    ) -> str:
        """Render D3 visualization content."""
        # chart_obj is the JavaScript code
        js_code = chart_obj
        chart_id = f"d3-chart-{uuid.uuid4().hex[:8]}"

        # Replace '#chart' with our specific chart ID
        js_code = js_code.replace("'#chart'", f"'#{chart_id}'")
        js_code = js_code.replace('"#chart"', f'"#{chart_id}"')
        js_code = js_code.replace('`#chart`', f'`#{chart_id}`')

        guidance_sections: List[str] = []
        if teaching_steps:
            items = ''.join(f"<li>{html.escape(step)}</li>" for step in teaching_steps)
            guidance_sections.append(
                f"""
        <div class=\"chart-guidance\">
            <h3>How this chart works</h3>
            <ol>{items}</ol>
        </div>
                """
            )

        if notes:
            guidance_sections.append(
                f"""
        <div class=\"chart-note\"><strong>Notes:</strong> {html.escape(notes)}</div>
                """
            )

        guidance_html = '\n'.join(guidance_sections)

        return f'''
        {guidance_html}
        <div id="{chart_id}" style="width: 100%; min-height: 400px;"></div>
        <script type="text/javascript">
            (function() {{
                {js_code}
            }})();
        </script>
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """Convert D3 visualization to HTML."""
        # D3.js library for <head>
        d3_version = kwargs.get('d3_version', '7')
        extra_head = f'''
    <!-- D3.js -->
    <script src="https://d3js.org/d3.v{d3_version}.min.js"></script>
        '''

        kwargs['extra_head'] = extra_head

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """D3 code doesn't have a JSON representation."""
        return {
            'type': 'd3_visualization',
            'code_length': len(chart_obj),
            'note': 'D3 visualizations are JavaScript code, not JSON data'
        }

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'terminal',
        export_format: str = 'html',
        return_code: bool = True,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render D3 visualization."""
        content = self._get_content(response)

        # Extract payload containing instructions and JavaScript code
        payload = self._extract_payload(content)

        if not payload:
            error_msg = (
                "No D3 payload found in response (expected ```json block with a \"javascript\" field)"
            )
            error_html = "<div class='error'>Missing D3 JSON payload in response</div>"
            return error_msg, error_html

        code = payload['javascript']
        teaching_steps = payload.get('teaching_steps', [])
        notes = payload.get('notes')

        # "Execute" (validate) code
        js_code, error = self.execute_code(code)

        if error:
            error_html = self._render_error(error, code, theme)
            return code, error_html

        # Generate HTML
        render_kwargs = dict(kwargs)
        title = render_kwargs.pop('title', 'D3 Visualization')
        render_kwargs['teaching_steps'] = teaching_steps
        if notes:
            render_kwargs['notes'] = notes

        html_output = self.to_html(
            js_code,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=title,
            icon='📊',
            **render_kwargs
        )

        # Return (code, html)
        return code, html_output

    @staticmethod
    def _extract_payload(content: str) -> Optional[Dict[str, Any]]:
        """Extract a D3 payload from raw JSON, ```json fences, ```javascript fences, or HTML <script> tags."""
        # 0) Fast path: raw JSON body (no fences)
        with contextlib.suppress(Exception):
            raw = json.loads(content)
            if isinstance(raw, dict):
                js = raw.get("javascript") or raw.get("code")
                if isinstance(js, str) and js.strip():
                    steps = raw.get("teaching_steps") or []
                    notes = raw.get("notes")
                    return {
                        "javascript": js.strip(),
                        "teaching_steps": [str(s).strip() for s in steps if str(s).strip()] if isinstance(steps, list) else [],
                        "notes": notes.strip() if isinstance(notes, str) else None,
                    }

        # 1) Markdown ```json fences (case-insensitive)
        for block in re.findall(r'```json\s*(.*?)```', content, re.DOTALL | re.IGNORECASE):
            try:
                obj = json.loads(block)
            except Exception:
                continue
            if isinstance(obj, dict):
                js = obj.get("javascript") or obj.get("code")
                if isinstance(js, str) and js.strip():
                    steps = obj.get("teaching_steps") or []
                    notes = obj.get("notes")
                    return {
                        "javascript": js.strip(),
                        "teaching_steps": [str(s).strip() for s in steps if str(s).strip()] if isinstance(steps, list) else [],
                        "notes": notes.strip() if isinstance(notes, str) else None,
                    }

        # 2) Markdown ```javascript / ```js fences → salvage as JS
        for js in re.findall(r'```(?:javascript|js)\s*(.*?)```', content, re.DOTALL | re.IGNORECASE):
            js = js.strip()
            if not js:
                continue
            # If a full HTML doc was embedded in the fence, extract inner <script> contents
            if "<script" in js or "<!DOCTYPE" in js or "<html" in js:
                scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', js, re.IGNORECASE)
                js = "\n".join(s.strip() for s in scripts if s.strip()) or js
            return {"javascript": js, "teaching_steps": [], "notes": None}

        # 3) Raw HTML with <script>…</script>
        if "<script" in content:
            scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', content, re.IGNORECASE)
            if js := "\n".join(s.strip() for s in scripts if s.strip()):
                return {"javascript": js, "teaching_steps": [], "notes": None}

        return None
