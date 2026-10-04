// FEAT-598 (TASK-3793): TS DSL passes EVERY shared contract fixture (spec AC7).
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { applyTransform, TransformError } from './dsl';

const DSL_DIR = resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl');
const files = readdirSync(DSL_DIR).filter((f) => f.endsWith('.json')).sort();

describe('dsl golden fixtures', () => {
  it('finds the shared fixtures', () => {
    expect(files.length).toBeGreaterThan(0);
  });
  
  it.each(files)('%s', (file) => {
    const fx = JSON.parse(readFileSync(join(DSL_DIR, file), 'utf8'));
    
    // Check if this is an error expectation fixture
    if (fx.error) {
      expect(() => applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {})).toThrow(TransformError);
      try {
        applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {});
      } catch (error) {
        if (error instanceof TransformError) {
          expect(error.opIndex).toBe(fx.error.op_index);
        }
      }
    } else {
      expect(applyTransform(fx.input, { ops: fx.ops }, fx.frames ?? {})).toEqual(fx.expected);
    }
  });
});