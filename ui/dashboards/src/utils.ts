// utils.ts - Funciones utilitarias tipadas
export type Dispose = () => void;

export const clamp = (n: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, n));

export const cssPx = (n: number): string => `${Math.round(n)}px`;

export const uid = (prefix = "id"): string =>
  `${prefix}-${Math.random().toString(36).slice(2, 10)}`;

export const stop = (ev: Event): void => {
  ev.preventDefault();
  ev.stopPropagation();
};

type Attrs = Record<string, string | boolean | number>;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: (string | Node)[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (typeof v === "boolean") {
      if (v) node.setAttribute(k, "");
    } else {
      node.setAttribute(k, String(v));
    }
  }
  for (const ch of children) {
    node.append(typeof ch === "string" ? document.createTextNode(ch) : ch);
  }
  return node;
}

export function on<K extends keyof HTMLElementEventMap>(
  target: EventTarget,
  type: K,
  handler: (ev: HTMLElementEventMap[K]) => void,
  options?: AddEventListenerOptions
): Dispose {
  target.addEventListener(type, handler as EventListener, options);
  return () => target.removeEventListener(type, handler as EventListener, options);
}

// Debounce helper
export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  ms: number
): T {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  return ((...args: unknown[]) => {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), ms);
  }) as T;
}

// Local storage helpers con tipado
export const storage = {
  get<T>(key: string): T | null {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  },
  set<T>(key: string, value: T): void {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // storage full or unavailable
    }
  },
  remove(key: string): void {
    localStorage.removeItem(key);
  }
};