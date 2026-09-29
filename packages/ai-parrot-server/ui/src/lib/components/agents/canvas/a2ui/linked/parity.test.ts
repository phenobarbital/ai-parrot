// FEAT-611 M8 / §9 S6: the TS lane reproduces the shared Epson parity fixture (conditions on the wire + rows).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyTransform } from './dsl';
import { createLinkedLane } from './index';

const FX = JSON.parse(readFileSync(resolve(process.cwd(),
  '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/parity/epson_dashboard_params.json'), 'utf8'));

afterEach(() => vi.restoreAllMocks());

describe('epson dashboard parity — rows', () => {
  it('applyTransform matches the Python reference rows', () => {
    const frames: Record<string, Record<string, unknown>[]> = {};
    for (const key of ['targets', 'activity', 'attainment', 'kpis']) {
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
