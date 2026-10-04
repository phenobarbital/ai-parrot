// FEAT-598 (TASK-3794): loadRef resolves opaque ids via the manifest; SRI mismatch never imports (AC9, S6).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadRef, sriOf } from './ref';
import type { TransformRef } from './types';

const BASE = '/static/a2ui/transforms';

function mockFetchSequence(...responses: Response[]): void {
  const impl = vi.fn();
  responses.forEach((r) => impl.mockResolvedValueOnce(r));
  vi.spyOn(globalThis, 'fetch').mockImplementation(impl as never);
}

beforeEach(() => {
  (globalThis.URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => 'blob:mock-url');
  (globalThis.URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe('loadRef', () => {
  it('returns null for a ref not in the manifest', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ version: 1, entries: {} })));
    const importModule = vi.fn();
    const ref = { name: 'x@1.0.0', integrity: 'sha384-a' } as TransformRef;
    expect(await loadRef(ref, { transformsBase: BASE, importModule })).toBeNull();
    expect(importModule).not.toHaveBeenCalled();
  });

  it('fetches the module at ${base}/${entry.file} and imports it when bytes match the pinned integrity', async () => {
    const moduleBytes = new TextEncoder().encode('export default (rows) => rows;').buffer;
    const integrity = await sriOf(moduleBytes);
    const manifest = {
      version: 1,
      entries: { 'clip@1.0.0': { file: 'clip@1.0.0.js', integrity } },
    };
    mockFetchSequence(
      new Response(JSON.stringify(manifest)),
      new Response(moduleBytes),
    );
    const transformFn = (rows: unknown[]) => rows;
    const importModule = vi.fn().mockResolvedValue({ default: transformFn });
    const ref = { name: 'clip@1.0.0', integrity } as TransformRef;

    const fn = await loadRef(ref, { transformsBase: BASE, importModule });

    expect(fn).toBe(transformFn);
    expect(importModule).toHaveBeenCalledTimes(1);
    const [importedUrl] = importModule.mock.calls[0] as [string];
    expect(importedUrl).toBe('blob:mock-url');
    const fetchSpy = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    expect((fetchSpy.mock.calls[1] as [string])[0]).toBe(`${BASE}/clip@1.0.0.js`);
  });

  it('never imports when the fetched bytes do not match the pinned SRI', async () => {
    const manifest = {
      version: 1,
      entries: { 'clip@1.0.0': { file: 'clip@1.0.0.js', integrity: 'sha384-pinned' } },
    };
    mockFetchSequence(
      new Response(JSON.stringify(manifest)),
      new Response(new TextEncoder().encode('export default () => [];').buffer),
    );
    // Manifest entry integrity matches ref.integrity so the pre-fetch check passes,
    // but the actual downloaded bytes will not hash to 'sha384-pinned'.
    const importModule = vi.fn();
    const ref = { name: 'clip@1.0.0', integrity: 'sha384-pinned' } as TransformRef;

    expect(await loadRef(ref, { transformsBase: BASE, importModule })).toBeNull();
    expect(importModule).not.toHaveBeenCalled();
  });

  it('returns null when the manifest entry integrity does not equal ref.integrity', async () => {
    const manifest = {
      version: 1,
      entries: { 'clip@1.0.0': { file: 'clip@1.0.0.js', integrity: 'sha384-other' } },
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(manifest)));
    const importModule = vi.fn();
    const ref = { name: 'clip@1.0.0', integrity: 'sha384-mine' } as TransformRef;

    expect(await loadRef(ref, { transformsBase: BASE, importModule })).toBeNull();
    expect(importModule).not.toHaveBeenCalled();
  });

  it('a deprecated entry still resolves, with a console.warn', async () => {
    const moduleBytes = new TextEncoder().encode('export default (rows) => rows;').buffer;
    const integrity = await sriOf(moduleBytes);
    const manifest = {
      version: 1,
      entries: { 'clip@0.9.0': { file: 'clip@0.9.0.js', integrity, deprecated: true } },
    };
    mockFetchSequence(new Response(JSON.stringify(manifest)), new Response(moduleBytes));
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const transformFn = (rows: unknown[]) => rows;
    const importModule = vi.fn().mockResolvedValue({ default: transformFn });
    const ref = { name: 'clip@0.9.0', integrity } as TransformRef;

    const fn = await loadRef(ref, { transformsBase: BASE, importModule });

    expect(fn).toBe(transformFn);
    expect(warnSpy).toHaveBeenCalled();
  });

  it('returns null when the module has no callable default export', async () => {
    const moduleBytes = new TextEncoder().encode('export default 42;').buffer;
    const integrity = await sriOf(moduleBytes);
    const manifest = { version: 1, entries: { 'bad@1.0.0': { file: 'bad@1.0.0.js', integrity } } };
    mockFetchSequence(new Response(JSON.stringify(manifest)), new Response(moduleBytes));
    const importModule = vi.fn().mockResolvedValue({ default: 42 });
    const ref = { name: 'bad@1.0.0', integrity } as TransformRef;

    expect(await loadRef(ref, { transformsBase: BASE, importModule })).toBeNull();
  });

  it('returns null when the manifest fetch itself fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network down'));
    const importModule = vi.fn();
    const ref = { name: 'clip@1.0.0', integrity: 'sha384-a' } as TransformRef;

    expect(await loadRef(ref, { transformsBase: BASE, importModule })).toBeNull();
    expect(importModule).not.toHaveBeenCalled();
  });
});
