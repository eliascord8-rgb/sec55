#!/usr/bin/env bash
# =============================================================================
# Better Social — One-shot VPS deploy script
# Tested on Ubuntu 22.04 / Debian 12
#
# USAGE:
#   1. Copy this file to your VPS (or `git pull` includes it)
#   2. Edit the CONFIG block below (DOMAIN + REPO_URL)
#   3. sudo bash deploy.sh
#
# What it does:
#   • Installs Python 3.11, Node 20, Yarn, MongoDB 7, Nginx, Certbot
#   • Clones (or updates) the repo into /opt/better-social
#   • Sets up backend venv + .env + systemd service
#   • Builds the React frontend with the correct REACT_APP_BACKEND_URL
#   • Configures Nginx reverse proxy (/api -> backend, / -> React build)
#   • Issues a Let's Encrypt certificate
# =============================================================================

set -euo pipefail

# ───────────────────────── CONFIG ────────────────────────────────────────────
DOMAIN="better-social.pro"              # <-- CHANGE ME (no https://, no trailing /)
WWW_DOMAIN="www.${DOMAIN}"
REPO_URL="https://github.com/eliascord8-rgb/sec55.git"   # <-- CHANGE ME
APP_DIR="/opt/better-social"
ADMIN_EMAIL="balkinstr@web.de"          # <-- for Let's Encrypt notices
DB_NAME="better_social"
# ─────────────────────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo bash deploy.sh)"; exit 1
fi

log() { echo -e "\n\033[1;35m▶ $*\033[0m"; }

log "1/8  Installing system packages…"
apt update
DEBIAN_FRONTEND=noninteractive apt install -y \
  python3.11 python3.11-venv python3-pip git curl gnupg \
  nginx certbot python3-certbot-nginx ufw

if ! command -v node >/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt install -y nodejs
fi
if ! command -v yarn >/dev/null; then
  npm install -g yarn
fi

log "2/8  Installing MongoDB 7…"
if ! command -v mongod >/dev/null; then
  curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
  CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu ${CODENAME}/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list
  apt update
  apt install -y mongodb-org
fi
systemctl enable --now mongod

log "3/8  Cloning / updating repository…"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" pull
else
  git clone "${REPO_URL}" "${APP_DIR}"
fi
chown -R www-data:www-data "${APP_DIR}"

log "4/8  Setting up backend…"
cd "${APP_DIR}/backend"
sudo -u www-data python3.11 -m venv venv
sudo -u www-data ./venv/bin/pip install --upgrade pip
sudo -u www-data ./venv/bin/pip install -r requirements.txt
sudo -u www-data ./venv/bin/pip install gunicorn uvicorn

cat > "${APP_DIR}/backend/.env" <<EOF
MONGO_URL=mongodb://localhost:27017
DB_NAME=${DB_NAME}
CORS_ORIGINS=https://${DOMAIN}
EOF
chown www-data:www-data "${APP_DIR}/backend/.env"

cat > /etc/systemd/system/better-social.service <<EOF
[Unit]
Description=Better Social FastAPI backend
After=network.target mongod.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}/backend
Environment="PATH=${APP_DIR}/backend/venv/bin"
ExecStart=${APP_DIR}/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now better-social
systemctl restart better-social
sleep 2
systemctl --no-pager status better-social --lines=5 || true

log "5/8  Building frontend…"
cd "${APP_DIR}/frontend"
cat > "${APP_DIR}/frontend/.env" <<EOF
REACT_APP_BACKEND_URL=https://${DOMAIN}
WDS_SOCKET_PORT=443
EOF
sudo -u www-data yarn install --frozen-lockfile
sudo -u www-data yarn build

log "6/8  Configuring Nginx…"
cat > /etc/nginx/sites-available/better-social <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} ${WWW_DOMAIN};

    client_max_body_size 20M;

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }

    # React build
    root ${APP_DIR}/frontend/build;
    index index.html;
    location / {
        try_files \$uri /index.html;
    }

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
}
EOF

ln -sf /etc/nginx/sites-available/better-social /etc/nginx/sites-enabled/better-social
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

log "7/8  Configuring firewall…"
ufw allow OpenSSH || true
ufw allow 'Nginx Full' || true
yes | ufw enable || true

log "8/8  Issuing SSL certificate (Let's Encrypt)…"
certbot --nginx --non-interactive --agree-tos -m "${ADMIN_EMAIL}" \
  -d "${DOMAIN}" -d "${WWW_DOMAIN}" --redirect || \
  echo "⚠️  Certbot failed — make sure your DNS A record points to this server, then re-run: certbot --nginx -d ${DOMAIN} -d ${WWW_DOMAIN}"

echo
echo "════════════════════════════════════════════════════════"
echo "✅  Deployment complete."
echo "    Site:        https://${DOMAIN}"
echo "    Admin panel: https://${DOMAIN}/admin"
echo "    Backend log: journalctl -u better-social -f"
echo "    Update later: cd ${APP_DIR} && git pull && bash deploy.sh"
echo "════════════════════════════════════════════════════════"
