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
 * turn opens the SAME way when its root is Infographic-like; a widget-only
 * `a2ui` turn (any other root) is out of scope for this canvas (returns
 * `null` — no tab).
 */
import { hasInfographicRoot } from './a2ui/a2ui-kind';
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
  if (message.output_mode !== 'infographic' && message.output_mode !== 'a2ui') return null;

  const meta = message.metadata;
  const inlineHtml =
    !meta?.html_inline_omitted && typeof message.output === 'string' ? message.output : '';
  const url = typeof meta?.html_url === 'string' ? meta.html_url : undefined;
  const template = typeof meta?.template_name === 'string' ? meta.template_name : undefined;
  const theme = typeof meta?.theme === 'string' ? meta.theme : undefined;
  const common = { template, theme };

  const hasRoot = hasInfographicRoot(message.a2ui_envelope);

  // A widget-only a2ui turn (Chart/DataTable/KPICard/... root, no
  // Infographic/Report) never opens the infographic canvas — out of scope
  // regardless of the flag (spec §3 Module 3 "NOT in scope").
  if (message.output_mode === 'a2ui' && !hasRoot) return null;

  if (features.a2ui && message.a2ui_envelope && hasRoot) {
    return {
      mode: 'a2ui',
      envelope: message.a2ui_envelope,
      url,
      html: inlineHtml || undefined,
      ...common,
    };
  }

  // HTML fallback — today's behaviour, byte-identical when the flag is off
  // or no envelope/root is present (output_mode "infographic" always falls
  // through to here in that case; output_mode "a2ui" falls through only
  // when it DOES have an Infographic root but the flag is off).
  if (inlineHtml.includes('<html') || inlineHtml.includes('<!DOCTYPE')) {
    return { mode: 'html', html: inlineHtml, ...common };
  }
  if (url) {
    return { mode: 'html', url, ...common };
  }
  return null;
}
