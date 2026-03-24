#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# deploy.sh – Install dependencies and services on an Ubuntu AWS VM
#
# Usage:
#   chmod +x scripts/deploy.sh
#   sudo ./scripts/deploy.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "═══════════════════════════════════════════════════"
echo "  Concert Ticket System – AWS VM Setup"
echo "═══════════════════════════════════════════════════"

# ── 1. System packages ──────────────────────────────────────────────
echo "[1/5] Installing system packages…"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx curl

# ── 2. Redis ─────────────────────────────────────────────────────────
echo "[2/5] Installing Redis…"
apt-get install -y -qq redis-server
systemctl enable redis-server
systemctl start redis-server
redis-cli ping

# ── 3. RabbitMQ ──────────────────────────────────────────────────────
echo "[3/5] Installing RabbitMQ…"
apt-get install -y -qq rabbitmq-server
systemctl enable rabbitmq-server
systemctl start rabbitmq-server
rabbitmqctl status | head -5

# ── 4. Python dependencies ──────────────────────────────────────────
echo "[4/5] Installing Python dependencies…"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# ── 5. NGINX config (for direct architecture) ───────────────────────
echo "[5/5] Configuring NGINX…"
cp direct/nginx.conf /etc/nginx/conf.d/ticket_system.conf
# Remove default site if it conflicts
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Redis:    redis-cli ping"
echo "  RabbitMQ: rabbitmqctl status"
echo "  NGINX:    curl http://localhost:8080/health"
echo ""
echo "  Start REST servers:"
echo "    uvicorn direct.server:app --host 0.0.0.0 --port 8001 &"
echo "    uvicorn direct.server:app --host 0.0.0.0 --port 8002 &"
echo ""
echo "  Start RabbitMQ workers:"
echo "    python3 indirect/worker.py --worker-id w1 &"
echo "    python3 indirect/worker.py --worker-id w2 &"
echo "═══════════════════════════════════════════════════"
