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

export type AgentMessageRequest = {
  query: string;
  background?: boolean;
  turn_id?: string;
  output_mode?: string;
  method_name?: string;
  params?: Record<string, string>;
  attachments?: File[];
};

async function sendChat(agentId: string, payload: ChatRequest): Promise<ChatResponse> {
  const { data } = await apiClient.post(`/api/v1/agents/chat/${agentId}`, payload);
  return data;
}

async function sendAgentMessage(agentId: string, payload: AgentMessageRequest): Promise<ChatResponse> {
  const { method_name, params = {}, attachments = [], ...rest } = payload;
  const endpoint = method_name
    ? `/api/v1/agents/chat/${agentId}/${method_name}`
    : `/api/v1/agents/chat/${agentId}`;

  const shouldUseFormData = Boolean(method_name) || attachments.length > 0;

  if (shouldUseFormData) {
    const formData = new FormData();
    formData.append('query', rest.query);
    if (rest.turn_id) formData.append('turn_id', rest.turn_id);
    if (rest.output_mode) formData.append('output_mode', rest.output_mode);
    if (typeof rest.background === 'boolean') formData.append('background', String(rest.background));

    Object.entries(params).forEach(([key, value]) => {
      if (key) {
        formData.append(key, value ?? '');
      }
    });

    attachments.forEach((file) => formData.append('attachments', file));

    const { data } = await apiClient.post(endpoint, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return data;
  }

  const requestPayload: Record<string, any> = {
    query: rest.query
  };

  if (rest.turn_id) requestPayload.turn_id = rest.turn_id;
  if (rest.output_mode) requestPayload.output_mode = rest.output_mode;
  if (typeof rest.background === 'boolean') requestPayload.background = rest.background;

  Object.entries(params).forEach(([key, value]) => {
    if (key) {
      requestPayload[key] = value;
    }
  });

  const { data } = await apiClient.post(endpoint, requestPayload);
  return data;
}

export const chatApi = {
  sendChat,
  sendAgentMessage
};
