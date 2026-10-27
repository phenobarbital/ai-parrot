import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

S = Path(sys.argv[1])
CASES = {
    "flowchart": ('flowchart TD\n    A[Start] -->|go| B[End]\n', ["Start", "End", "go"]),
    "class": ('classDiagram\n    class Animal {\n      +String name\n    }\n    Animal <|-- Dog\n', ["Animal", "Dog", "name"]),
}
async def main():
    out = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = await browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto((S / "index.html").as_uri())
        await page.add_script_tag(path=str(S / "bundle.js"))
        for i, (name, (src, labels)) in enumerate(CASES.items()):
            res = await page.evaluate("([s, id]) => window.runSmoke(s, id)", [src, f"a2ui-mermaid-{i}"])
            clean = res["clean"]
            await page.evaluate("(h) => { document.getElementById('out').innerHTML = h }", clean)
            text = await page.evaluate("() => document.getElementById('out').innerText || document.getElementById('out').textContent")
            out[name] = {
                "raw_svg_len": res["raw"], "clean_svg_len": len(clean),
                "labels_visible": {label: (label in text) for label in labels},
                "has_foreignObject": "foreignObject" in clean, "has_script": "<script" in clean.lower(),
            }
            await page.screenshot(path=str(S / f"{name}.png"))
        out["page_errors"] = errors
        await browser.close()
    print(json.dumps(out, indent=2))
asyncio.run(main())
