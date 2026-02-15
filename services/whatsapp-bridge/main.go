package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/gorilla/mux"
	"github.com/gorilla/websocket"
	qrterminal "github.com/mdp/qrterminal/v3"
	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
	_ "github.com/mattn/go-sqlite3"
)

// WhatsAppBridge manages WhatsApp connection and message routing.
type WhatsAppBridge struct {
	client        *whatsmeow.Client
	redisClient   *redis.Client
	ctx           context.Context
	qrCodeData    string
	qrCodePNG     []byte
	authenticated bool

	// WebSocket connections for QR code streaming
	wsUpgrader websocket.Upgrader
	wsClients  map[*websocket.Conn]bool
}

// IncomingMessage is the structure published to Redis for each received message.
type IncomingMessage struct {
	From      string                 `json:"from"`
	FromName  string                 `json:"from_name,omitempty"`
	Content   string                 `json:"content"`
	Type      string                 `json:"type"`
	Media     string                 `json:"media,omitempty"`
	Timestamp int64                  `json:"timestamp"`
	MessageID string                 `json:"message_id"`
	IsGroup   bool                   `json:"is_group"`
	GroupName string                 `json:"group_name,omitempty"`
	Extra     map[string]interface{} `json:"extra,omitempty"`
}

// OutgoingMessage is the payload accepted by the /send endpoint.
type OutgoingMessage struct {
	Phone    string `json:"phone"`
	Message  string `json:"message"`
	MediaURL string `json:"media_url,omitempty"`
}

// Response is the standard JSON envelope returned by all HTTP handlers.
type Response struct {
	Success bool        `json:"success"`
	Data    interface{} `json:"data,omitempty"`
	Error   string      `json:"error,omitempty"`
}

// NewWhatsAppBridge creates a bridge connected to Redis.
func NewWhatsAppBridge(redisURL string) (*WhatsAppBridge, error) {
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("invalid Redis URL: %v", err)
	}

	redisClient := redis.NewClient(opt)
	ctx := context.Background()

	if err := redisClient.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("Redis connection failed: %v", err)
	}

	bridge := &WhatsAppBridge{
		ctx:         ctx,
		redisClient: redisClient,
		wsUpgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		},
		wsClients: make(map[*websocket.Conn]bool),
	}

	return bridge, nil
}

// InitializeWhatsApp sets up the whatsmeow client with SQLite session storage.
func (b *WhatsAppBridge) InitializeWhatsApp() error {
	dbLog := waLog.Stdout("Database", "INFO", true)

	// Ensure data directory exists
	if _, err := os.Stat("data"); os.IsNotExist(err) {
		os.Mkdir("data", 0755)
	}

	container, err := sqlstore.New(b.ctx, "sqlite3", "file:data/whatsapp.db?_foreign_keys=on", dbLog)
	if err != nil {
		return fmt.Errorf("failed to connect to database: %v", err)
	}

	deviceStore, err := container.GetFirstDevice(b.ctx)
	if err != nil {
		return fmt.Errorf("failed to get device: %v", err)
	}

	clientLog := waLog.Stdout("Client", "INFO", true)
	b.client = whatsmeow.NewClient(deviceStore, clientLog)
	b.client.AddEventHandler(b.handleEvent)

	return nil
}

func (b *WhatsAppBridge) handleEvent(evt interface{}) {
	switch v := evt.(type) {
	case *events.Message:
		b.handleIncomingMessage(v)
	case *events.Receipt:
		log.Printf("Receipt: %v", v)
	case *events.Presence:
		log.Printf("Presence: %s is %s", v.From, v.Unavailable)
	case *events.ChatPresence:
		log.Printf("ChatPresence: %s", v.State)
	case *events.Connected:
		log.Println("✅ WhatsApp connected")
		b.authenticated = true
		b.broadcastAuthenticated()
	case *events.LoggedOut:
		log.Println("⚠️ Logged out from WhatsApp")
		b.authenticated = false
	}
}

