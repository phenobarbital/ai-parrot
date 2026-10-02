// FEAT-611 M8 / §9 S6: the TS lane reproduces the shared Epson parity fixture (conditions on the wire + rows).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyTransform } from './dsl';
import { createLinkedLane, dependenciesOf, executionOrder } from './index';

const FIXTURES = '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/';
const FX = JSON.parse(readFileSync(resolve(process.cwd(), FIXTURES + 'epson_dashboard_params.json'), 'utf8'));
const DFX = JSON.parse(readFileSync(resolve(process.cwd(), FIXTURES + 'derived_dashboard.json'), 'utf8'));

afterEach(() => vi.restoreAllMocks());

describe('derived dashboard parity — order, fetches, params and rows', () => {
  it('orders dependencies first, exactly like the Python executor', () => {
    const deps: Record<string, string[]> = {};
    for (const key of Object.keys(DFX.sources)) deps[key] = dependenciesOf(DFX.sources[key]);
    const { order, failed } = executionOrder(DFX.sources, deps);
    expect(order).toEqual(DFX.expected_order);
    expect(failed.size).toBe(0);
  });

  it('fetches only the query-slug sources and computes derived rows from the parent frame', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const fetched: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const slug = decodeURIComponent(String(url).split('/').pop() ?? '');
      fetched.push(slug);
      return new Response(JSON.stringify(DFX.input_frames[slug]));
    });
    const rows: Record<string, unknown> = {};
    const readyOrder: string[] = [];
    const lane = createLinkedLane(DFX.sources, {
      baseUrl: '', headers: () => ({}), transformsBase: '',
      onUpdate: (u) => {
        if (u.status === 'ready') {
          rows[u.key] = u.rows;
          readyOrder.push(u.key);
        }
      },
    });
    await lane.refreshAll();
    expect(fetched).toEqual(DFX.expected_fetches.map((key: string) => DFX.sources[key].slug));
    // refreshAll fetches every query-slug source first, then computes the derived views: a valid interleaving of the
    // Python order — every key exactly once, and never before one of its dependencies.
    expect([...readyOrder].sort()).toEqual([...DFX.expected_order].sort());
    for (const key of readyOrder) {
      for (const ref of dependenciesOf(DFX.sources[key])) expect(readyOrder.indexOf(ref)).toBeLessThan(readyOrder.indexOf(key));
    }
    for (const key of Object.keys(DFX.expected_rows)) expect(rows[key]).toEqual(DFX.expected_rows[key]);
    // Every param addressed to a derived key is ignored: no fetch, no override.
    for (const fxCase of DFX.param_cases.filter((c: any) => DFX.sources[c.source].kind === 'derived')) {
      const before = fetched.length;
      for (const [name, value] of Object.entries(fxCase.overrides)) await lane.setParam(fxCase.source, name, value);
      expect(fetched.length).toBe(before);
      expect(lane.getParams()).toEqual({});
    }
    lane.stop();
  });
});

describe('epson dashboard parity — rows', () => {
  it('applyTransform matches the Python reference rows', () => {
    const frames: Record<string, Record<string, unknown>[]> = {};
    for (const key of ['targets', 'activity', 'daily', 'attainment', 'kpis']) {
      const src = FX.sources[key];
      frames[key] = applyTransform(FX.input_frames[src.slug], src.transform, frames);
      expect(frames[key]).toEqual(FX.expected_rows[key]);
    }
  });
});

describe('epson dashboard parity — conditions on the wire', () => {
  it.each(FX.param_cases)('$id', async (fxCase: any) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const bodies: Record<string, unknown>[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      bodies.push(JSON.parse(String((init as RequestInit).body)));
      return new Response(JSON.stringify(FX.input_frames[FX.sources.activity.slug]));
    });
    const key = fxCase.source as string;
    const src = key === 'activity_locked' ? FX.locked_source : FX.sources[key];
    const lane = createLinkedLane({ [key]: { ...src, refresh: { policy: 'manual' } } } as any, {
      baseUrl: '', headers: () => ({}), transformsBase: '', onUpdate: () => {},
    });
    await lane.setParam(key, Object.keys(fxCase.overrides)[0], Object.values(fxCase.overrides)[0]);
    if (fxCase.expected_ignored.length === 0) {
      // Declared, non-locked param → exactly one re-fetch carrying the expected conditions (key order included).
      expect(bodies).toHaveLength(1);
      expect(bodies[0]).toEqual(fxCase.expected_conditions);
      expect(Object.keys(bodies[0])).toEqual(Object.keys(fxCase.expected_conditions));
    } else {
      // Undeclared / locked → setParam is a no-op (no fetch); the next refresh sends the unchanged conditions.
      expect(bodies).toHaveLength(0);
      await lane.refreshAll();
      expect(bodies).toHaveLength(1);
      expect(bodies[0].refresh).toBe(true);
      const { refresh: _refresh, ...wire } = bodies[0];
      expect(wire).toEqual(fxCase.expected_conditions);
      expect(Object.keys(wire)).toEqual(Object.keys(fxCase.expected_conditions));
    }
    lane.stop();
  });
});
