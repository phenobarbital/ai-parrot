import { config } from '$lib/config';

export type QuestionHistoryEntry = {
  turnId: string;
  question: string;
  timestamp: string;
  mode: 'talk' | 'method';
  methodName?: string;
  outputMode?: string;
  background?: boolean;
};

type HistoryPayload = {
  entries: QuestionHistoryEntry[];
};

function getKey(agentId: string) {
  return `${config.conversationStoragePrefix}.${agentId}.history`;
}

export function loadQuestionHistory(agentId: string): QuestionHistoryEntry[] {
  if (typeof window === 'undefined') return [];
  const raw = localStorage.getItem(getKey(agentId));
  if (!raw) return [];
  try {
    const payload = JSON.parse(raw) as HistoryPayload;
    return Array.isArray(payload.entries) ? payload.entries : [];
  } catch (error) {
    console.error('Failed to parse history', error);
    return [];
  }
}

export function saveQuestionHistory(agentId: string, entry: QuestionHistoryEntry) {
  if (typeof window === 'undefined') return;
  const existing = loadQuestionHistory(agentId);
  const filtered = existing.filter((item) => item.turnId !== entry.turnId);
  const updated: HistoryPayload = {
    entries: [...filtered, entry]
  };
  localStorage.setItem(getKey(agentId), JSON.stringify(updated));
}

export function clearQuestionHistory(agentId: string) {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(getKey(agentId));
}
