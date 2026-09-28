/**
 * Canonical request → QuerySource conditions (FEAT-598, spec §7 / S5).
 * TS twin of `parrot.outputs.a2ui.linked.conditions.derive_conditions`; pinned by
 * `contract/fixtures/conditions/*.json`. Never emits `querylimit` or `refresh` (lane-time keys).
 */
import type { SourceRequest } from './types';

// Keys a lane adds at fetch time; derive_conditions never emits them.
const LANE_TIME_KEYS: Set<string> = new Set(['querylimit', 'refresh']);

export function deriveConditions(
  request: SourceRequest,
  locked: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  
  // Rule 1: placeholders in request order, locked values overriding same-named keys
  // (locked-only keys appended after, as Python does)
  for (const [key, value] of Object.entries(request.placeholders)) {
    // Never emit lane-time keys
    if (!LANE_TIME_KEYS.has(key)) {
      out[key] = value;
    }
  }
  for (const [key, value] of Object.entries(locked)) {
    // Never emit lane-time keys
    if (!LANE_TIME_KEYS.has(key)) {
      out[key] = value;
    }
  }
  
  // Rule 2: filter entries verbatim
  if (request.filter && Object.keys(request.filter).length > 0) {
    out['filter'] = { ...request.filter };
  }
  
  // Rule 3: fields / ordering / grouping only when non-empty
  if (request.fields && request.fields.length > 0) {
    out['fields'] = [...request.fields];
  }
  if (request.ordering && request.ordering.length > 0) {
    out['ordering'] = [...request.ordering];
  }
  if (request.grouping && request.grouping.length > 0) {
    out['grouping'] = [...request.grouping];
  }
  
  // Rule 4: limit / offset mapped to the same dialect keys the fixtures use
  if (request.limit !== undefined && request.limit !== null) {
    out['limit'] = request.limit;
  }
  if (request.offset !== undefined && request.offset !== null) {
    out['_offset'] = request.offset;
  }
  
  return out;
}