import { describe, expect, it } from 'vitest';
import { getPresentation, isInlinePresentation } from './a2ui-presentation';
import type { CreateSurface } from './a2ui-types';

function surface(extensions?: Record<string, unknown>): CreateSurface {
  return {
    surfaceId: 'presentation',
    components: [],
    metadata: extensions === undefined ? undefined : { extensions },
  };
}

describe('getPresentation', () => {
  it('returns every field for a well-formed marker', () => {
    const marker = {
      kind: 'widget',
      inline: true,
      origin: 'chat_turn',
      component: 'KPICard',
    };

    expect(getPresentation(surface({ parrot_presentation: marker }))).toEqual(marker);
  });

  it('returns null for absent, non-object, and invalid-kind markers', () => {
    expect(getPresentation(surface())).toBeNull();
    expect(getPresentation(surface({ parrot_presentation: 'widget' }))).toBeNull();
    expect(
      getPresentation(
        surface({
          parrot_presentation: { kind: 'invalid', inline: true, origin: 'chat_turn', component: 'KPICard' },
        }),
      ),
    ).toBeNull();
  });

  it('returns null without throwing for malformed markers', () => {
    expect(() => getPresentation(surface({ parrot_presentation: [] }))).not.toThrow();
    expect(
      getPresentation(surface({ parrot_presentation: { kind: 'widget', inline: 'true', origin: 1, component: null } })),
    ).toBeNull();
  });
});

describe('isInlinePresentation', () => {
  it('is true only when the marker has inline true', () => {
    const marker = { kind: 'widget', inline: true, origin: 'chat_turn', component: 'KPICard' };
    const notInline = { ...marker, inline: false };

    expect(isInlinePresentation({ version: 'v1.0', createSurface: surface({ parrot_presentation: marker }) })).toBe(true);
    expect(isInlinePresentation({ version: 'v1.0', createSurface: surface({ parrot_presentation: notInline }) })).toBe(
      false,
    );
  });

  it('is false for null, undefined, and marker-less envelopes', () => {
    expect(isInlinePresentation(null)).toBe(false);
    expect(isInlinePresentation(undefined)).toBe(false);
    expect(isInlinePresentation({ version: 'v1.0', createSurface: surface() })).toBe(false);
  });
});
