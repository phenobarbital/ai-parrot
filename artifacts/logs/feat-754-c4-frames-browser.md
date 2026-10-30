# FEAT-754 / TASK-4792 — rendered C4 boundary-frame evidence

- Date: 2026-10-27
- Browser: headless Google Chrome 153.0.8010.52 (driven by Python Playwright, real canvas renderer)
- ECharts: 6.1.0 (the installed `node_modules/echarts/dist/echarts.min.js`)
- Code under test: the real `attachFrameProjection` / `buildGraphOption` exports of
  `A2UIGraph.svelte`, compiled with vite + `@sveltejs/vite-plugin-svelte` into an IIFE (no mocks;
  `convertToPixel` is the live chart's).
- Fixture: nested boundaries — `shop` (system: `web`) contains `core` (container, parent `shop`:
  `api`, `db`); `customer` outside. Complete positions.
- `ok` = every member's projected center lies inside its frame rect, `core` rect lies inside `shop`
  rect, and `customer` lies outside `shop`.
- `graphic_setOption_idle_delta` = count of `setOption({graphic})` calls during 1 s idle after the
  scenario settled (0 ⇒ no render loop).
- Pan = real mouse drag (+80,+60 px) on the canvas; zoom = real wheel (-300) — both emit `graphRoam`.

## Results (rects in viewport px)

| Scenario | ok | shop rect | core rect | idle setOption |
|---|---|---|---|---|
| size 800x600 | True | 336,108 448x416 | 368,428 384x64 | 0 |
| size 500x400 (resize) | True | 210,80 280x260 | 230,280 240x40 | 0 |
| after pan (drag +80,+60) | True | 290,140 280x260 | 310,340 240x40 | 0 |
| after zoom (wheel in) | True | 294,134 308x286 | 316,354 264x44 | 0 |
| same-geometry base option replacement (notMerge) | True | 210,80 280x260 | 230,280 240x40 | 0 |
| remount (cleanup+dispose+mount) | True | 210,80 280x260 | 230,280 240x40 | 0 |

- Switch to non-C4 (`kind: 'flowchart'`): owned frame ids remaining = [] (removed via `$action: 'remove'`).
- After cleanup + dispose + remount: `rendered` handlers on the new instance = 1 (exactly one, no leak). ECharts stores the roam handler under the lowercased key `graphroam`, so the `graphRoam` key read returned 0; the roam subscription is evidenced by reprojection in the pan/zoom rows.
- Two container sizes: 800x600 then resized to 500x400 via `chart.resize()` — frames reprojected from the
  resulting `rendered` event.
- Same-geometry base option replacement: `setOption(buildGraphOption(props), {notMerge: true})` wiped the
  graphic; the missing owned ids were detected and the frames reinstalled with identical geometry.

## Raw output
```json
[
 {
  "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/153.0.0.0 Safari/537.36",
  "echarts": "6.1.0"
 },
 {
  "scenario": "size 800x600",
  "ok": true,
  "shop": {
   "x": 336,
   "y": 108,
   "width": 448,
   "height": 416
  },
  "core": {
   "x": 368,
   "y": 428,
   "width": 384,
   "height": 64
  },
  "centers": {
   "customer": [
    80,
    140
   ],
   "web": [
    400,
    140
   ],
   "api": [
    400,
    460
   ],
   "db": [
    720,
    460
   ]
  },
  "graphic_setOption_idle_delta": 0
 },
 {
  "scenario": "size 500x400 (resize)",
  "ok": true,
  "shop": {
   "x": 210,
   "y": 80,
   "width": 280,
   "height": 260
  },
  "core": {
   "x": 230,
   "y": 280,
   "width": 240,
   "height": 40
  },
  "centers": {
   "customer": [
    50,
    100
   ],
   "web": [
    250,
    100
   ],
   "api": [
    250,
    300
   ],
   "db": [
    450,
    300
   ]
  },
  "graphic_setOption_idle_delta": 0
 },
 {
  "scenario": "after pan (drag +80,+60)",
  "ok": true,
  "shop": {
   "x": 290,
   "y": 140,
   "width": 280,
   "height": 260
  },
  "core": {
   "x": 310,
   "y": 340,
   "width": 240,
   "height": 40
  },
  "centers": {
   "customer": [
    130,
    160
   ],
   "web": [
    330,
    160
   ],
   "api": [
    330,
    360
   ],
   "db": [
    530,
    360
   ]
  },
  "graphic_setOption_idle_delta": 0
 },
 {
  "scenario": "after zoom (wheel in)",
  "ok": true,
  "shop": {
   "x": 294,
   "y": 134,
   "width": 308,
   "height": 286
  },
  "core": {
   "x": 316,
   "y": 354,
   "width": 264,
   "height": 44
  },
  "centers": {
   "customer": [
    117.99999999999997,
    156
   ],
   "web": [
    338,
    156
   ],
   "api": [
    338,
    376
   ],
   "db": [
    558,
    376
   ]
  },
  "graphic_setOption_idle_delta": 0
 },
 {
  "scenario": "same-geometry base option replacement (notMerge)",
  "ok": true,
  "shop": {
   "x": 210,
   "y": 80,
   "width": 280,
   "height": 260
  },
  "core": {
   "x": 230,
   "y": 280,
   "width": 240,
   "height": 40
  },
  "centers": {
   "customer": [
    50,
    100
   ],
   "web": [
    250,
    100
   ],
   "api": [
    250,
    300
   ],
   "db": [
    450,
    300
   ]
  },
  "graphic_setOption_idle_delta": 0
 },
 {
  "scenario": "switch to non-C4",
  "frame_ids": []
 },
 {
  "scenario": "remount (cleanup+dispose+mount)",
  "ok": true,
  "shop": {
   "x": 210,
   "y": 80,
   "width": 280,
   "height": 260
  },
  "core": {
   "x": 230,
   "y": 280,
   "width": 240,
   "height": 40
  },
  "centers": {
   "customer": [
    50,
    100
   ],
   "web": [
    250,
    100
   ],
   "api": [
    250,
    300
   ],
   "db": [
    450,
    300
   ]
  },
  "graphic_setOption_idle_delta": 0
 },
 {
  "scenario": "handler counts after remount",
  "rendered": 1,
  "graphRoam": 0
 }
]
```
