
import Dexie, { type Table } from 'dexie';
import type { AgentConversation, AgentMessage } from '$lib/types/agent';
import { config } from '$lib/config';

export class ChatDatabase extends Dexie {
    conversations!: Table<AgentConversation>;
    messages!: Table<AgentMessage>;

    constructor() {
        super(config.conversationStoragePrefix || 'agentui_chat_db');

        // Schema definition
        this.version(1).stores({
            conversations: 'id, created_at, updated_at', // Primary key and indexes
            messages: 'id, metadata.session_id, timestamp' // messages indexed by session_id
        });
    }
}

export const db = new ChatDatabase();

// Service functions
export const ChatService = {
    async createConversation(agentName: string, id: string, initialTitle: string = 'New Conversation'): Promise<string> {
        const conversation: AgentConversation = {
            id,
            title: initialTitle,
            created_at: new Date(),
            updated_at: new Date(),
            agent_name: agentName,
        };
        await db.conversations.put(conversation);
        return id;
    },

    async updateConversationTitle(id: string, title: string) {
        await db.conversations.update(id, { title, updated_at: new Date() });
    },

    async getConversations(agentName?: string): Promise<AgentConversation[]> {
        let collection = db.conversations.orderBy('updated_at').reverse();
        if (agentName) {
            // filtering by agent name if needed, though Dexie filtering on non-index is slower at scale
            // but fine for local history. Better to add index if critical.
            const all = await collection.toArray();
            return all.filter(c => c.agent_name === agentName);
        }
        return await collection.toArray();
    },

    async getMessages(sessionId: string): Promise<AgentMessage[]> {
        // We need to query messages where metadata.session_id equals sessionId
        // Since we indexed 'metadata.session_id', we can use it.
        // Note: nested indexing in Dexie works via 'metadata.session_id' in schema
        return await db.messages
            .where('metadata.session_id')
            .equals(sessionId)
            .sortBy('timestamp');
    },

    async saveMessage(message: AgentMessage) {
        // Ensure we have a session_id in metadata to link it
        if (!message.metadata?.session_id) {
            console.warn('Cannot save message without session_id', message);
            return;
        }
        await db.messages.put(message);

        // Update conversation timestamp and last message snippet
        await db.conversations.update(message.metadata.session_id, {
            updated_at: new Date(),
            last_message: message.content.substring(0, 100)
        });
    },

    async deleteConversation(id: string) {
        await db.transaction('rw', db.conversations, db.messages, async () => {
            await db.messages.where('metadata.session_id').equals(id).delete();
            await db.conversations.delete(id);
        });
    },

    async clearHistory() {
        await db.messages.clear();
        await db.conversations.clear();
    }
};
