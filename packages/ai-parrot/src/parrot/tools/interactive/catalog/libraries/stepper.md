---
name: stepper
description: Tiny dependency-free multi-step / wizard controller (vanilla JS, no CDN).
category: wizard
scope: inline
global_var: Stepper
---

## Inline
```js
window.Stepper = (function () {
  function init(rootSelector) {
    const root = document.querySelector(rootSelector);
    if (!root) return null;
    const steps = Array.from(root.querySelectorAll('[data-step]'));
    let idx = 0;
    function render() {
      steps.forEach((s, i) => { s.hidden = (i !== idx); });
      const prev = root.querySelector('[data-stepper-prev]');
      const next = root.querySelector('[data-stepper-next]');
      const ind = root.querySelector('[data-stepper-indicator]');
      if (prev) prev.disabled = (idx === 0);
      if (next) next.textContent = (idx === steps.length - 1) ? 'Finish' : 'Next';
      if (ind) ind.textContent = 'Step ' + (idx + 1) + ' of ' + steps.length;
    }
    root.addEventListener('click', (e) => {
      if (e.target.closest('[data-stepper-next]') && idx < steps.length - 1) { idx++; render(); }
      if (e.target.closest('[data-stepper-prev]') && idx > 0) { idx--; render(); }
    });
    render();
    return {
      next: () => { idx = Math.min(idx + 1, steps.length - 1); render(); },
      prev: () => { idx = Math.max(idx - 1, 0); render(); },
      goto: (i) => { idx = Math.max(0, Math.min(i, steps.length - 1)); render(); },
    };
  }
  return { init };
})();
```

## Usage
```html
<div id="wizard">
  <div data-stepper-indicator></div>
  <section data-step><h2>Step 1</h2></section>
  <section data-step hidden><h2>Step 2</h2></section>
  <button data-stepper-prev>Back</button>
  <button data-stepper-next>Next</button>
</div>
<script>const wiz = Stepper.init('#wizard');</script>
```

## Types
```ts
interface StepperApi { next(): void; prev(): void; goto(i: number): void; }
declare const Stepper: { init(rootSelector: string): StepperApi | null };
```
