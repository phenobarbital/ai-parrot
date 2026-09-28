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

/**
 * Normalise a QuerySource JSON payload to a single row array (S4, same rule as the Python
 * `QuerySlugSource._select_multi_frame`): a plain array is already the single frame (the
 * server unwraps a one-frame MultiQuery result before serializing); a keyed object selects
 * `src.multi_output` when set, else `'result'`, else the sole key when there is exactly one.
 * Anything else (ambiguous multi-frame with no selector, or an unexpected shape) yields `[]`.
 */
function selectFrame(payload: unknown, src: LinkedDataSource): Row[] {
  if (Array.isArray(payload)) return payload as Row[];
  if (payload && typeof payload === 'object') {
    const frames = payload as Record<string, unknown>;
    const keys = Object.keys(frames);
    let selected: unknown;
    if (src.multi_output && Object.prototype.hasOwnProperty.call(frames, src.multi_output)) {
      selected = frames[src.multi_output];
    } else if (Object.prototype.hasOwnProperty.call(frames, 'result')) {
      selected = frames['result'];
    } else if (keys.length === 1) {
      selected = frames[keys[0]];
    } else {
      selected = [];
    }
    return Array.isArray(selected) ? (selected as Row[]) : [];
  }
  return [];
}

export async function fetchSource(
  src: LinkedDataSource,
  conditions: Record<string, unknown>,
  opts: { baseUrl: string; headers: HeadersInit; maxFetchRows?: number },
): Promise<Row[]> {
  const cap = opts.maxFetchRows ?? DEFAULT_MAX_FETCH_ROWS;
  // deriveConditions never emits `limit` (TASK-3770/TASK-3793); the lane re-applies request.limit bounded by the cap (S8/AC17)
  const body: Record<string, unknown> = { ...conditions, querylimit: Math.min(src.request.limit ?? cap, cap) };
  if (body.refresh !== true) delete body.refresh;
  let payload: unknown;
  try {
    payload = await postQuery(queryUrl(opts.baseUrl, src.slug, src.tenant ?? null), body, opts.headers);
  } catch (err) {
    if (err instanceof QuerySourceHttpError && err.status === 404) throw new SourceUnavailable(src.slug);
    throw err;
  }
  return selectFrame(payload, src);
}
