import type { AxiosInstance } from "axios";
import apiClient from "./http";
import type { BotChatRequest, BotChatResponse } from "$lib/types/bot-chat.js";

const BOT_BASE_PATH = "/api/v1/chat";

export const chatWithBot = async (
  chatbotId: string,
  request: BotChatRequest,
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<BotChatResponse> => {
  const http = client ?? apiClient;
  const response = await http.post<BotChatResponse>(
    `${BOT_BASE_PATH}/${chatbotId}`,
    request,
    { signal },
  );
  return response.data;
};
