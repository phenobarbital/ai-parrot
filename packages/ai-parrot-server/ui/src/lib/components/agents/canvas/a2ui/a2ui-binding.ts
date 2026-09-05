/**
 * A2UI JSON-Pointer (RFC 6901) data-model binding resolution (FEAT-527).
 *
 * Pure TypeScript, no runtime dependency (spec constraint: "do not add npm
 * packages"). Mirrors the backend bake pass's binding resolution (a bound
 * prop is `{"path": "/pointer"}`, resolved against the envelope's flat
 * `dataModel`), but read-only and client-side: the bundled UI renders an
 * ALREADY-baked-or-not envelope either way, resolving on demand.
 */
import type { Binding } from './a2ui-types';

/** True when `v` is a JSON-Pointer binding object (`{"path": string}`). */
export function isBinding(v: unknown): v is Binding {
  return (
    typeof v === 'object' &&
    v !== null &&
    !Array.isArray(v) &&
    typeof (v as Record<string, unknown>).path === 'string'
  );
}

/**
 * Resolve one RFC 6901 JSON Pointer against `dataModel`.
 *
 * Per RFC 6901 §4, each `/`-separated token is unescaped by replacing `~1`
 * with `/` FIRST, then `~0` with `~` — this order matters so a literal
 * `~01` (meaning the single character `~1`) is not double-unescaped.
 *
 * @param path - The pointer, e.g. `/charts/chart-0/rows` or `/a~1b/c~0d`.
 * @param dataModel - The envelope's flat data model object.
 * @returns The resolved value, or `undefined` if any segment is missing.
 */
function resolvePointer(path: string, dataModel: Record<string, unknown>): unknown {
  if (path === '') return dataModel;
  const segments = path.split('/').slice(1).map((seg) => seg.replace(/~1/g, '/').replace(/~0/g, '~'));
  let current: unknown = dataModel;
  for (const seg of segments) {
    if (current === undefined || current === null) return undefined;
    if (Array.isArray(current)) {
      const idx = Number(seg);
      current = Number.isInteger(idx) ? current[idx] : undefined;
    } else if (typeof current === 'object') {
      current = (current as Record<string, unknown>)[seg];
    } else {
      return undefined;
    }
  }
  return current;
}

/**
 * Resolve `value` against `dataModel` when it is a {@link Binding};
 * otherwise pass it through unchanged (never throws on a malformed pointer
 * — returns `undefined` instead).
 */
export function resolveBinding(value: unknown, dataModel: Record<string, unknown>): unknown {
  if (!isBinding(value)) return value;
  try {
    return resolvePointer(value.path, dataModel);
  } catch {
    return undefined;
  }
}

/** Shallow-resolve every prop in `props` against `dataModel` (bindings
 * become their resolved value; non-bindings pass through unchanged). */
export function resolveProps(
  props: Record<string, unknown>,
  dataModel: Record<string, unknown>,
): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    resolved[key] = resolveBinding(value, dataModel);
  }
  return resolved;
}
