/**
 * Prompt Placeholder Utilities
 *
 * Defines available placeholders for prompt templates and provides
 * functions to replace them with actual values at runtime.
 *
 * Placeholder syntax: {{placeholder_key}}
 * Example: "Show revenue for {{today}}" → "Show revenue for 2026-02-27"
 */

import type {
  PromptPlaceholder,
  PlaceholderOption,
} from "$lib/types/prompt-library";

/**
 * Format a date as YYYY-MM-DD (ISO 8601 date format)
 */
function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Get the full month name for a date
 */
function getMonthName(date: Date): string {
  return new Intl.DateTimeFormat("en-US", { month: "long" }).format(date);
}

/**
 * Get a zero-padded month number (01-12)
 */
function getMonthNumber(date: Date): string {
  return String(date.getMonth() + 1).padStart(2, "0");
}

/**
 * Get yesterday's date
 */
function getYesterday(): Date {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  return date;
}

/**
 * Get the previous month's date (same day, previous month)
 * Handles year boundary (January → December of previous year)
 */
function getPreviousMonthDate(): Date {
  const date = new Date();
  date.setMonth(date.getMonth() - 1);
  return date;
}

/**
 * Registry of all available placeholders.
 * Each placeholder has a key, human-readable label, and getValue function.
 */
export const PROMPT_PLACEHOLDERS: PromptPlaceholder[] = [
  {
    key: "today",
    label: "Today's Date",
    getValue: () => formatDate(new Date()),
  },
  {
    key: "yesterday",
    label: "Yesterday's Date",
    getValue: () => formatDate(getYesterday()),
  },
  {
    key: "current_year",
    label: "Current Year",
    getValue: () => String(new Date().getFullYear()),
  },
  {
    key: "previous_year",
    label: "Previous Year",
    getValue: () => String(new Date().getFullYear() - 1),
  },
  {
    key: "current_month",
    label: "Current Month",
    getValue: () => getMonthName(new Date()),
  },
  {
    key: "previous_month",
    label: "Previous Month",
    getValue: () => getMonthName(getPreviousMonthDate()),
  },
  {
    key: "current_month_num",
    label: "Current Month Number",
    getValue: () => getMonthNumber(new Date()),
  },
  {
    key: "previous_month_num",
    label: "Previous Month Number",
    getValue: () => getMonthNumber(getPreviousMonthDate()),
  },
];

/**
 * Build a lookup map from placeholder key to its definition.
 * Used for efficient replacement.
 */
const placeholderMap = new Map<string, PromptPlaceholder>(
  PROMPT_PLACEHOLDERS.map((p) => [p.key, p]),
);

/**
 * Replace all {{placeholder}} occurrences in a template string
 * with their current values.
 *
 * @param template - The template string containing {{placeholders}}
 * @returns The string with all known placeholders replaced
 *
 * @example
 * replacePlaceholders("Report for {{today}}")
 * // Returns: "Report for 2026-02-27"
 *
 * @example
 * replacePlaceholders("From {{yesterday}} to {{today}}")
 * // Returns: "From 2026-02-26 to 2026-02-27"
 */
export function replacePlaceholders(template: string): string {
  if (!template) return template;

  // Match all {{...}} patterns
  return template.replace(/\{\{(\w+)\}\}/g, (match, key) => {
    const placeholder = placeholderMap.get(key);
    if (placeholder) {
      return placeholder.getValue();
    }
    // Leave unknown placeholders unchanged
    return match;
  });
}

/**
 * Get placeholder options for dropdown UI.
 * Includes a preview of the current resolved value.
 *
 * @returns Array of options with key, label, and preview
 *
 * @example
 * getPlaceholderOptions()
 * // Returns: [{ key: 'today', label: "Today's Date", preview: '2026-02-27' }, ...]
 */
export function getPlaceholderOptions(): PlaceholderOption[] {
  return PROMPT_PLACEHOLDERS.map((p) => ({
    key: p.key,
    label: p.label,
    preview: p.getValue(),
  }));
}

/**
 * Insert a placeholder at a specific cursor position in a string.
 * Used when user selects a placeholder from a dropdown in the editor.
 *
 * @param text - The current text
 * @param cursorPos - The cursor position where to insert
 * @param placeholder - The placeholder key (without braces)
 * @returns Object with the new text and new cursor position
 *
 * @example
 * insertPlaceholder("Hello world", 6, "today")
 * // Returns: { text: "Hello {{today}}world", newCursorPos: 15 }
 */
export function insertPlaceholder(
  text: string,
  cursorPos: number,
  placeholder: string,
): { text: string; newCursorPos: number } {
  const insertion = `{{${placeholder}}}`;
  const before = text.slice(0, cursorPos);
  const after = text.slice(cursorPos);
  const newText = before + insertion + after;
  const newCursorPos = cursorPos + insertion.length;

  return { text: newText, newCursorPos };
}

/**
 * Check if a string contains any placeholders.
 * Useful for displaying a "has placeholders" indicator in the UI.
 *
 * @param text - The text to check
 * @returns true if the text contains at least one {{...}} pattern
 */
export function hasPlaceholders(text: string): boolean {
  return /\{\{\w+\}\}/.test(text);
}

/**
 * Extract all placeholder keys from a template string.
 * Useful for validation or preview purposes.
 *
 * @param template - The template string
 * @returns Array of unique placeholder keys found
 *
 * @example
 * extractPlaceholders("From {{today}} to {{today}} in {{current_year}}")
 * // Returns: ['today', 'current_year']
 */
export function extractPlaceholders(template: string): string[] {
  const matches = template.matchAll(/\{\{(\w+)\}\}/g);
  const keys = new Set<string>();
  for (const match of matches) {
    keys.add(match[1]);
  }
  return Array.from(keys);
}
