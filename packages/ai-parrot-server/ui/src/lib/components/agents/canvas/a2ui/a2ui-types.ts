/**
 * A2UI v1.0 wire types (FEAT-527, spec §2 New Public Interfaces).
 *
 * Structural TypeScript mirrors of the backend's A2UI v1.0 wire envelope
 * (`parrot.outputs.a2ui.serialization.serialize()`) — no runtime dependency,
 * no class instances, just the JSON shape every `AgentMessage.a2ui_envelope`
 * carries. Deliberately looser than the backend's own Pydantic models: the
 * bundled UI only needs to walk and bind this tree, never validate it (the
 * backend already validated it before emission).
 */

/** A JSON-Pointer (RFC 6901) data-model binding, e.g. `{"path": "/charts/chart-0/rows"}`. */
export interface Binding {
  path: string;
}

/** A flat, wire-shaped A2UI component — props live top-level (v1.0), never
 * nested under a "properties" key. `child`/`children` reference OTHER
 * component ids in the same flat list. */
export interface WireComponent {
  id: string;
  component: string;
  child?: string;
  children?: string[] | { componentId: string; path: string };
  metadata?: { extensions?: Record<string, unknown> };
  [prop: string]: unknown;
}

/** A nested composite child descriptor (e.g. inside an `Infographic`
 * section's `components` list) — NOT a wire `WireComponent` (no id), the
 * adapter's own authored-descriptor shape. */
export interface SectionDescriptor {
  component: string;
  properties?: Record<string, unknown>;
}

/** One `Infographic`/`Report` section. */
export interface InfographicSection {
  heading?: string;
  text?: string;
  components?: SectionDescriptor[];
}

/** The A2UI v1.0 `createSurface` message. */
export interface CreateSurface {
  surfaceId: string;
  catalogId?: string;
  components: WireComponent[];
  dataModel?: Record<string, unknown>;
}

/** The full wire envelope carried on `AgentMessage.a2ui_envelope` /
 * `AIMessage.a2ui_envelope` — `{"version": "v1.0", "createSurface": {...}}`. */
export interface A2UIEnvelope {
  version: "v1.0";
  createSurface: CreateSurface;
}
