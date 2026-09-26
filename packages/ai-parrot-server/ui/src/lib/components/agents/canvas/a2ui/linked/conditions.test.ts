// FEAT-598 (TASK-3793): deriveConditions matches every shared conditions fixture, key order included (S5).
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { deriveConditions } from './conditions';

const DIR = resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions');
const files = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();

describe('deriveConditions golden fixtures', () => {
  it('finds the shared fixtures', () => {
    expect(files.length).toBeGreaterThan(0);
  });
  
  it.each(files)('%s', (file) => {
    const fx = JSON.parse(readFileSync(join(DIR, file), 'utf8'));
    const out = deriveConditions(fx.request, fx.locked ?? {});
    expect(out).toEqual(fx.expected);
    expect(Object.keys(out)).toEqual(Object.keys(fx.expected));
  });
  
  // Never emits querylimit / refresh even when present in request
  it('does not emit lane-time keys', () => {
    const requestWithLaneKeys = {
      placeholders: { querylimit: 100, refresh: 'auto' },
      filter: {},
      fields: [],
      ordering: [],
      grouping: [],
    };
    const out = deriveConditions(requestWithLaneKeys, {});
    expect(out).not.toHaveProperty('querylimit');
    expect(out).not.toHaveProperty('refresh');
  });
});