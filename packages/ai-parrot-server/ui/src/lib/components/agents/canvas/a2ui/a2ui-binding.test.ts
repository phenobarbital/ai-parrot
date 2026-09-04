import { describe, expect, it } from 'vitest';
import { isBinding, resolveBinding, resolveProps } from './a2ui-binding';

describe('resolveBinding', () => {
  const dm = {
    charts: { 'chart-0': { rows: [{ m: 'a', v: 1 }] } },
    'a/b': { 'c~d': 7 },
  };

  it('resolves a pointer', () => {
    expect(resolveBinding({ path: '/charts/chart-0/rows' }, dm)).toEqual([{ m: 'a', v: 1 }]);
  });

  it('returns undefined on missing path', () => {
    expect(resolveBinding({ path: '/nope/x' }, dm)).toBeUndefined();
  });

  it('unescapes ~1 and ~0', () => {
    expect(resolveBinding({ path: '/a~1b/c~0d' }, dm)).toBe(7);
  });

  it('passes through non-bindings', () => {
    expect(resolveBinding('literal', dm)).toBe('literal');
    expect(resolveBinding(42, dm)).toBe(42);
    expect(resolveBinding(null, dm)).toBeNull();
  });

  it('resolves the root with an empty pointer', () => {
    expect(resolveBinding({ path: '' }, dm)).toEqual(dm);
  });

  it('returns undefined when indexing into a non-object', () => {
    expect(resolveBinding({ path: '/charts/chart-0/rows/0/m/x' }, dm)).toBeUndefined();
  });

  it('resolves array indices', () => {
    expect(resolveBinding({ path: '/charts/chart-0/rows/0/m' }, dm)).toBe('a');
  });
});

describe('isBinding', () => {
  it('guards shape', () => {
    expect(isBinding({ path: '/x' })).toBe(true);
    expect(isBinding({ paths: '/x' })).toBe(false);
    expect(isBinding('x')).toBe(false);
    expect(isBinding(null)).toBe(false);
    expect(isBinding([1, 2])).toBe(false);
  });
});

describe('resolveProps', () => {
  const dm = { rows: [1, 2, 3] };

  it('shallow-resolves every prop', () => {
    const resolved = resolveProps({ data: { path: '/rows' }, title: 'Fixed' }, dm);
    expect(resolved).toEqual({ data: [1, 2, 3], title: 'Fixed' });
  });
});
