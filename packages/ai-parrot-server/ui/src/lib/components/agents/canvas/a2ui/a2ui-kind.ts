/**
 * A2UI surface-kind heuristic (FEAT-527).
 *
 * There is no `kind` field on the wire (docs/frontend/agentdashboard-a2ui-reference.md
 * §6.2) — the kind is an attribute of how a surface was produced / persisted
 * (`UISurfaceKind` in the `ui_surfaces` plane), never the `createSurface`
 * message itself. This is the reference `inferKind()` from that doc, ported
 * verbatim (root-component dispatch, `Infographic`/`Report` sections count,
 * `-infographic` surfaceId suffix).
 */
import type { A2UIEnvelope, CreateSurface, WireComponent } from './a2ui-types';

export type SurfaceKind = 'widget' | 'infographic' | 'dashboard';

/** Root component names whose lowering carries an A2UI-native `Infographic`
 * subtree (spec Non-Goal note: a `Report` root also opens the infographic
 * canvas — doc §7 "lossy heuristic", acceptable for v1). */
const INFOGRAPHIC_LIKE_ROOTS = new Set(['Infographic', 'Report']);

/**
 * Infer the kind of an incoming `CreateSurface` (doc §6.2 heuristic).
 *
 * @param surface - The `createSurface` message.
 * @returns `"dashboard"` for a multi-section (or `-infographic`-suffixed)
 *   Infographic/Report root; `"infographic"` for a single-section one;
 *   `"widget"` for anything else (Chart/DataTable/Map/KPICard/InfoCard/
 *   Timeline/any single primitive), or when there is no `root` component.
 */
export function inferSurfaceKind(surface: CreateSurface): SurfaceKind {
  const root = surface.components.find((c) => c.id === 'root');
  if (!root) return 'widget';
  if (INFOGRAPHIC_LIKE_ROOTS.has(root.component)) {
    const sections = ((root as WireComponent).sections as unknown[] | undefined)?.length ?? 0;
    return sections > 1 || surface.surfaceId.endsWith('-infographic') ? 'dashboard' : 'infographic';
  }
  return 'widget';
}

/** True when `envelope`'s `createSurface` root is an `Infographic`/`Report`
 * composite — the shape `AgentChat.maybeOpenInfographicCanvas` (TASK-2868)
 * opens the infographic canvas for. */
export function hasInfographicRoot(envelope: A2UIEnvelope | null | undefined): boolean {
  if (!envelope) return false;
  const root = envelope.createSurface.components.find((c) => c.id === 'root');
  return root !== undefined && INFOGRAPHIC_LIKE_ROOTS.has(root.component);
}
