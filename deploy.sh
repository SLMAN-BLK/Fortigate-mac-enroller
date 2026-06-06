#!/usr/bin/env bash
# ============================================================
# deploy.sh — MAC Registration Portal v2 (Multi-Site)
# Run as root on 192.168.1.62 (Ubuntu Server)
# ============================================================
set -euo pipefail

APP_DIR="/opt/mac-register"
SERVICE="mac-register"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MAC Registration Portal v2 — Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "[1/7] System packages..."
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv python3-dev \
    libldap2-dev libsasl2-dev nginx

echo "[2/7] Copying files to $APP_DIR..."
mkdir -p "$APP_DIR"
cp -r ./* "$APP_DIR/"
# .env is dotfile, copy explicitly
[ -f .env ] && cp .env "$APP_DIR/.env"

echo "[3/7] Python venv + packages..."
cd "$APP_DIR"
python3 -m venv venv
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt -q
echo "       Done."

echo "[4/7] Permissions..."
chown -R www-data:www-data "$APP_DIR"
chmod 750 "$APP_DIR"
chmod 640 "$APP_DIR/.env"   # protect credentials

echo "[5/7] Systemd service..."
cp "$APP_DIR/mac-register.service" /etc/systemd/system/"$SERVICE".service
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" \
  && echo "       Service running ✓" \
  || { echo "       ERROR — check: journalctl -u $SERVICE -n 30"; exit 1; }

echo "[6/7] Nginx..."
cp "$APP_DIR/nginx-mac-register.conf" /etc/nginx/sites-available/"$SERVICE"
ln -sf /etc/nginx/sites-available/"$SERVICE" /etc/nginx/sites-enabled/"$SERVICE"
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "       Nginx ready ✓"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done!  http://192.168.1.62"
echo "  Logs : journalctl -u $SERVICE -f"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
