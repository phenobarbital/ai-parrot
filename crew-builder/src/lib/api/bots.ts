import { apiClient } from './client';

export type BotSummary = {
  id: string;
  chatbot_id: string;
  name: string;
  description?: string;
  category?: string;
  owner?: string;
};

type BotApiResponse = {
  chatbot_id?: string;
  id?: string;
  name: string;
  description?: string;
  category?: string;
  owner?: string;
  created_by?: string;
};

const mapBot = (bot: BotApiResponse): BotSummary => ({
  id: bot.chatbot_id || bot.id || bot.name,
  chatbot_id: bot.chatbot_id || bot.id || bot.name,
  name: bot.name,
  description: bot.description || 'No description provided.',
  category: bot.category || 'General',
  owner: bot.owner || bot.created_by || 'Unknown'
});

async function listBots() {
  const { data } = await apiClient.get('/api/v1/bots');
  const bots = Array.isArray(data) ? data : data?.bots || [];
  return {
    bots: bots.map(mapBot)
  };
}

async function getBot(agentId: string) {
  try {
    const { data } = await apiClient.get(`/api/v1/bots/${agentId}`);
    return mapBot(data);
  } catch (error: any) {
    if (error?.response?.status === 404) {
      const { bots } = await listBots();
      const found = bots.find(
        (bot) => bot.chatbot_id === agentId || bot.id === agentId || bot.name === agentId
      );
      if (found) {
        return found;
      }
    }
    throw error;
  }
}

export const botsApi = {
  listBots,
  getBot
};
