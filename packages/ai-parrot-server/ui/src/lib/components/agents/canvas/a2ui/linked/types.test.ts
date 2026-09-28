// FEAT-598 (TASK-3792): getDataSources — the TS twin of has_data_sources.
import { describe, expect, it } from 'vitest';
import type { CreateSurface } from '../a2ui-types';
import type { LinkedSources } from '$lib/types/generated/LinkedSources';
import { DATA_SOURCES_EXTENSION, getDataSources } from './types';

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
