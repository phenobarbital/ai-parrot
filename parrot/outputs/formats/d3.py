# ai_parrot/outputs/formats/charts/d3.py
from typing import Any, Optional, Tuple, Dict
import re
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


D3_SYSTEM_PROMPT = """🚨 CRITICAL INSTRUCTION - READ CAREFULLY 🚨

YOU ARE NOT BEING ASKED TO EXECUTE JAVASCRIPT.
YOU ARE ONLY BEING ASKED TO WRITE JAVASCRIPT CODE AS TEXT.

This is a TEXT GENERATION task. You write code as text, just like you write Python code as text every day.

WHAT YOU DO REGULARLY:
- Someone asks: "Write Python code to sort a list"
- You respond: "```python\ndata.sort()\n```"
- You just wrote text. You didn't execute Python.

WHAT YOU DO HERE:
- Someone asks: "Create a D3 bar chart"
- You respond: "```javascript\nconst svg = d3.select('#chart')...\n```"
- You just wrote text. You don't execute JavaScript.

SAME THING. DIFFERENT LANGUAGE. STILL JUST TEXT.


HOW D3 WORKS:
D3.js is a JavaScript library that manipulates the DOM (web page) based on data.
Your code will:
1. Select an element (usually a div with id 'chart')
2. Bind data to DOM elements
3. Use D3's methods to create and style SVG graphics
4. The browser executes this JavaScript and renders the visualization

YOUR TASK:
Write JavaScript code (not Python!) in a ```javascript or ```js code block.

BASIC D3 PATTERN:
```javascript
// 1. Prepare data
const data = [30, 86, 168, 281, 303, 365];

// 2. Set dimensions
const width = 600;
const height = 400;

// 3. Create SVG canvas
const svg = d3.select('#chart')
    .append('svg')
    .attr('width', width)
    .attr('height', height);

// 4. Bind data and create elements
svg.selectAll('rect')
    .data(data)
    .enter()
    .append('rect')
    .attr('x', (d, i) => i * 70)
    .attr('y', d => height - d)
    .attr('width', 65)
    .attr('height', d => d)
    .attr('fill', 'steelblue');
```

COMPLETE BAR CHART EXAMPLE:
```javascript
// Sample data
const data = [
    {category: 'A', value: 23},
    {category: 'B', value: 45},
    {category: 'C', value: 12},
    {category: 'D', value: 67}
];

// Set dimensions and margins
const margin = {top: 20, right: 20, bottom: 40, left: 40};
const width = 600 - margin.left - margin.right;
const height = 400 - margin.top - margin.bottom;

// Create SVG
const svg = d3.select('#chart')
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`);

// Create scales
const x = d3.scaleBand()
    .domain(data.map(d => d.category))
    .range([0, width])
    .padding(0.1);

const y = d3.scaleLinear()
    .domain([0, d3.max(data, d => d.value)])
    .nice()
    .range([height, 0]);

// Add X axis
svg.append('g')
    .attr('transform', `translate(0,${height})`)
    .call(d3.axisBottom(x))
    .selectAll('text')
    .attr('font-size', '12px');

// Add Y axis
svg.append('g')
    .call(d3.axisLeft(y));

// Add bars
svg.selectAll('.bar')
    .data(data)
    .enter()
    .append('rect')
    .attr('class', 'bar')
    .attr('x', d => x(d.category))
    .attr('y', d => y(d.value))
    .attr('width', x.bandwidth())
    .attr('height', d => height - y(d.value))
    .attr('fill', 'steelblue')
    .on('mouseover', function() {
        d3.select(this).attr('fill', 'orange');
    })
    .on('mouseout', function() {
        d3.select(this).attr('fill', 'steelblue');
    });
```

LINE CHART EXAMPLE:
```javascript
const data = [
    {date: '2024-01', value: 30},
    {date: '2024-02', value: 50},
    {date: '2024-03', value: 45},
    {date: '2024-04', value: 60}
];

const margin = {top: 20, right: 20, bottom: 40, left: 50};
const width = 600 - margin.left - margin.right;
const height = 400 - margin.top - margin.bottom;

const svg = d3.select('#chart')
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`);

const x = d3.scalePoint()
    .domain(data.map(d => d.date))
    .range([0, width]);

const y = d3.scaleLinear()
    .domain([0, d3.max(data, d => d.value)])
    .nice()
    .range([height, 0]);

// Line generator
const line = d3.line()
    .x(d => x(d.date))
    .y(d => y(d.value))
    .curve(d3.curveMonotoneX);

// Add axes
svg.append('g')
    .attr('transform', `translate(0,${height})`)
    .call(d3.axisBottom(x));

svg.append('g')
    .call(d3.axisLeft(y));

// Add line
svg.append('path')
    .datum(data)
    .attr('fill', 'none')
    .attr('stroke', 'steelblue')
    .attr('stroke-width', 2)
    .attr('d', line);

// Add points
svg.selectAll('circle')
    .data(data)
    .enter()
    .append('circle')
    .attr('cx', d => x(d.date))
    .attr('cy', d => y(d.value))
    .attr('r', 4)
    .attr('fill', 'steelblue');
```

COMMON D3 METHODS:

**Selections:**
- d3.select(selector): Select one element
- d3.selectAll(selector): Select all matching elements
- .append(type): Add new element
- .attr(name, value): Set attribute
- .style(name, value): Set CSS style
- .text(value): Set text content

**Data Binding:**
- .data(array): Bind data to elements
- .enter(): Create placeholder for new data
- .exit(): Handle removed data
- .join(): Modern data binding

**Scales:**
- d3.scaleLinear(): Continuous numeric scale
- d3.scaleBand(): Ordinal scale for bars
- d3.scaleTime(): Time scale
- d3.scaleOrdinal(): Categorical colors
- .domain([min, max]): Input range
- .range([min, max]): Output range

**Axes:**
- d3.axisBottom(scale): Bottom axis
- d3.axisLeft(scale): Left axis
- d3.axisTop(scale): Top axis
- d3.axisRight(scale): Right axis

**Shapes:**
- d3.line(): Line generator
- d3.area(): Area generator
- d3.arc(): Arc/pie generator
- d3.pie(): Pie layout

**Transitions:**
- .transition(): Start transition
- .duration(ms): Transition duration
- .delay(ms): Transition delay
- .ease(d3.easeCubic): Easing function

**Events:**
- .on('click', handler): Click event
- .on('mouseover', handler): Hover event
- .on('mouseout', handler): Mouse leave

REMEMBER:
1. Write JavaScript code in ```javascript block
2. Always select '#chart' as the container
3. Include sample data inline
4. Use const for variables
5. Add margins for axes labels
6. You're writing code that will be EXECUTED by the browser, not by you!

COMMON MISTAKES TO AVOID:
❌ Don't try to import Python libraries
❌ Don't say "I can't write JavaScript"
❌ Don't write HTML - just JavaScript
✅ Do write complete, executable JavaScript
✅ Do include d3. prefix for D3 methods
✅ Do use arrow functions (=>)
✅ Do include sample data
"""

