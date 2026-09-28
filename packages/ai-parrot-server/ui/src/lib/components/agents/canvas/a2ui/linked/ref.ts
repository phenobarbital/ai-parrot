/**
 * loadRef — catalogued `transform.ref` modules (FEAT-598, S6, AC9).
 * URL = `${transformsBase}/${manifest.entries[ref.name].file}`; `ref.name` is opaque, never a URL.
 * Returns null on unknown ref, integrity mismatch, SRI mismatch, or any load failure → caller keeps the snapshot.
 */
import type { Row, TransformRef } from './types';

export type RowTransform = (rows: Row[]) => Row[];
interface ManifestEntry { file: string; integrity: string; deprecated?: boolean }
interface Manifest { version: number; entries: Record<string, ManifestEntry> }

export async function sriOf(bytes: ArrayBuffer): Promise<string> {
  // Re-view into a local-realm Uint8Array first: `bytes` may originate from another global
  // realm (e.g. a `fetch`/`Response` implementation not bound to this module's own
  // ArrayBuffer/Uint8Array constructors), which some `SubtleCrypto` implementations reject
  // on an identity check even though the underlying bytes are perfectly valid.
  const local = Uint8Array.from(new Uint8Array(bytes));
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-384', local));
  return `sha384-${btoa(String.fromCharCode(...digest))}`;
}

export async function loadRef(
  ref: TransformRef,
  opts: { transformsBase: string; importModule?: (url: string) => Promise<unknown> },
): Promise<RowTransform | null> {
  const base = opts.transformsBase.replace(/\/$/, '');
  try {
    const manifest = (await (await fetch(`${base}/manifest.json`)).json()) as Manifest;
    const entry = manifest.entries?.[ref.name];
    if (!entry || entry.integrity !== ref.integrity) return null;
    if (entry.deprecated) console.warn(`a2ui transform ${ref.name} is deprecated`);
    const bytes = await (await fetch(`${base}/${entry.file}`)).arrayBuffer();
    const sri = await sriOf(bytes);
    // The fetched bytes must match BOTH the descriptor's pin and the manifest entry's own
    // integrity (already checked above) — never import a module whose actual bytes differ.
    if (sri !== ref.integrity) return null;
    const importModule = opts.importModule ?? ((url: string) => import(/* @vite-ignore */ url));
    const blobUrl = URL.createObjectURL(new Blob([bytes], { type: 'text/javascript' }));
    let mod: unknown;
    try {
      mod = await importModule(blobUrl);
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
    const fn = (mod as { default?: unknown } | null | undefined)?.default;
    return typeof fn === 'function' ? (fn as RowTransform) : null;
  } catch {
    return null;
  }
}
