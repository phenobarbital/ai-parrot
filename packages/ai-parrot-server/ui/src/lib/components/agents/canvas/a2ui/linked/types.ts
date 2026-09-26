/**
 * A2UI linked-surface wire types (FEAT-598, spec §2 Data Models / §3 Module 11).
 *
 * Friendly re-exports of the types GENERATED from the `LinkedSources` JSON Schema
 * (`ui/schemas/LinkedSources.json` → `pnpm generate`). Never re-declare a field here:
 * Python ↔ TS drift must surface as a type error, not a silent mismatch.
 */
import type { CreateSurface } from '../a2ui-types';
import type {
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
  LinkedDataSource,
  LinkedSources,
  ParamSpec,
  RefreshPolicy,
  SourceRequest,
  TransformRef,
  TransformSpec,
};

/** One transform operation emitted by the generated schema. */
export type TransformOp = NonNullable<Ops>[number];

/** One QuerySource result row, `orient="records"` (spec §7 DSL semantics). */
export type Row = Record<string, unknown>;

/** Extension key carrying the descriptor (spec G2). */
export const DATA_SOURCES_EXTENSION = 'parrot_data_sources';

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
