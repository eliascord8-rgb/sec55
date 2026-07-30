# Better Social — VPS Deployment Guide

This guide takes your Better Social app from local preview to a **live public URL on any VPS** (Hetzner, DigitalOcean, Vultr, OVH, etc.) with HTTPS.

Estimated time: **30–45 minutes**.

---

## 0. What you need before you start

| Item | Why |
|------|-----|
| A **VPS** with Ubuntu 22.04 or 24.04 (2 vCPU / 2 GB RAM minimum, 4 GB recommended) | Runs backend + Mongo + frontend |
| A **domain name** (e.g. `bettersocial.com`) pointed to your VPS IP | Needed for HTTPS |
| **Root/sudo SSH access** | Install packages |
| Your `.env` values (Emergent LLM key, NOWPayments key, PayPal receiver email, Discord bot token, Elastic Email key, etc.) | Copy from the preview env |

Point a DNS **A record** for `bettersocial.com` **and** `www.bettersocial.com` at your VPS IP before you begin. SSL issuance won't work otherwise.

---

## 1. Prepare the server (5 min)

SSH in as root, then:

```bash
apt update && apt upgrade -y
apt install -y git curl ufw nginx certbot python3-certbot-nginx \
                python3.11 python3.11-venv python3-pip \
                build-essential

# Firewall — SSH + HTTP + HTTPS only
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# MongoDB 7
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list
apt update && apt install -y mongodb-org
systemctl enable --now mongod

# Node 20 (for the React build) + Yarn
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
corepack enable
```

---

## 2. Clone your project (2 min)

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO.git bettersocial
cd bettersocial
```

If your repo is private, generate a fine-grained GitHub PAT and use `https://oauth2:PAT@github.com/USER/REPO.git`.

---

## 3. Backend setup (5 min)

```bash
cd /opt/bettersocial/backend

# venv + deps
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
```

**Edit `/opt/bettersocial/backend/.env`**:

```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=bettersocial_prod

# Emergent-managed keys (copy from your preview backend/.env)
EMERGENT_LLM_KEY=sk-emergent-XXXXXXXX

# Discord purchase-notification channel (already set to your channel)
DISCORD_PURCHASE_CHANNEL_ID=1477630409742221499

# Owner credentials (change these!)
OWNER_USERNAME=Balkin
OWNER_PASSWORD=YOUR_STRONG_OWNER_PASSWORD
OWNER_EMAIL=you@yourdomain.com

# Dedicated DB manager owner (used for /db-manager)
DBMGR_USERNAME=dbmanager
DBMGR_PASSWORD=YOUR_STRONG_DBM_PASSWORD
DBMGR_EMAIL=dbadmin@yourdomain.com

# Email (Elastic Email) — needed for password-reset emails
ELASTIC_EMAIL_API_KEY=xxxx
ELASTIC_EMAIL_FROM=noreply@yourdomain.com

# NOWPayments (optional)
NOWPAYMENTS_API_KEY=xxxx
NOWPAYMENTS_IPN_SECRET=xxxx

# Public URL — used in outgoing emails for reset/verify links
PUBLIC_APP_URL=https://bettersocial.com
```

Test it once:

```bash
cd /opt/bettersocial/backend
source .venv/bin/activate
uvicorn server:app --host 127.0.0.1 --port 8001
# Ctrl+C after you see "Application startup complete."
```

---

## 4. systemd service for the backend (2 min)

Create `/etc/systemd/system/bettersocial-backend.service`:

```ini
[Unit]
Description=Better Social FastAPI backend
After=network.target mongod.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bettersocial/backend
Environment="PATH=/opt/bettersocial/backend/.venv/bin"
EnvironmentFile=/opt/bettersocial/backend/.env
ExecStart=/opt/bettersocial/backend/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now bettersocial-backend
systemctl status bettersocial-backend
```

---

## 5. Frontend build (3 min)

```bash
cd /opt/bettersocial/frontend
```

**Edit `/opt/bettersocial/frontend/.env`** — change `REACT_APP_BACKEND_URL` to your own domain:

```env
REACT_APP_BACKEND_URL=https://bettersocial.com
WDS_SOCKET_PORT=443
```

Build:

```bash
yarn install --frozen-lockfile
yarn build
```

The finished static site is now at `/opt/bettersocial/frontend/build`.

---

## 6. Nginx reverse-proxy (3 min)

Create `/etc/nginx/sites-available/bettersocial`:

```nginx
server {
    listen 80;
    server_name bettersocial.com www.bettersocial.com;

    # React build
    root /opt/bettersocial/frontend/build;
    index index.html;

    # File upload limit — needed for AI voice notes / db-manager uploads
    client_max_body_size 50m;

    # Backend API — /api/* -> uvicorn on port 8001
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # WebSocket for public/AI chat
    location /ws/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }

    # React SPA — serve index.html for any unknown path
    location / {
        try_files $uri /index.html;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/bettersocial /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

Visit `http://bettersocial.com` — you should see the guest landing page (still HTTP for now).

---

## 7. Free SSL via Let's Encrypt (2 min)

```bash
certbot --nginx -d bettersocial.com -d www.bettersocial.com \
        --agree-tos -m you@yourdomain.com --redirect --non-interactive
```

Certbot patches your Nginx config, forces HTTPS, and auto-renews. Visit `https://bettersocial.com` — you're live with a green padlock.

---

## 8. Verify everything

```bash
# Backend responds
curl -s https://bettersocial.com/api/features | head -c 200

# Owner login works
curl -s https://bettersocial.com/api/auth/captcha

# DB is your production DB
mongosh --eval 'db.getSiblingDB("bettersocial_prod").users.countDocuments()'

# Backend logs
journalctl -u bettersocial-backend -f
```

Open `https://bettersocial.com/admin?haha123` → log in as `Balkin` → go to **DB Backups** and click **Run backup now** to confirm the 6-hour backup worker is wired.

---

## 9. Update workflow (whenever you push new code)

```bash
cd /opt/bettersocial
git pull
# backend
source backend/.venv/bin/activate && pip install -r backend/requirements.txt && deactivate
systemctl restart bettersocial-backend
# frontend
cd frontend && yarn install --frozen-lockfile && yarn build && cd ..
# nginx serves the new build immediately — no reload needed
```

---

## 10. Backups off-site (recommended)

The app already snapshots the DB to `/opt/bettersocial/backups/*.json.gz` every 6 hours. Push those to S3-compatible storage nightly:

```bash
apt install -y rclone
rclone config       # add a "backups" remote (Backblaze B2, R2, S3...)

# cron: nightly at 03:00
echo '0 3 * * * root rclone copy /opt/bettersocial/backups backups:bettersocial-backups --min-age 1h' \
    > /etc/cron.d/bettersocial-backup-sync
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Frontend loads but every API call is `Failed to fetch` | `REACT_APP_BACKEND_URL` in `frontend/.env` doesn't match your real domain — rebuild after fixing |
| Backend returns 502 through Nginx | `systemctl status bettersocial-backend` and check `journalctl -u bettersocial-backend -n 100` |
| Password reset emails don't arrive | Elastic Email key wrong / sender not verified — check `ELASTIC_EMAIL_*` |
| Discord "new client bought" not posting | The bot isn't running — Admin → Discord Bot → Start; then Admin → Discord → test purchase notification |
| Certbot fails with "DNS problem" | Your A record hasn't propagated yet — wait 5 min and re-run |
| MongoDB connection refused | `systemctl status mongod` — reinstall if the service is missing |

---

Deployed. Every 6 hours the DB backs itself up, the AI ticket assistant is live, and new orders will ping your Discord channel `1477630409742221499`.
