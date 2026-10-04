/**
 * A2UI linked-surface wire types (FEAT-598, spec §2 Data Models / §3 Module 11).
 *
 * Friendly re-exports of the types GENERATED from the `LinkedSources` JSON Schema
 * (`ui/schemas/LinkedSources.json` → `pnpm generate`). Never re-declare a field here:
 * Python ↔ TS drift must surface as a type error, not a silent mismatch.
 */
import type { CreateSurface } from '../a2ui-types';
import type {
  DerivedDataSource,
  LinkedDataSource,
  LinkedSources,
  Ops,
  ParamSpec,
  RefreshPolicy,
  SourceRequest,
  TransformRef,
  TransformSpec,
} from '$lib/types/generated/LinkedSources';

export type {
  DerivedDataSource,
  LinkedDataSource,
  LinkedSources,
  ParamSpec,
  RefreshPolicy,
  SourceRequest,
  TransformRef,
  TransformSpec,
};

/** One entry of `parrot_data_sources`: a fetched query-slug source or a derived view of a sibling. */
export type LinkedSource = LinkedSources[string];

/** One transform operation emitted by the generated schema. */
export type TransformOp = NonNullable<Ops>[number];

/** One QuerySource result row, `orient="records"` (spec §7 DSL semantics). */
export type Row = Record<string, unknown>;

/** Extension key carrying the descriptor (spec G2). */
export const DATA_SOURCES_EXTENSION = 'parrot_data_sources';

/**
 * Narrow a source to the fetched kind. A descriptor written before the `derived` kind existed carries no
 * `kind` at all — it is a query-slug source (TS twin of `LinkedSources._default_kind`).
 */
export function isQuerySlug(src: LinkedSource): src is LinkedDataSource {
  return (src.kind ?? 'query_slug') === 'query_slug';
}

/** Narrow a source to a derived view (computed from a sibling's frame; never fetched). */
export function isDerived(src: LinkedSource): src is DerivedDataSource {
  return src.kind === 'derived';
}

/**
 * Return the surface's `parrot_data_sources` mapping, or `null` when the surface is baked
 * (no key, not an object, or empty) — the TS twin of Python's `has_data_sources`.
 */
export function getDataSources(surface: CreateSurface): LinkedSources | null {
  const raw = surface.metadata?.extensions?.[DATA_SOURCES_EXTENSION];
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).length === 0) {
    return null;
  }
  return raw as LinkedSources;
}