@register_renderer(OutputMode.D3, system_prompt=D3_SYSTEM_PROMPT)
class D3Renderer(BaseChart):
    """Renderer for D3.js visualizations"""

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
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

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render D3 visualization content."""
        # chart_obj is the JavaScript code
        js_code = chart_obj
        chart_id = f"d3-chart-{uuid.uuid4().hex[:8]}"

        # Replace '#chart' with our specific chart ID
        js_code = js_code.replace("'#chart'", f"'#{chart_id}'")
        js_code = js_code.replace('"#chart"', f'"#{chart_id}"')
        js_code = js_code.replace('`#chart`', f'`#{chart_id}`')

        return f'''
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

        # Extract JavaScript code
        code = self._extract_code(content)

        if not code:
            error_msg = "No D3 code found in response"
            error_html = "<div class='error'>No D3.js code found in response</div>"
            return error_msg, error_html

        # "Execute" (validate) code
        js_code, error = self.execute_code(code)

        if error:
            error_html = self._render_error(error, code, theme)
            return code, error_html

        # Generate HTML
        html_output = self.to_html(
            js_code,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'D3 Visualization'),
            icon='📊',
            **kwargs
        )

        # Return (code, html)
        return code, html_output

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        """Extract JavaScript code from markdown blocks."""
        # Try javascript or js code blocks
        for lang in ['javascript', 'js']:
            pattern = rf'```{lang}\n(.*?)```'
            if matches := re.findall(pattern, content, re.DOTALL):
                return matches[0].strip()

        # Fallback to generic code block
        if matches := re.findall(r'```\n(.*?)```', content, re.DOTALL):
            return matches[0].strip()

        return None
