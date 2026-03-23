/**
 * VoiceChat WebSocket Client
 * 
 * Example client showing different authentication methods:
 * 1. Sec-WebSocket-Protocol (pre-connection) - RECOMMENDED
 * 2. Query parameter
 * 3. Post-connection auth message
 */

class VoiceChatClient {
    constructor(options = {}) {
        this.baseUrl = options.baseUrl || 'ws://localhost:8765';
        this.path = options.path || '/ws/voice';
        this.token = options.token || null;
        this.authMethod = options.authMethod || 'protocol'; // 'protocol', 'query', 'message'

        this.ws = null;
        this.sessionId = null;
        this.authenticated = false;
        this.sessionActive = false;

        // Callbacks
        this.onConnected = options.onConnected || (() => { });
        this.onAuthenticated = options.onAuthenticated || (() => { });
        this.onAuthError = options.onAuthError || (() => { });
        this.onSessionStarted = options.onSessionStarted || (() => { });
        this.onAudioResponse = options.onAudioResponse || (() => { });
        this.onTranscription = options.onTranscription || (() => { });
        this.onError = options.onError || console.error;
        this.onClose = options.onClose || (() => { });
    }

    /**
     * Connect to WebSocket with authentication
     */
    connect() {
        let url = `${this.baseUrl}${this.path}`;
        let protocols = null;

        switch (this.authMethod) {
            case 'protocol':
                // Method 1: Sec-WebSocket-Protocol (RECOMMENDED)
                // This authenticates BEFORE the connection is accepted
                // Server receives: Sec-WebSocket-Protocol: jwt, <token>
                if (this.token) {
                    protocols = ['jwt', this.token];
                }
                break;

            case 'query':
                // Method 2: Query parameter
                // Simple but exposes token in logs/history
                if (this.token) {
                    url += `?token=${encodeURIComponent(this.token)}`;
                }
                break;

            case 'message':
                // Method 3: Post-connection message
                // Authenticates AFTER connection, may require timeout handling
                // Auth message sent in onConnected handler
                break;
        }

        this.ws = new WebSocket(url, protocols);
        this.ws.binaryType = 'arraybuffer';

        this.ws.onopen = () => {
            console.log('WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            this._handleMessage(event);
        };

        this.ws.onerror = (error) => {
            this.onError('WebSocket error', error);
        };

        this.ws.onclose = (event) => {
            this.authenticated = false;
            this.sessionActive = false;
            this.onClose(event);
        };
    }

    /**
     * Handle incoming messages
     */
    _handleMessage(event) {
        // Binary audio data
        if (event.data instanceof ArrayBuffer) {
            this.onAudioResponse(event.data);
            return;
        }

        // JSON messages
        const message = JSON.parse(event.data);

        switch (message.type) {
            case 'connected':
                this.sessionId = message.session_id;
                this.authenticated = message.authenticated || false;
                this.onConnected(message);

                // If using message auth and not yet authenticated, send auth now
                if (this.authMethod === 'message' && !this.authenticated && this.token) {
                    this.authenticate(this.token);
                }
                break;

            case 'auth_success':
                this.authenticated = true;
                this.onAuthenticated(message);
                break;

            case 'auth_error':
                this.authenticated = false;
                this.onAuthError(message);
                break;

            case 'auth_required':
                // Server requires auth - prompt user or use stored token
                if (this.token) {
                    this.authenticate(this.token);
                } else {
                    this.onAuthError({ message: 'Authentication required' });
                }
                break;

            case 'session_started':
                this.sessionActive = true;
                this.onSessionStarted(message);
                break;

            case 'session_ended':
                this.sessionActive = false;
                break;

            case 'response_chunk':
                if (message.audio_base64) {
                    const audioData = this._base64ToArrayBuffer(message.audio_base64);
                    this.onAudioResponse(audioData);
                }
                break;

            case 'transcription':
                this.onTranscription(message);
                break;

            case 'pong':
                console.log('Pong received:', message);
                break;

            case 'error':
                this.onError(message.message, message);
                break;

            default:
                console.log('Unknown message type:', message.type, message);
        }
    }

    /**
     * Send authentication message (Method 3)
     */
    authenticate(token) {
        this.send({
            type: 'auth',
            token: token
        });
    }

    /**
     * Alternative: authenticate with Bearer format
     */
    authenticateBearer(token) {
        this.send({
            type: 'auth',
            authorization: `Bearer ${token}`
        });
    }

    /**
     * Start voice session
     */
    startSession(config = {}) {
        this.send({
            type: 'start_session',
            config: {
                voice_name: config.voice || 'Puck',
                language: config.language || 'en-US',
                system_prompt: config.systemPrompt,
                ...config
            }
        });
    }

    /**
     * End voice session
     */
    endSession() {
        this.send({ type: 'end_session' });
    }

    /**
     * Start recording
     */
    startRecording() {
        this.send({ type: 'start_recording' });
    }

    /**
     * Stop recording
     */
    stopRecording() {
        this.send({ type: 'stop_recording' });
    }

    /**
     * Send audio data (base64)
     */
    sendAudio(audioData) {
        if (audioData instanceof ArrayBuffer) {
            // Send as binary for efficiency
            this.ws.send(audioData);
        } else if (typeof audioData === 'string') {
            // Already base64
            this.send({
                type: 'audio_data',
                data: audioData
            });
        }
    }

    /**
     * Send text message
     */
    sendText(text) {
        this.send({
            type: 'send_text',
            text: text
        });
    }

    /**
     * Send ping for keepalive
     */
    ping() {
        this.send({
            type: 'ping',
            timestamp: new Date().toISOString()
        });
    }

    /**
     * Send JSON message
     */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    /**
     * Close connection
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
    }

    /**
     * Convert base64 to ArrayBuffer
     */
    _base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }
}


