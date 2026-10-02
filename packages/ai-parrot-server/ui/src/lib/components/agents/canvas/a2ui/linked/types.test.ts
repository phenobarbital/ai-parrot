// FEAT-598 (TASK-3792): getDataSources — the TS twin of has_data_sources.
import { describe, expect, it } from 'vitest';
import type { CreateSurface } from '../a2ui-types';
import type { LinkedSources } from '$lib/types/generated/LinkedSources';
import { DATA_SOURCES_EXTENSION, getDataSources, isDerived, isQuerySlug } from './types';

const base: CreateSurface = { surfaceId: 's1', components: [{ id: 'root', component: 'Chart' }] };

const sources: LinkedSources = {
  sales: {
    conditions: {},
    request: {},
    slug: 'sales',
    target: '/sales',
  },
};

describe('getDataSources', () => {
  it('returns null for a baked surface', () => {
    expect(getDataSources(base)).toBeNull();
  });

  it('returns null for an empty mapping', () => {
    expect(
      getDataSources({
        ...base,
        metadata: { extensions: { [DATA_SOURCES_EXTENSION]: {} } },
      }),
    ).toBeNull();
  });

  it('returns null for a non-object value', () => {
    expect(
      getDataSources({
        ...base,
        metadata: { extensions: { [DATA_SOURCES_EXTENSION]: 'invalid' } },
      }),
    ).toBeNull();
  });

  it('returns a linked-source mapping', () => {
    expect(
      getDataSources({
        ...base,
        metadata: { extensions: { [DATA_SOURCES_EXTENSION]: sources } },
      }),
    ).toBe(sources);
  });
});

describe('source kinds', () => {
  const mixed: LinkedSources = {
    ...sources,
    by_region: {
      kind: 'derived',
      from: 'sales',
      transform: { ops: [{ op: 'group_by', by: ['region'], aggregate: { amount: 'sum' } }] },
      target: '/by_region/rows',
    },
  };

  it('a descriptor without kind is a query-slug source; kind=derived is a derived view', () => {
    expect(isQuerySlug(mixed.sales)).toBe(true);
    expect(isDerived(mixed.sales)).toBe(false);
    expect(isQuerySlug(mixed.by_region)).toBe(false);
    expect(isDerived(mixed.by_region)).toBe(true);
    expect(getDataSources({ ...base, metadata: { extensions: { [DATA_SOURCES_EXTENSION]: mixed } } })).toBe(mixed);
  });
});
