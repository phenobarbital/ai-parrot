// FEAT-623 (TASK-3996): formatA2UIValue passes every shared display-format fixture.
// The Python `format_cell` reads the same JSON (test_format_cell_parity.py).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatA2UIValue } from './a2ui-format';

interface Fixture {
  value: unknown;
  format: string;
  unit?: string;
  expected: string;
}

const FIXTURE = resolve(
  process.cwd(),
  '../../ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json'
);
const fixtures: Fixture[] = JSON.parse(readFileSync(FIXTURE, 'utf8'));
const label = (f: Fixture) => `${JSON.stringify(f.value)} ${f.format}${f.unit ? ' ' + f.unit : ''}`;

describe('display_format.json parity', () => {
  it('finds the shared fixtures', () => {
    expect(fixtures.length).toBeGreaterThan(0);
  });

  it.each(fixtures.map((f) => [label(f), f] as const))('%s', (_name, f) => {
    expect(formatA2UIValue(f.value, f.format, f.unit)).toBe(f.expected);
  });

  describe('locale pin', () => {
    const RealNumberFormat = Intl.NumberFormat;
    afterEach(() => {
      Intl.NumberFormat = RealNumberFormat;
      vi.resetModules();
    });

    it('prints en-US strings even when the default locale is German', async () => {
      // Simulate a de-DE browser: any constructor call without an explicit locale gets de-DE.
      const Patched = function (locale?: string | string[], opts?: Intl.NumberFormatOptions) {
        return new RealNumberFormat(locale ?? 'de-DE', opts);
      } as unknown as typeof Intl.NumberFormat;
      Intl.NumberFormat = Patched;
      // Sanity: the simulation really changes unpinned output.
      expect(new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(1234.56)).toBe('1.234,6');

      vi.resetModules();
      const mod = await import('./a2ui-format');
      for (const f of fixtures) {
        expect(mod.formatA2UIValue(f.value, f.format, f.unit)).toBe(f.expected);
      }
    });
  });
});
