export type Dispose = () => void;

export function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  ...children: Array<HTMLElement | Text | string>
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const ch of children) node.append(typeof ch === "string" ? document.createTextNode(ch) : ch);
  return node;
}

export function on<T extends EventTarget>(
  target: T,
  type: string,
  handler: EventListenerOrEventListenerObject,
  options?: AddEventListenerOptions
): Dispose {
  target.addEventListener(type, handler, options);
  return () => target.removeEventListener(type, handler, options);
}

export function cssPx(n: number): string {
  return `${Math.round(n)}px`;
}

export function uid(prefix = "id"): string {
  const s = Math.random().toString(36).slice(2, 10);
  return `${prefix}-${s}`;
}

export function stop(ev: Event): void {
  ev.preventDefault();
  ev.stopPropagation();
}
