import { describe, expect, it } from 'vitest';
import { hasInfographicRoot, inferSurfaceKind } from './a2ui-kind';
import type { CreateSurface } from './a2ui-types';

function surface(overrides: Partial<CreateSurface> = {}): CreateSurface {
  return {
    surfaceId: 'main',
    catalogId: 'https://parrot.dev/catalogs/v1',
    components: [],
    ...overrides,
  };
}

describe('inferSurfaceKind', () => {
  it('one-section Infographic → infographic', () => {
    const env = surface({
      components: [{ id: 'root', component: 'Infographic', sections: [{ heading: 'A' }] }],
    });
    expect(inferSurfaceKind(env)).toBe('infographic');
  });

  it('two-section Infographic → dashboard', () => {
    const env = surface({
      components: [
        { id: 'root', component: 'Infographic', sections: [{ heading: 'A' }, { heading: 'B' }] },
      ],
    });
    expect(inferSurfaceKind(env)).toBe('dashboard');
  });

  it('surfaceId ending in "-infographic" → dashboard even with one section', () => {
    const env = surface({
      surfaceId: 'flex-program-dashboard-infographic',
      components: [{ id: 'root', component: 'Infographic', sections: [{ heading: 'A' }] }],
    });
    expect(inferSurfaceKind(env)).toBe('dashboard');
  });

  it('Report root follows the same rule as Infographic', () => {
    const env = surface({
      components: [
        { id: 'root', component: 'Report', sections: [{ heading: 'A' }, { heading: 'B' }] },
      ],
    });
    expect(inferSurfaceKind(env)).toBe('dashboard');
  });

  it('Chart root → widget', () => {
    const env = surface({
      components: [{ id: 'root', component: 'Chart', type: 'bar', x: 'm', y: ['v'] }],
    });
    expect(inferSurfaceKind(env)).toBe('widget');
  });

  it('no root component → widget', () => {
    const env = surface({ components: [{ id: 'not-root', component: 'Chart' }] });
    expect(inferSurfaceKind(env)).toBe('widget');
  });

  it('Infographic with no sections declared → infographic (0 sections, not > 1)', () => {
    const env = surface({ components: [{ id: 'root', component: 'Infographic' }] });
    expect(inferSurfaceKind(env)).toBe('infographic');
  });
});

describe('hasInfographicRoot', () => {
  it('true for an Infographic root envelope', () => {
    const env = {
      version: 'v1.0' as const,
      createSurface: surface({ components: [{ id: 'root', component: 'Infographic' }] }),
    };
    expect(hasInfographicRoot(env)).toBe(true);
  });

  it('true for a Report root envelope', () => {
    const env = {
      version: 'v1.0' as const,
      createSurface: surface({ components: [{ id: 'root', component: 'Report' }] }),
    };
    expect(hasInfographicRoot(env)).toBe(true);
  });

  it('false for a Chart root envelope', () => {
    const env = {
      version: 'v1.0' as const,
      createSurface: surface({ components: [{ id: 'root', component: 'Chart' }] }),
    };
    expect(hasInfographicRoot(env)).toBe(false);
  });

  it('false for null/undefined', () => {
    expect(hasInfographicRoot(null)).toBe(false);
    expect(hasInfographicRoot(undefined)).toBe(false);
  });
});