// =============================================================================
// Usage Examples
// =============================================================================

/**
 * Example 1: Protocol-based authentication (RECOMMENDED)
 * 
 * This is the most secure method for browsers because:
 * - Authentication happens BEFORE the WebSocket upgrade
 * - Server can reject unauthorized connections immediately
 * - Token not exposed in URL/logs
 */
function example1_protocolAuth() {
    const client = new VoiceChatClient({
        baseUrl: 'wss://api.example.com',
        path: '/ws/voice',
        token: 'eyJhbGciOiJIUzI1NiIs...',  // Your JWT token
        authMethod: 'protocol',

        onConnected: (msg) => {
            console.log('Connected!', msg);
            if (msg.authenticated) {
                console.log('Already authenticated via protocol');
                client.startSession({ voice: 'Puck' });
            }
        },

        onAuthenticated: (msg) => {
            console.log('Auth successful:', msg);
        },

        onSessionStarted: (msg) => {
            console.log('Session started:', msg);
            // Ready to send audio
        }
    });

    client.connect();
}


/**
 * Example 2: Post-connection authentication
 * 
 * Use this when:
 * - Token not available at connection time
 * - Need to handle token refresh
 * - User provides credentials after connecting
 */
function example2_messageAuth() {
    const client = new VoiceChatClient({
        baseUrl: 'wss://api.example.com',
        path: '/ws/voice',
        authMethod: 'message',

        onConnected: (msg) => {
            console.log('Connected, need to authenticate');
            // Token will be sent automatically if set
            // Or manually: client.authenticate('your-token');
        },

        onAuthenticated: (msg) => {
            console.log('Now authenticated!');
            client.startSession();
        },

        onAuthError: (msg) => {
            console.error('Auth failed:', msg);
            // Show login UI
        }
    });

    // Connect first, then authenticate
    client.connect();

    // Later, when user logs in:
    // client.authenticate(tokenFromLogin);
}


/**
 * Example 3: Full voice chat with ping keepalive
 */
function example3_fullUsage() {
    let pingInterval = null;

    const client = new VoiceChatClient({
        baseUrl: 'wss://api.example.com',
        path: '/ws/voice',
        token: localStorage.getItem('jwt_token'),
        authMethod: 'protocol',

        onConnected: (msg) => {
            // Start keepalive pings every 30 seconds
            pingInterval = setInterval(() => client.ping(), 30000);

            if (msg.authenticated) {
                client.startSession({
                    voice: 'Puck',
                    language: 'en-US',
                    systemPrompt: 'You are a helpful assistant.'
                });
            }
        },

        onSessionStarted: (msg) => {
            console.log('Ready to record!');
            enableRecordButton();
        },

        onAudioResponse: (audioData) => {
            // Play audio through Web Audio API
            playAudio(audioData);
        },

        onTranscription: (msg) => {
            if (msg.is_user) {
                showUserTranscription(msg.text);
            } else {
                showAssistantTranscription(msg.text);
            }
        },

        onClose: () => {
            if (pingInterval) clearInterval(pingInterval);
        }
    });

    client.connect();

    // Record button handlers
    document.getElementById('recordBtn').addEventListener('mousedown', () => {
        client.startRecording();
        startMicrophoneCapture(audioChunk => {
            client.sendAudio(audioChunk);
        });
    });

    document.getElementById('recordBtn').addEventListener('mouseup', () => {
        stopMicrophoneCapture();
        client.stopRecording();
    });
}


// Export for ES modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { VoiceChatClient };
}