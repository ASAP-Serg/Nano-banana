#!/usr/bin/env bash
# Run ON the VPS (as deploy or root). Writes a paste-ready facts file — no private keys.
set -euo pipefail

OUT="${1:-$HOME/nano-autodeploy-facts.txt}"
APP_DIR="${APP_DIR:-/srv/nano-banana}"

{
  echo "# Nano-Banana autodeploy facts — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Paste into GitHub → Settings → Secrets and variables → Actions"
  echo
  echo "SERVER_HOST=$(curl -4 -s --max-time 3 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
  echo "SERVER_USER=$(whoami)"
  echo "SERVER_PORT=22"
  echo "DEPLOY_PATH=${APP_DIR}"
  echo
  echo "# --- server checks ---"
  echo "hostname=$(hostname)"
  echo "pwd_app=$(ls -ld "$APP_DIR" 2>/dev/null || echo MISSING)"
  if [[ -d "$APP_DIR/.git" ]]; then
    echo "git_remote=$(git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
    echo "git_branch=$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    echo "git_head=$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || true)"
  fi
  echo "has_env=$([ -f "$APP_DIR/.env" ] && echo yes || echo NO)"
  echo "docker=$(docker compose version 2>/dev/null | head -1 || echo MISSING)"
  echo "containers=$(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
  echo "nginx_sites=$(ls /etc/nginx/sites-enabled 2>/dev/null | tr '\n' ' ')"
  echo
  echo "# SERVER_SSH_KEY = private key of a dedicated GitHub Actions key"
  echo "# (public half must be in ~/.ssh/authorized_keys for SERVER_USER)"
  echo "# Also: origin on the server must be able to git fetch ASAP-Serg/Nano-banana"
} | tee "$OUT"

echo
echo "Wrote $OUT"
