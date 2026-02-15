# Multi-stage build for WhatsApp Bridge
FROM golang:1.24-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git gcc musl-dev sqlite-dev

WORKDIR /build

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . ./

# Build binary
RUN CGO_ENABLED=1 GOOS=linux go build \
    -ldflags="-s -w -extldflags '-static'" \
    -o whatsapp-bridge .

# Final stage
FROM alpine:latest

# Install runtime dependencies
RUN apk add --no-cache \
    ca-certificates \
    sqlite \
    tzdata

# Create non-root user
RUN addgroup -g 1000 parrot && \
    adduser -D -u 1000 -G parrot parrot

# Create data directory
RUN mkdir -p /data && \
    chown -R parrot:parrot /data

WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/whatsapp-bridge .

# Switch to non-root user
USER parrot

# Expose port
EXPOSE 8765

# Volume for persistent data
VOLUME ["/data"]

# Environment variables
ENV REDIS_URL=redis://localhost:6379 \
    BRIDGE_PORT=8765

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8765/health || exit 1

# Run the bridge
CMD ["./whatsapp-bridge"]
