import type { ChatResponse } from '$lib/api/chat';
import { config } from '$lib/config';

const STORAGE_PREFIX = config.conversationStoragePrefix;

type ConversationPayload = {
  turns: Record<string, ChatResponse>;
  order: string[];
};

function getKey(agentId: string) {
  return `${STORAGE_PREFIX}.${agentId}`;
}

export function saveTurn(agentId: string, turn: ChatResponse) {
  if (typeof window === 'undefined') return;
  const raw = localStorage.getItem(getKey(agentId));
  const payload: ConversationPayload = raw ? JSON.parse(raw) : { turns: {}, order: [] };
  payload.turns[turn.turn_id] = turn;
  if (!payload.order.includes(turn.turn_id)) {
    payload.order.push(turn.turn_id);
  }
  localStorage.setItem(getKey(agentId), JSON.stringify(payload));
}

export function getTurn(agentId: string, turnId: string) {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(getKey(agentId));
  if (!raw) return null;
  const payload: ConversationPayload = JSON.parse(raw);
  return payload.turns[turnId] || null;
}

export function loadConversation(agentId: string) {
  if (typeof window === 'undefined') return { turns: {}, order: [] };
  const raw = localStorage.getItem(getKey(agentId));
  if (!raw) return { turns: {}, order: [] };
  return JSON.parse(raw) as ConversationPayload;
}
