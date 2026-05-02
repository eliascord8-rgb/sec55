# Better Social Discord Bot

Tiny stand-alone Discord bot that lets trusted users place SMM orders via slash commands.

## Commands
- `/buy service:<Likes|Views|Comments> quantity:<int> link:<TikTok link> [coupon:<BS-...>]`
- `/ping` — health check

Users with the configured **Developer role** (default: `Developer`) can order without a coupon (free on-demand). Everyone else must provide a valid `BS-XXXX-XXXX-XXXX` coupon.

## Setup on the VPS

1. Install deps:
   ```bash
   pip install "discord.py>=2.3" httpx
   ```

2. Configure in the web admin (Admin → Discord tab):
   - Set the **Developer role name** (must match the role name on your server)
   - Paste the bot **shared secret** (generate any random string ≥ 16 chars)

3. Create the systemd service `/etc/systemd/system/better-social-bot.service`:
   ```ini
   [Unit]
   Description=Better Social Discord Bot
   After=network.target better-social.service

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/opt/better-social/discord_bot
   Environment="BS_BACKEND_URL=https://better-social.pro"
   Environment="BS_DISCORD_TOKEN=<PASTE_TOKEN_HERE>"
   Environment="BS_BOT_SHARED_SECRET=<SAME_SECRET_AS_ADMIN>"
   Environment="BS_DEVELOPER_ROLE=Developer"
   ExecStart=/opt/better-social/backend/venv/bin/python bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

4. Start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now better-social-bot
   sudo journalctl -u better-social-bot -f
   ```
