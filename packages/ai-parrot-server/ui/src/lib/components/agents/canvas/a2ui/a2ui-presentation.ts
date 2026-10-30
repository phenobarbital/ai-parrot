/**
 * Reader for the surface-level `parrot_presentation` extension (FEAT-755).
 *
 * The backend emitter stamps this on every inline chat answer, so a renderer no
 * longer has to infer "widget vs dashboard" from the root component
 * (`a2ui-kind.ts`'s lossy heuristic). Absent or malformed => null, never a throw.
 */
import type { A2UIEnvelope, CreateSurface } from './a2ui-types';
import type { SurfaceKind } from './a2ui-kind';

export const PRESENTATION_EXTENSION = 'parrot_presentation';

export interface PresentationExtension {
  kind: SurfaceKind;
  inline: boolean;
  origin: 'chat_turn' | string;
  component: string;
}

/** The surface-level `metadata.extensions.parrot_presentation`, or null when absent/malformed. */
export function getPresentation(surface: CreateSurface): PresentationExtension | null {
  const raw = surface.metadata?.extensions?.[PRESENTATION_EXTENSION];
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return null;
  }

  const { kind, inline, origin, component } = raw as Record<string, unknown>;
  if (
    (kind !== 'widget' && kind !== 'infographic' && kind !== 'dashboard') ||
    typeof inline !== 'boolean' ||
    typeof origin !== 'string' ||
    typeof component !== 'string'
  ) {
    return null;
  }

  return { kind, inline, origin, component };
}

/** True when the envelope was produced as an inline chat answer (`inline === true`). */
export function isInlinePresentation(envelope: A2UIEnvelope | null | undefined): boolean {
  const presentation = envelope?.createSurface ? getPresentation(envelope.createSurface) : null;
  return presentation?.inline === true;
}
