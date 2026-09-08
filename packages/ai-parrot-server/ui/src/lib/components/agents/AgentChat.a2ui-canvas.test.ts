// ai-parrot (FEAT-527): AgentChat -> canvas opening rule for infographic /
// a2ui turns. Tests the extracted pure decision helper
// (`buildInfographicTabData`) rather than mounting the full AgentChat
// component (per this task's own recommendation — AgentChat.svelte is
// 2,700+ lines and not practically unit-testable end-to-end here).
import { describe, expect, it } from 'vitest';
import { buildInfographicTabData } from './canvas/infographic-tab-builder';

const infographicEnvelope = {
  version: 'v1.0' as const,
  createSurface: {
    surfaceId: 'infographic-a',
    components: [{ id: 'root', component: 'Infographic', title: 'T', sections: [] }],
  },
};

const widgetEnvelope = {
  version: 'v1.0' as const,
  createSurface: {
    surfaceId: 'chart',
    components: [{ id: 'root', component: 'Chart' }],
  },
};

describe('buildInfographicTabData', () => {
  it('prefers a2ui mode when flag on and Infographic root (output_mode=infographic)', () => {
    const msg = {
      output_mode: 'infographic',
      output: '<html>..</html>',
      metadata: { html_url: 'https://x/a.html', template_name: 'basic' },
      a2ui_envelope: infographicEnvelope,
    };
    expect(buildInfographicTabData(msg, { a2ui: true })).toMatchObject({
      mode: 'a2ui',
      url: 'https://x/a.html',
      template: 'basic',
      envelope: infographicEnvelope,
    });
  });

  it('falls back to HTML mode when the flag is off (byte-identical to today)', () => {
    const msg = {
      output_mode: 'infographic',
      output: '<html>..</html>',
      metadata: { html_url: 'https://x/a.html', template_name: 'basic' },
      a2ui_envelope: infographicEnvelope,
    };
    expect(buildInfographicTabData(msg, { a2ui: false })).toMatchObject({
      mode: 'html',
      html: '<html>..</html>',
      template: 'basic',
    });
  });

  it('falls back to HTML mode when no envelope is present at all', () => {
    const msg = {
      output_mode: 'infographic',
      output: '<html>..</html>',
      metadata: { html_url: 'https://x/a.html', template_name: 'basic' },
    };
    expect(buildInfographicTabData(msg, { a2ui: true })).toMatchObject({
      mode: 'html',
      html: '<html>..</html>',
    });
  });

  it('output_mode=a2ui with an Infographic root opens the a2ui tab', () => {
    const msg = {
      output_mode: 'a2ui',
      metadata: { html_url: 'https://x/a.html' },
      a2ui_envelope: infographicEnvelope,
    };
    expect(buildInfographicTabData(msg, { a2ui: true })).toMatchObject({
      mode: 'a2ui',
      envelope: infographicEnvelope,
    });
  });

  it('ignores a2ui widgets (no Infographic/Report root) regardless of the flag', () => {
    const msg = { output_mode: 'a2ui', a2ui_envelope: widgetEnvelope };
    expect(buildInfographicTabData(msg, { a2ui: true })).toBeNull();
    expect(buildInfographicTabData(msg, { a2ui: false })).toBeNull();
  });

  it('a2ui + Infographic root + flag off degrades to an HTML tab when a url exists', () => {
    const msg = {
      output_mode: 'a2ui',
      metadata: { html_url: 'https://x/a.html' },
      a2ui_envelope: infographicEnvelope,
    };
    expect(buildInfographicTabData(msg, { a2ui: false })).toMatchObject({
      mode: 'html',
      url: 'https://x/a.html',
    });
  });

  it('returns null for an unrelated output_mode', () => {
    expect(buildInfographicTabData({ output_mode: 'default' }, { a2ui: true })).toBeNull();
  });

  it('returns null when there is neither inline html nor a url', () => {
    expect(buildInfographicTabData({ output_mode: 'infographic' }, { a2ui: true })).toBeNull();
  });

  it('respects html_inline_omitted (does not treat output as inline html)', () => {
    const msg = {
      output_mode: 'infographic',
      output: '<html>large</html>',
      metadata: { html_inline_omitted: true, html_url: 'https://x/big.html' },
    };
    const result = buildInfographicTabData(msg, { a2ui: true });
    expect(result).toMatchObject({ mode: 'html', url: 'https://x/big.html' });
    expect(result?.html).toBeUndefined();
  });
});
