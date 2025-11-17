import { apiClient } from './client';

export type ChatRequest = {
  query: string;
};

export type ChatResponse = {
  turn_id: string;
  input: string;
  output: string;
  response: string;
  [key: string]: any;
};

async function sendChat(agentId: string, payload: ChatRequest): Promise<ChatResponse> {
  const { data } = await apiClient.post(`/api/v1/agents/chat/${agentId}`, payload);
  return data;
}

export const chatApi = {
  sendChat
};
