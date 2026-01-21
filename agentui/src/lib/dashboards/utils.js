export const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
export const cssPx = (n) => `${Math.round(n)}px`;
export const uid = (prefix = "id") => `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
export const stop = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
};
export function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (typeof v === "boolean") {
            if (v)
                node.setAttribute(k, "");
        }
        else {
            node.setAttribute(k, String(v));
        }
    }
    for (const ch of children) {
        node.append(typeof ch === "string" ? document.createTextNode(ch) : ch);
    }
    return node;
}
export function on(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    return () => target.removeEventListener(type, handler, options);
}
// Debounce helper
export function debounce(fn, ms) {
    let timeout = null;
    return ((...args) => {
        if (timeout)
            clearTimeout(timeout);
        timeout = setTimeout(() => fn(...args), ms);
    });
}
// Local storage helpers con tipado
export const storage = {
    get(key) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : null;
        }
        catch {
            return null;
        }
    },
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        }
        catch {
            // storage full or unavailable
        }
    },
    remove(key) {
        localStorage.removeItem(key);
    }
};
//# sourceMappingURL=utils.js.map