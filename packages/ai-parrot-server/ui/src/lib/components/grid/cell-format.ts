/**
 * Cell-value serialization shared by the results grid and the export paths.
 *
 * jsonb/array columns arrive from the API as live JS objects; anything that
 * coerces them with String() — RevoGrid's default renderer, CSV building,
 * SheetJS rows — produces "[object Object]" (or blank cells). Serialize them
 * as compact JSON instead.
 */
export function stringifyCellValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}