func (b *WhatsAppBridge) handleIncomingMessage(msg *events.Message) {
	info := msg.Info

	// Skip messages from self
	if info.IsFromMe {
		return
	}

	incomingMsg := IncomingMessage{
		From:      info.Sender.User,
		Timestamp: info.Timestamp.Unix(),
		MessageID: info.ID,
		IsGroup:   info.IsGroup,
		Extra:     make(map[string]interface{}),
	}

	if info.PushName != "" {
		incomingMsg.FromName = info.PushName
	}

	if info.IsGroup {
		groupInfo, err := b.client.GetGroupInfo(b.ctx, info.Chat)
		if err == nil {
			incomingMsg.GroupName = groupInfo.Name
		}
	}

	// Extract message content based on type
	if msg.Message.GetConversation() != "" {
		incomingMsg.Type = "text"
		incomingMsg.Content = msg.Message.GetConversation()
	} else if extendedMsg := msg.Message.GetExtendedTextMessage(); extendedMsg != nil {
		incomingMsg.Type = "text"
		incomingMsg.Content = extendedMsg.GetText()
	} else if imageMsg := msg.Message.GetImageMessage(); imageMsg != nil {
		incomingMsg.Type = "image"
		incomingMsg.Content = imageMsg.GetCaption()
		incomingMsg.Media = imageMsg.GetURL()
	} else if audioMsg := msg.Message.GetAudioMessage(); audioMsg != nil {
		incomingMsg.Type = "audio"
		incomingMsg.Media = audioMsg.GetURL()
	} else if videoMsg := msg.Message.GetVideoMessage(); videoMsg != nil {
		incomingMsg.Type = "video"
		incomingMsg.Content = videoMsg.GetCaption()
		incomingMsg.Media = videoMsg.GetURL()
	} else if docMsg := msg.Message.GetDocumentMessage(); docMsg != nil {
		incomingMsg.Type = "document"
		incomingMsg.Content = docMsg.GetFileName()
		incomingMsg.Media = docMsg.GetURL()
	} else {
		incomingMsg.Type = "unknown"
		incomingMsg.Content = "Unsupported message type"
	}

	b.publishToRedis(incomingMsg)
	log.Printf("📨 Message from %s (%s): %s", incomingMsg.From, incomingMsg.FromName, incomingMsg.Content)
}

func (b *WhatsAppBridge) publishToRedis(msg IncomingMessage) {
	data, err := json.Marshal(msg)
	if err != nil {
		log.Printf("Error marshaling message: %v", err)
		return
	}

	err = b.redisClient.Publish(b.ctx, "whatsapp:messages", data).Err()
	if err != nil {
		log.Printf("Error publishing to Redis: %v", err)
	}
}

// Connect performs QR-based authentication or resumes an existing session.
func (b *WhatsAppBridge) Connect() error {
	if b.client.Store.ID == nil {
		qrChan, err := b.client.GetQRChannel(b.ctx)
		if err != nil {
			return fmt.Errorf("failed to get QR channel: %v", err)
		}

		err = b.client.Connect()
		if err != nil {
			return fmt.Errorf("failed to connect: %v", err)
		}

		for evt := range qrChan {
			if evt.Event == "code" {
				b.qrCodeData = evt.Code

				png, err := qrcode.Encode(evt.Code, qrcode.Medium, 256)
				if err == nil {
					b.qrCodePNG = png
				}

				qrterminal.GenerateHalfBlock(evt.Code, qrterminal.L, os.Stdout)
				fmt.Println("\n📱 Scan this QR code with WhatsApp")
				fmt.Println("Or visit http://localhost:8765/qr for web QR code")

				b.broadcastQRCode(evt.Code)
			} else {
				log.Printf("QR event: %s", evt.Event)
			}
		}
	} else {
		err := b.client.Connect()
		if err != nil {
			return fmt.Errorf("failed to connect: %v", err)
		}
		log.Println("✅ WhatsApp connected (already authenticated)")
		b.authenticated = true
	}

	return nil
}

func (b *WhatsAppBridge) broadcastQRCode(code string) {
	for client := range b.wsClients {
		err := client.WriteJSON(map[string]string{
			"type": "qr_code",
			"data": code,
		})
		if err != nil {
			log.Printf("Error broadcasting to WebSocket: %v", err)
			client.Close()
			delete(b.wsClients, client)
		}
	}
}

func (b *WhatsAppBridge) broadcastAuthenticated() {
	for client := range b.wsClients {
		err := client.WriteJSON(map[string]string{
			"type": "authenticated",
		})
		if err != nil {
			client.Close()
			delete(b.wsClients, client)
		}
	}
}

// --- HTTP Handlers ---

func (b *WhatsAppBridge) handleHealth(w http.ResponseWriter, r *http.Request) {
	response := Response{
		Success: true,
		Data: map[string]interface{}{
			"connected":     b.client.IsConnected(),
			"authenticated": b.authenticated,
			"logged_in":     b.client.Store.ID != nil,
		},
	}
	json.NewEncoder(w).Encode(response)
}

