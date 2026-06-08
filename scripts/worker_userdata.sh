#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# worker_userdata.sh – EC2 "User data" bootstrap for a WORKER VM.
#
# Paste this into:  Launch Instance → Advanced details → User data
# Set "Number of instances" to N and AWS will launch N workers that each
# configure themselves on first boot (no SSH, no going one by one).
#
# EDIT the two variables below before pasting.
# Runs as root at boot; logs to /var/log/cloud-init-output.log on the VM.
# ─────────────────────────────────────────────────────────────────────
set -eux

# ── EDIT THESE ──────────────────────────────────────────────────────
BROKER_HOST="10.0.1.10"                                  # broker VM private IP
REPO="https://github.com/TU_USUARIO/TU_REPO.git"         # must be reachable (public, or use an AMI instead)
# Credentials must match scripts/deploy_broker.sh:
export RABBITMQ_USER="ticket"
export RABBITMQ_PASS="ticket"
# export REDIS_PASSWORD="miredis"                         # only if the broker has one
# ────────────────────────────────────────────────────────────────────

apt-get update -y
apt-get install -y git

cd /home/ubuntu
if [ ! -d ticket-system ]; then
    sudo -u ubuntu git clone "$REPO" ticket-system
else
    cd ticket-system && sudo -u ubuntu git pull && cd ..
fi
cd /home/ubuntu/ticket-system
chmod +x scripts/*.sh

# WORKER_ID is left to default to the VM hostname, so every instance shows up
# as a distinct node in the metrics automatically.
BROKER_HOST="$BROKER_HOST" ./scripts/deploy_worker.sh
