/**
 * Pure decision logic for `AgentChat.svelte`'s `maybeOpenInfographicCanvas`
 * (FEAT-527) — extracted so it is unit-testable without mounting the
 * 2,700+ line `AgentChat.svelte` component (per this task's own
 * recommendation).
 *
 * Dual-emit routing for the bundled UI: an `output_mode: "infographic"`
 * turn keeps opening the HTML tab UNLESS `features.a2ui` is on AND the
 * turn carries an `a2ui_envelope` with an `Infographic`/`Report` root, in
 * which case it opens in `mode: "a2ui"` instead. An `output_mode: "a2ui"`
 * turn opens the SAME way when its root is Infographic-like OR when it is a
 * linked surface (FEAT-611 M6: `parrot_data_sources` present, any root —
 * usually Chart/DataTable/Column); any other widget-only `a2ui` turn is out
 * of scope for this canvas (returns `null` — no tab). A linked tab carries
 * `persistedSurfaceId` from `metadata.a2ui_surface_id` when the bot persisted
 * the surface in the same turn (enables the server-lane Refresh).
 */
import { hasInfographicRoot, isLinkedSurface } from './a2ui/a2ui-kind';
import type { A2UIEnvelope } from './a2ui/a2ui-types';
import type { InfographicTabData } from './infographic/infographic-types';

/** The minimal shape `buildInfographicTabData` needs from an `AgentMessage`. */
export interface InfographicMessageLike {
  output_mode?: string;
  output?: unknown;
  metadata?: {
    html_inline_omitted?: unknown;
    html_url?: unknown;
    template_name?: unknown;
    theme?: unknown;
    a2ui_surface_id?: unknown;
  } | null;
  a2ui_envelope?: A2UIEnvelope;
}

/**
 * Decide the `InfographicTabData` (if any) `maybeOpenInfographicCanvas`
 * should open for `message`, given the current `features.a2ui` value.
 *
 * @param message - The assistant `AgentMessage` (or a message-shaped object).
 * @param features - Only `a2ui` is read; passed explicitly (not imported)
 *   so this stays a pure function.
 * @returns The tab data, or `null` when no canvas tab should open.
 */
export function buildInfographicTabData(
  message: InfographicMessageLike,
  features: { a2ui: boolean },
): InfographicTabData | null {
  // FEAT-611 (live S4): a tool-built LINKED surface opens the canvas whatever the requested mode —
  // in "Default (Auto)" the server lifts the envelope but keeps output_mode "default", and streamed
  // turns carry no output_mode at all.
  const linkedAnyMode = isLinkedSurface(message.a2ui_envelope);
  if (message.output_mode !== 'infographic' && message.output_mode !== 'a2ui' && !linkedAnyMode) return null;

  const meta = message.metadata;
  const inlineHtml =
    !meta?.html_inline_omitted && typeof message.output === 'string' ? message.output : '';
  const url = typeof meta?.html_url === 'string' ? meta.html_url : undefined;
  const template = typeof meta?.template_name === 'string' ? meta.template_name : undefined;
  const theme = typeof meta?.theme === 'string' ? meta.theme : undefined;
  const common = { template, theme };

  const hasRoot = hasInfographicRoot(message.a2ui_envelope);
  const linked = isLinkedSurface(message.a2ui_envelope);
  const persistedSurfaceId =
    typeof meta?.a2ui_surface_id === 'string' && meta.a2ui_surface_id !== ''
      ? meta.a2ui_surface_id
      : undefined;

  // A widget-only a2ui turn (Chart/DataTable/KPICard/... root, no
  // Infographic/Report) never opens the infographic canvas — out of scope
  // regardless of the flag (spec §3 Module 3 "NOT in scope") — UNLESS it is
  // a linked surface (FEAT-611 M6), which opens the canvas for any root.
  if (message.output_mode === 'a2ui' && !hasRoot && !linked) return null;

  if (features.a2ui && message.a2ui_envelope && (hasRoot || linked)) {
    return {
      mode: 'a2ui',
      envelope: message.a2ui_envelope,
      ...(persistedSurfaceId ? { persistedSurfaceId } : {}),
      url,
      html: inlineHtml || undefined,
      ...common,
    };
  }

  // HTML fallback — today's behaviour, byte-identical when the flag is off
  // or no envelope/root is present (output_mode "infographic" always falls
  // through to here in that case; output_mode "a2ui" falls through only
  // when it DOES have an Infographic root or is linked but the flag is off).
  if (inlineHtml.includes('<html') || inlineHtml.includes('<!DOCTYPE')) {
    return { mode: 'html', html: inlineHtml, ...common };
  }
  if (url) {
    return { mode: 'html', url, ...common };
  }
  return null;
}
