import { config } from '$lib/config';
import { notificationStore } from '$lib/stores/notifications.svelte';
import { auth } from '$lib/auth';
import { get } from 'svelte/store';

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'authenticated' | 'error';

class UserWebSocket {
    socket: WebSocket | null = null;
    status = $state<ConnectionStatus>('disconnected');
    error = $state<string | null>(null);
    reconnectAttempts = 0;
    maxReconnectAttempts = 5;
    reconnectTimer: any = null;
    token: string | null = null;

    // Track subscribed channels
    channels = $state<string[]>([]);

    constructor() {
        // Auto-connect if auth changes maybe? 
        // For now, allow manual init or called from layout
    }

    connect(token: string) {
        if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
            return;
        }

        this.token = token;
        this.status = 'connecting';
        this.error = null;

        const protocol = config.apiBaseUrl.startsWith('https') ? 'wss' : 'ws';
        const host = config.apiBaseUrl.replace(/^https?:\/\//, '');
        const url = `${protocol}://${host}/ws/userinfo`;

        console.log(`[UserWS] Connecting to ${url}`);

        try {
            this.socket = new WebSocket(url);

            this.socket.onopen = this.handleOpen.bind(this);
            this.socket.onmessage = this.handleMessage.bind(this);
            this.socket.onclose = this.handleClose.bind(this);
            this.socket.onerror = this.handleError.bind(this);
        } catch (e) {
            this.handleError(e);
        }
    }

    disconnect() {
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
        this.status = 'disconnected';
    }

    private handleOpen() {
        console.log('[UserWS] Connected');
        this.status = 'connected';
        this.reconnectAttempts = 0;

        // Authenticate
        if (this.token) {
            this.sendAuth(this.token);
        }
    }

    private handleMessage(event: MessageEvent) {
        try {
            const data = JSON.parse(event.data);

            // Handle Auth Success
            if (data.type === 'auth_success') {
                console.log('[UserWS] Authenticated as', data.username);
                this.status = 'authenticated';
                this.channels = data.channels || [];
                return;
            }

            // Handle Auth Required
            if (data.type === 'auth_required') {
                console.log('[UserWS] Auth required');
                if (this.token) {
                    this.sendAuth(this.token);
                }
                return;
            }

            // Handle Messages
            if (data.type === 'message' || data.type === 'direct' || data.type === 'broadcast') {
                this.handleIncomingMessage(data);
            }

            // Subscribed/Unsubscribed
            if (data.type === 'subscribed') {
                if (!this.channels.includes(data.channel)) {
                    this.channels = [...this.channels, data.channel];
                }
            }

        } catch (e) {
            console.error('[UserWS] Failed to parse message', e);
        }
    }

    private handleIncomingMessage(data: any) {
        // Add to notifications store
        // data.content could be string or object
        let content = data.content;

        // If content is an object with a 'content' field, unwrap it (common pattern)
        if (typeof content === 'object' && content !== null && content.content) {
            content = content.content;
        }

        const messageText = typeof content === 'string' ? content : JSON.stringify(content, null, 2);

        const channelDisplay = data.channel ? `(${data.channel})` : '';
        const title = data.type === 'direct' ? `Message from ${data.from}` :
            data.type === 'broadcast' ? `Broadcast from ${data.from}` :
                `Notification ${channelDisplay}`;

        const type = data.type === 'error' ? 'error' : 'info';

        notificationStore.add({
            title: title,
            message: messageText,
            type: type,
            toast: true, // Show as toast
            duration: 5000
        });
    }

    private handleClose(event: CloseEvent) {
        console.log('[UserWS] Closed', event.code, event.reason);
        this.status = 'disconnected';
        this.socket = null;

        // Reconnect logic
        if (this.token && this.reconnectAttempts < this.maxReconnectAttempts) {
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            this.reconnectAttempts++;
            console.log(`[UserWS] Reconnecting in ${delay}ms... (Attempt ${this.reconnectAttempts})`);

            this.reconnectTimer = setTimeout(() => {
                this.connect(this.token!);
            }, delay);
        }
    }

    private handleError(error: Event | unknown) {
        console.error('[UserWS] Error', error);
        this.status = 'error';
    }

    // Actions

    sendAuth(token: string) {
        this.sendRaw({
            type: 'auth',
            content: token
        });
    }

    send(channel: string, message: any) {
        this.sendRaw({
            type: 'message',
            content: {
                channel: channel,
                content: message
            }
        });
    }

    sendDirect(username: string, message: any) {
        this.sendRaw({
            type: 'direct',
            content: {
                target: username,
                content: message
            }
        });
    }

    subscribe(channel: string) {
        this.sendRaw({
            type: 'subscribe',
            content: { channel }
        });
    }

    private sendRaw(data: any) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(data));
        } else {
            console.warn('[UserWS] Socket not open, cannot send', data);
        }
    }
}

// Singleton pattern with global check for HMR
const globalKey = Symbol.for('UserWebSocket');
let instance: UserWebSocket;

// @ts-ignore
if (globalThis[globalKey]) {
    // @ts-ignore
    instance = globalThis[globalKey];
} else {
    instance = new UserWebSocket();
    // @ts-ignore
    globalThis[globalKey] = instance;
}

export const userWebSocket = instance;
