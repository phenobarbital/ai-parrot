/** fetchSource — one linked source against QuerySource (FEAT-598, spec M11 skeleton, AC4/AC10/AC17). */
import { postQuery, queryUrl, QuerySourceHttpError } from '$lib/api/querysource';
import type { LinkedDataSource, Row } from './types';

/** Raised for every QuerySource 404 — the UI says "unavailable", NEVER "denied" (spec §7 risks). */
export class SourceUnavailable extends Error {
  constructor(public readonly slug: string) {
    super(`source '${slug}' unavailable`);
    this.name = 'SourceUnavailable';
  }
}

export const DEFAULT_MAX_FETCH_ROWS = 5000;

/** Raised when a keyed MultiQuery payload cannot be reduced to ONE frame — TS twin of the RuntimeError raised by
 *  `QuerySlugSource._select_multi_frame` (query_slug.py:238). The lane reports status 'error' and keeps rows. */
export class FrameSelectionError extends Error {
  constructor(public readonly slug: string, message: string) {
    super(message);
    this.name = 'FrameSelectionError';
  }
}

/**
 * Normalise a QuerySource payload to one row array, rule-for-rule with `_select_multi_frame` (S4/S7):
 * `null`/`undefined` → `[]`; a plain array is the single frame, wrapped as `{result: array}` exactly as Python
 * wraps a bare DataFrame; `{}` → `[]`; `src.multi_output` must name a present frame (else FrameSelectionError);
 * otherwise `'result'`, else the sole frame, else FrameSelectionError (ambiguous). A non-array frame → `[]`.
 */
function selectFrame(payload: unknown, src: LinkedDataSource): Row[] {
  if (payload === null || payload === undefined) return [];
  const frames: Record<string, unknown> = Array.isArray(payload)
    ? { result: payload }
    : typeof payload === 'object'
      ? (payload as Record<string, unknown>)
      : {};
  const keys = Object.keys(frames);
  if (keys.length === 0) return [];
  let selected: unknown;
  if (src.multi_output) {
    if (!Object.prototype.hasOwnProperty.call(frames, src.multi_output)) {
      throw new FrameSelectionError(
        src.slug,
        `multi-query slug '${src.slug}' has no output named '${src.multi_output}' (available: ${[...keys].sort().join(', ')})`,
      );
    }
    selected = frames[src.multi_output];
  } else if (Object.prototype.hasOwnProperty.call(frames, 'result')) {
    selected = frames['result'];
  } else if (keys.length === 1) {
    selected = frames[keys[0]];
  } else {
    throw new FrameSelectionError(
      src.slug,
      `multi-query slug '${src.slug}' returned multiple outputs (${[...keys].sort().join(', ')}); specify multi_output`,
    );
  }
  return Array.isArray(selected) ? (selected as Row[]) : [];
}

export async function fetchSource(
  src: LinkedDataSource,
  conditions: Record<string, unknown>,
  opts: { baseUrl: string; headers: HeadersInit; maxFetchRows?: number },
): Promise<Row[]> {
  const cap = opts.maxFetchRows ?? DEFAULT_MAX_FETCH_ROWS;
  // deriveConditions never emits `limit` (conditions.py:17-37 parity); the lane re-applies request.limit as
  // querylimit, bounded by the cap (S8/AC17) — the same rule as executor._conditions_for.
  const body: Record<string, unknown> = { ...conditions, querylimit: Math.min(src.request.limit ?? cap, cap) };
  if (body.refresh !== true) delete body.refresh;
  let payload: unknown;
  try {
    payload = await postQuery(
      queryUrl(opts.baseUrl, src.slug, src.tenant ?? null, src.is_multiquery === true),
      body,
      opts.headers,
    );
  } catch (err) {
    if (err instanceof QuerySourceHttpError && err.status === 404) throw new SourceUnavailable(src.slug);
    throw err;
  }
  return selectFrame(payload, src);
}
