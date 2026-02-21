#!/usr/bin/env bash
set -euo pipefail

# BitBot VPS Deployment Script
# Usage: curl -sSL <raw-url> | bash
# Or:    ssh user@vps "cd /opt/bitbot && bash scripts/deploy.sh"

INSTALL_DIR="${BITBOT_DIR:-/opt/bitbot}"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[bitbot]${NC} $1"; }
warn() { echo -e "${YELLOW}[bitbot]${NC} $1"; }

# --- 1. Check Docker ---
if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    log "Docker installed. You may need to log out and back in for group changes."
fi

if ! docker compose version &>/dev/null; then
    log "Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# --- 2. Setup project ---
cd "$INSTALL_DIR"

# --- 3. Environment file ---
if [ ! -f .env ]; then
    warn ".env file not found — creating from template"
    cp .env.example .env
    echo ""
    warn "IMPORTANT: Edit .env with your API keys before starting!"
    warn "  nano $INSTALL_DIR/.env"
    echo ""
fi

# --- 4. Create data directory ---
mkdir -p data/logs

# --- 5. Build and start ---
log "Building containers..."
docker compose build

log "Starting BitBot stack..."
docker compose up -d

# --- 6. Wait for health check ---
log "Waiting for bot to start..."
for i in {1..30}; do
    if curl -sf http://localhost:80/api/health >/dev/null 2>&1; then
        echo ""
        log "BitBot is running!"
        echo ""
        echo "  Dashboard:  http://$(hostname -I | awk '{print $1}')"
        echo "  API docs:   http://$(hostname -I | awk '{print $1}')/docs"
        echo "  Health:     http://$(hostname -I | awk '{print $1}')/api/health"
        echo ""
        echo "  Logs:       docker compose logs -f bot"
        echo "  Stop:       docker compose down"
        echo "  Restart:    docker compose restart"
        echo ""
        exit 0
    fi
    sleep 2
    printf "."
done

warn "Bot didn't start within 60s. Check logs:"
echo "  docker compose logs bot"
exit 1
