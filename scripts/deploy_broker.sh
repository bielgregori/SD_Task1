#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# deploy_broker.sh – Set up the CENTRAL BROKER VM (Redis + RabbitMQ)
#
# Run this on ONE VM only. Every worker VM (deploy_worker.sh) and the
# benchmark client connect to this machine. By default Redis only listens
# on 127.0.0.1 and RabbitMQ's `guest` user is rejected from remote hosts,
# so this script opens both up for the cluster.
#
# Usage:
#   chmod +x scripts/deploy_broker.sh
#   sudo ./scripts/deploy_broker.sh
#
# Optional overrides (env vars):
#   RABBITMQ_USER   (default: ticket)   remote-capable RabbitMQ user
#   RABBITMQ_PASS   (default: ticket)
#   REDIS_PASSWORD  (default: empty)    if set, Redis requires this password
#
# ⚠️  Security: this exposes Redis/RabbitMQ on the network. Restrict access
#     with the AWS Security Group (only allow the worker/client VMs and your
#     own IP on ports 6379 / 5672 / 15672) and/or set REDIS_PASSWORD.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RMQ_USER="${RABBITMQ_USER:-ticket}"
RMQ_PASS="${RABBITMQ_PASS:-ticket}"
REDIS_PASS="${REDIS_PASSWORD:-}"

echo "═══════════════════════════════════════════════════"
echo "  Concert Ticket System – BROKER VM Setup"
echo "  (Redis + RabbitMQ, open for remote workers)"
echo "═══════════════════════════════════════════════════"

# ── 1. Packages ─────────────────────────────────────────────────────
echo "[1/4] Installing Redis + RabbitMQ…"
apt-get update -qq
apt-get install -y -qq redis-server rabbitmq-server curl

# ── 2. Redis: listen on all interfaces ──────────────────────────────
echo "[2/4] Opening Redis to the network…"
REDIS_CONF=/etc/redis/redis.conf
if grep -q '^bind ' "$REDIS_CONF"; then
    sed -i 's/^bind .*/bind 0.0.0.0 ::/' "$REDIS_CONF"
else
    echo 'bind 0.0.0.0 ::' >> "$REDIS_CONF"
fi
if grep -q '^protected-mode ' "$REDIS_CONF"; then
    sed -i 's/^protected-mode .*/protected-mode no/' "$REDIS_CONF"
else
    echo 'protected-mode no' >> "$REDIS_CONF"
fi
if [ -n "$REDIS_PASS" ]; then
    if grep -q '^requirepass ' "$REDIS_CONF"; then
        sed -i "s/^requirepass .*/requirepass $REDIS_PASS/" "$REDIS_CONF"
    else
        echo "requirepass $REDIS_PASS" >> "$REDIS_CONF"
    fi
fi
systemctl enable redis-server
systemctl restart redis-server

# ── 3. RabbitMQ: create a remote-capable user (guest is localhost-only) ─
echo "[3/4] Creating remote RabbitMQ user '$RMQ_USER'…"
systemctl enable rabbitmq-server
systemctl restart rabbitmq-server
# Wait for the broker to accept commands
for _ in $(seq 1 30); do
    rabbitmqctl status >/dev/null 2>&1 && break
    sleep 1
done
rabbitmqctl add_user "$RMQ_USER" "$RMQ_PASS" 2>/dev/null \
    || rabbitmqctl change_password "$RMQ_USER" "$RMQ_PASS"
rabbitmqctl set_user_tags "$RMQ_USER" administrator
rabbitmqctl set_permissions -p / "$RMQ_USER" ".*" ".*" ".*"
rabbitmq-plugins enable rabbitmq_management >/dev/null 2>&1 || true

# ── 4. Report ───────────────────────────────────────────────────────
echo "[4/4] Done."
PRIVATE_IP="$(hostname -I | awk '{print $1}')"
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Broker ready on private IP: $PRIVATE_IP"
echo ""
echo "  Redis    : $PRIVATE_IP:6379"
echo "  RabbitMQ : $PRIVATE_IP:5672   (UI: http://$PRIVATE_IP:15672)"
echo ""
echo "  On each WORKER VM run:"
echo "    sudo BROKER_HOST=$PRIVATE_IP \\"
echo "         RABBITMQ_USER=$RMQ_USER RABBITMQ_PASS=$RMQ_PASS \\"
[ -n "$REDIS_PASS" ] && echo "         REDIS_PASSWORD=$REDIS_PASS \\"
echo "         ./scripts/deploy_worker.sh"
echo ""
echo "  On the CLIENT VM export the same before running the benchmark:"
echo "    export RABBITMQ_HOST=$PRIVATE_IP REDIS_HOST=$PRIVATE_IP"
echo "    export RABBITMQ_USER=$RMQ_USER RABBITMQ_PASS=$RMQ_PASS"
[ -n "$REDIS_PASS" ] && echo "    export REDIS_PASSWORD=$REDIS_PASS"
echo "═══════════════════════════════════════════════════"