func (b *WhatsAppBridge) handleSend(w http.ResponseWriter, r *http.Request) {
	var msg OutgoingMessage
	if err := json.NewDecoder(r.Body).Decode(&msg); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if msg.Phone == "" || msg.Message == "" {
		http.Error(w, "phone and message are required", http.StatusBadRequest)
		return
	}

	jid := types.NewJID(msg.Phone, types.DefaultUserServer)

	message := &waE2E.Message{
		Conversation: proto.String(msg.Message),
	}

	resp, err := b.client.SendMessage(b.ctx, jid, message)
	if err != nil {
		json.NewEncoder(w).Encode(Response{
			Success: false,
			Error:   err.Error(),
		})
		return
	}

	json.NewEncoder(w).Encode(Response{
		Success: true,
		Data: map[string]interface{}{
			"message_id": resp.ID,
			"timestamp":  resp.Timestamp,
		},
	})
}

func (b *WhatsAppBridge) handleQRCode(w http.ResponseWriter, r *http.Request) {
	if b.qrCodePNG == nil {
		http.Error(w, "No QR code available", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "image/png")
	w.Write(b.qrCodePNG)
}

func (b *WhatsAppBridge) handleQRPage(w http.ResponseWriter, r *http.Request) {
	html := `
<!DOCTYPE html>
<html>
<head>
    <title>WhatsApp QR Code</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .container {
            background: white;
            padding: 2rem;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-align: center;
        }
        h1 { color: #333; margin-bottom: 1rem; }
        #qrcode { margin: 1rem 0; }
        .status {
            padding: 0.5rem 1rem;
            border-radius: 5px;
            margin-top: 1rem;
        }
        .status.connected { background: #10b981; color: white; }
        .status.waiting   { background: #f59e0b; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 WhatsApp Authentication</h1>
        <p>Scan this QR code with WhatsApp on your phone</p>
        <div id="qrcode"></div>
        <div id="status" class="status waiting">Waiting for scan...</div>
    </div>
    <script>
        const ws = new WebSocket('ws://' + window.location.host + '/ws');
        const qrDiv = document.getElementById('qrcode');
        const statusDiv = document.getElementById('status');
        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            if (data.type === 'qr_code') {
                qrDiv.innerHTML = '<img src="/qr.png?' + Date.now() + '" alt="QR Code">';
            } else if (data.type === 'authenticated') {
                statusDiv.className = 'status connected';
                statusDiv.textContent = '✅ Connected to WhatsApp!';
                setTimeout(() => { window.close(); }, 2000);
            }
        };
        fetch('/qr.png').then(r => { if (r.ok) qrDiv.innerHTML = '<img src="/qr.png" alt="QR Code">'; });
    </script>
</body>
</html>
	`
	w.Header().Set("Content-Type", "text/html")
	w.Write([]byte(html))
}

func (b *WhatsAppBridge) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := b.wsUpgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}

	b.wsClients[conn] = true

	if b.qrCodeData != "" {
		conn.WriteJSON(map[string]string{
			"type": "qr_code",
			"data": b.qrCodeData,
		})
	}

	go func() {
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				delete(b.wsClients, conn)
				conn.Close()
				break
			}
		}
	}()
}

func main() {
	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = "redis://localhost:6379"
	}

	port := os.Getenv("BRIDGE_PORT")
	if port == "" {
		port = "8765"
	}

	bridge, err := NewWhatsAppBridge(redisURL)
	if err != nil {
		log.Fatalf("Failed to create bridge: %v", err)
	}

	if err := bridge.InitializeWhatsApp(); err != nil {
		log.Fatalf("Failed to initialize WhatsApp: %v", err)
	}

	go func() {
		if err := bridge.Connect(); err != nil {
			log.Fatalf("Failed to connect to WhatsApp: %v", err)
		}
	}()

	router := mux.NewRouter()
	router.HandleFunc("/health", bridge.handleHealth).Methods("GET")
	router.HandleFunc("/send", bridge.handleSend).Methods("POST")
	router.HandleFunc("/qr", bridge.handleQRPage).Methods("GET")
	router.HandleFunc("/qr.png", bridge.handleQRCode).Methods("GET")
	router.HandleFunc("/ws", bridge.handleWebSocket)

	// CORS middleware
	router.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", "*")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
			if r.Method == "OPTIONS" {
				w.WriteHeader(http.StatusOK)
				return
			}
			next.ServeHTTP(w, r)
		})
	})

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      router,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
	}

	log.Printf("🚀 WhatsApp Bridge starting on http://localhost:%s", port)
	log.Printf("📡 Redis: %s", redisURL)

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	<-sigChan

	log.Println("🛑 Shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("Server shutdown error: %v", err)
	}

	bridge.client.Disconnect()
	log.Println("👋 Goodbye!")
}
