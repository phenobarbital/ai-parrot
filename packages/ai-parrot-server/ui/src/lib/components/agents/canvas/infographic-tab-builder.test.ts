// ai-parrot (FEAT-611 M6): linked surfaces (Chart/DataTable/Column roots + parrot_data_sources) open the a2ui canvas.
import { describe, expect, it } from 'vitest';
import { isLinkedSurface } from './a2ui/a2ui-kind';
import { buildInfographicTabData } from './infographic-tab-builder';

function linkedEnvelope(rootComponent: string) {
  return {
    version: 'v1.0' as const,
    createSurface: {
      surfaceId: 'linked-activity',
      components: [{ id: 'root', component: rootComponent }],
      dataModel: {},
      metadata: {
        extensions: {
          parrot_data_sources: {
            activity: { kind: 'query_slug', slug: 'epson_field_activity', target: '/activity/rows' },
          },
        },
      },
    },
  };
}

const plainWidget = {
  version: 'v1.0' as const,
  createSurface: { surfaceId: 'chart', components: [{ id: 'root', component: 'Chart' }] },
};

describe('isLinkedSurface', () => {
  it('detects parrot_data_sources', () => {
    expect(isLinkedSurface(linkedEnvelope('Chart'))).toBe(true);
  });

  it('rejects baked / empty / missing', () => {
    expect(isLinkedSurface(plainWidget)).toBe(false);
    const empty = linkedEnvelope('Chart');
    empty.createSurface.metadata.extensions.parrot_data_sources = {} as never;
    expect(isLinkedSurface(empty)).toBe(false);
    expect(isLinkedSurface(undefined)).toBe(false);
    expect(isLinkedSurface(null)).toBe(false);
  });
});

describe('buildInfographicTabData — linked', () => {
  it('linked widget root opens tab', () => {
    const envelope = linkedEnvelope('Chart');
    expect(buildInfographicTabData({ output_mode: 'a2ui', a2ui_envelope: envelope }, { a2ui: true })).toMatchObject({
      mode: 'a2ui',
      envelope,
    });
  });

  it('linked Column root opens tab', () => {
    const envelope = linkedEnvelope('Column');
    expect(buildInfographicTabData({ output_mode: 'a2ui', a2ui_envelope: envelope }, { a2ui: true })).toMatchObject({
      mode: 'a2ui',
      envelope,
    });
  });

  it('plain non-Infographic root still returns null', () => {
    const msg = { output_mode: 'a2ui', a2ui_envelope: plainWidget };
    expect(buildInfographicTabData(msg, { a2ui: true })).toBeNull();
    expect(buildInfographicTabData(msg, { a2ui: false })).toBeNull();
  });

  it('carries persistedSurfaceId from metadata.a2ui_surface_id', () => {
    const envelope = linkedEnvelope('Chart');
    const withId = buildInfographicTabData(
      { output_mode: 'a2ui', a2ui_envelope: envelope, metadata: { a2ui_surface_id: 'srf-1' } },
      { a2ui: true },
    );
    expect(withId?.persistedSurfaceId).toBe('srf-1');

    for (const bad of [123, '']) {
      const result = buildInfographicTabData(
        { output_mode: 'a2ui', a2ui_envelope: envelope, metadata: { a2ui_surface_id: bad } },
        { a2ui: true },
      );
      expect(result).not.toBeNull();
      expect('persistedSurfaceId' in (result as object)).toBe(false);
    }
  });

  it('flag off degrades to null without html/url', () => {
    expect(
      buildInfographicTabData({ output_mode: 'a2ui', a2ui_envelope: linkedEnvelope('Chart') }, { a2ui: false }),
    ).toBeNull();
  });
});
