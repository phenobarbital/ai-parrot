
import Dexie, { type Table } from 'dexie';

export interface Conversation {
    session_id: string; // Primary Key
    title: string;
    agent_name: string;
    created_at: number;
    updated_at: number;
}

export interface Message {
    turn_id: string; // Primary Key
    session_id: string; // Foreign Key
    role: 'user' | 'assistant';
    content: string; // The text content (question or markdown response)

    // Extra fields for assistant messages
    data?: any;
    code?: string;
    output_mode?: string;
    metadata?: any;
    tool_calls?: any[];

    timestamp: number;
}

export class ChatDatabase extends Dexie {
    conversations!: Table<Conversation>;
    messages!: Table<Message>;

    constructor() {
        super('AgentChatDB');
        this.version(1).stores({
            conversations: 'session_id, updated_at', // Index for sorting
            messages: 'turn_id, session_id, timestamp' // Index for querying by session
        });
    }
}

export const db = new ChatDatabase();

// Helpers
export async function saveConversation(session_id: string, agent_name: string, first_query: string) {
    // Check if exists first to avoid overwriting title if not needed?
    // User requirement: "save the conversation with a 'title' using the first 4 words of first question... if user click on button 'new conversation', a new session_id is computed"
    // So we only create the conversation record on the first message of a new session.

    const existing = await db.conversations.get(session_id);
    if (!existing) {
        const title = first_query.split(' ').slice(0, 4).join(' ') || 'New Chat';
        await db.conversations.add({
            session_id,
            agent_name,
            title,
            created_at: Date.now(),
            updated_at: Date.now()
        });
    } else {
        await db.conversations.update(session_id, { updated_at: Date.now() });
    }
}

export async function saveMessage(msg: Message) {
    // If it's a user message, we might need to generate a turn_id if not present
    // But usually we can generate one.
    await db.messages.put(msg);
    // update conversation timestamp
    await db.conversations.update(msg.session_id, { updated_at: Date.now() });
}

export async function getConversationHistory(session_id: string) {
    return await db.messages.where('session_id').equals(session_id).sortBy('timestamp');
}

export async function getAllConversations() {
    return await db.conversations.orderBy('updated_at').reverse().toArray();
}
