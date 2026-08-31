/**
 * Shared types and constants for the feedback system.
 * Used by QuickRating.svelte and FeedbackModal.svelte.
 */

/** Quick rating type: positive (thumbs-up) or negative (thumbs-down) */
export type QuickRatingType = "positive" | "negative";

/** Option for feedback dropdowns */
export interface FeedbackOption {
  value: string;
  label: string;
}

/** Payload sent to the /api/v1/bot_feedback endpoint */
export interface FeedbackPayload {
  chatbot_id: string;
  session_id: string;
  turn_id: string;
  rating?: number;
  like?: boolean;
  dislike?: boolean;
  feedback_type?: string;
  feedback?: string;
}

/** Options shown for thumbs-up (positive) quick rating */
export const POSITIVE_OPTIONS: FeedbackOption[] = [
  { value: "helpful", label: "Helpful" },
  { value: "accurate", label: "Accurate" },
  { value: "well-explained", label: "Well-explained" },
  { value: "other", label: "Other" },
];

/** Options shown for thumbs-down (negative) quick rating */
export const NEGATIVE_OPTIONS: FeedbackOption[] = [
  { value: "incorrect", label: "Incorrect" },
  { value: "unhelpful", label: "Unhelpful" },
  { value: "confusing", label: "Confusing" },
  { value: "other", label: "Other" },
];

/** Categories for detailed feedback modal */
export const FEEDBACK_CATEGORIES: FeedbackOption[] = [
  { value: "suggestion", label: "Suggestion" },
  { value: "bug-report", label: "Bug Report" },
  { value: "feature-request", label: "Feature Request" },
  { value: "general", label: "General" },
  { value: "other", label: "Other" },
];

/**
 * Get the appropriate options for a quick rating type.
 * @param type - 'positive' for thumbs-up, 'negative' for thumbs-down
 * @returns Array of feedback options
 */
export function getOptionsForType(type: QuickRatingType): FeedbackOption[] {
  return type === "positive" ? POSITIVE_OPTIONS : NEGATIVE_OPTIONS;
}
