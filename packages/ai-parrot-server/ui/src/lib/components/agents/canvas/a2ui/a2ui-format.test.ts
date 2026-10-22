import { describe, expect, it } from 'vitest';
import { formatA2UIValue } from './a2ui-format';

const num = (n: number, opts: Intl.NumberFormatOptions = { maximumFractionDigits: 1 }) =>
  new Intl.NumberFormat('en-US', opts).format(n);

describe('formatA2UIValue', () => {
  it('percent treats the value as a ratio (max 1 decimal)', () => {
    expect(formatA2UIValue(0.57948717948717, 'percent')).toBe(`${num(57.9)}%`);
    expect(formatA2UIValue(0.8, 'percent')).toBe(`${num(80)}%`);
    expect(formatA2UIValue('0.683', 'percent')).toBe(`${num(68.3)}%`);
  });

  it('percent ignores unit', () => {
    expect(formatA2UIValue(0.5, 'percent', 'pts')).toBe(`${num(50)}%`);
  });

  it('number rounds to 1 fraction digit and appends unit', () => {
    expect(formatA2UIValue(1234.567, 'number')).toBe(num(1234.6));
    expect(formatA2UIValue(12.34, 'number', 'visits')).toBe(`${num(12.3)} visits`);
  });

  it('currency formats USD', () => {
    expect(formatA2UIValue(1234.5, 'currency')).toBe(num(1234.5, { style: 'currency', currency: 'USD' }));
  });

  it('no format: unit alone is appended, otherwise the value is unchanged', () => {
    expect(formatA2UIValue(42, undefined, 'stores')).toBe('42 stores');
    expect(formatA2UIValue(42, undefined)).toBe(42);
    expect(formatA2UIValue(42, 'email')).toBe(42);
  });

  it('non-numeric values pass through unchanged', () => {
    expect(formatA2UIValue('n/a', 'percent')).toBe('n/a');
    expect(formatA2UIValue(null, 'number', 'x')).toBeNull();
    expect(formatA2UIValue(undefined, 'currency')).toBeUndefined();
    expect(formatA2UIValue('', 'percent')).toBe('');
    expect(formatA2UIValue(Number.NaN, 'percent')).toBeNaN();
  });
});
