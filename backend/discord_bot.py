"""In-process Discord moderation bot, managed from the admin panel."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import discord

logger = logging.getLogger(__name__)


class DiscordBotManager:
    def __init__(self):
        self.client: Optional[discord.Client] = None
        self.task: Optional[asyncio.Task] = None
        self.status = "stopped"  # stopped | starting | running | error
        self.error = ""
        self.db = None
        self.banned_words: list[str] = []
        self.activity_text = ""
        self.welcome_enabled = False
        self.welcome_message = "Welcome {user} to {server}! 🎉"
        self.welcome_channel = ""
        self.mass_dm_task: Optional[asyncio.Task] = None
        self.mass_dm_progress: dict = {}

    # ---------- lifecycle ----------
    async def start(self, db, token: str, activity_text: str = "", banned_words: Optional[list] = None,
                    welcome: Optional[dict] = None):
        await self.stop()
        self.db = db
        self.banned_words = [w.strip().lower() for w in (banned_words or []) if w.strip()]
        self.activity_text = activity_text or ""
        welcome = welcome or {}
        self.welcome_enabled = bool(welcome.get("enabled"))
        self.welcome_message = welcome.get("message") or self.welcome_message
        self.welcome_channel = welcome.get("channel") or ""
        self.status = "starting"
        self.error = ""

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        client = discord.Client(intents=intents)
        self.client = client
        mgr = self

        @client.event
        async def on_ready():
            mgr.status = "running"
            logger.info("[discord] bot online as %s", client.user)
            if mgr.activity_text:
                try:
                    await client.change_presence(activity=discord.Game(name=mgr.activity_text))
                except Exception as e:
                    logger.warning("[discord] presence set failed: %s", e)

        @client.event
        async def on_member_join(member: discord.Member):
            if not mgr.welcome_enabled or not mgr.welcome_message:
                return
            guild = member.guild
            ch = None
            if mgr.welcome_channel:
                ch = discord.utils.get(guild.text_channels, name=mgr.welcome_channel.lstrip("#").lower())
            if ch is None:
                ch = guild.system_channel
            if ch is None:
                ch = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if ch:
                try:
                    txt = mgr.welcome_message.replace("{user}", member.mention).replace("{server}", guild.name)
                    await ch.send(txt)
                except Exception as e:
                    logger.warning("[discord] welcome send failed: %s", e)

        @client.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return
            # --- DMs → store for the admin DM console ---
            if isinstance(message.channel, discord.DMChannel):
                await mgr._store_dm(message.author, message.content, direction="in")
                return
            # --- ticket bot ---
            content_lower = (message.content or "").lower()
            if content_lower.startswith("!ticket") and message.guild:
                subject = message.content[7:].strip() or "Support request"
                guild = message.guild
                try:
                    cat = discord.utils.get(guild.categories, name="Tickets")
                    if cat is None:
                        cat = await guild.create_category("Tickets")
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        message.author: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
                    }
                    cname = f"ticket-{message.author.name}".lower().replace(" ", "-")[:90]
                    chan = await guild.create_text_channel(cname, category=cat, overwrites=overwrites, topic=subject[:250])
                    await chan.send(
                        f"🎫 Ticket opened by {message.author.mention} — **{subject}**\n"
                        f"A staff member will reply soon. Type `!close` to close this ticket."
                    )
                    await message.channel.send(f"{message.author.mention} your ticket is ready → {chan.mention}", delete_after=10)
                    await mgr._mod_log(f"ticket_open: {subject[:80]}", message)
                except Exception as e:
                    try:
                        await message.channel.send(f"⚠️ Couldn't open ticket: {e}", delete_after=8)
                    except Exception:
                        pass
                return
            if content_lower.startswith("!close") and message.guild and message.channel.name.startswith("ticket-"):
                perms = message.author.guild_permissions
                is_opener = message.channel.name == f"ticket-{message.author.name}".lower().replace(" ", "-")[:90]
                if perms.manage_channels or perms.administrator or is_opener:
                    try:
                        await message.channel.send("🔒 Closing ticket in 3 seconds…")
                        await mgr._mod_log("ticket_close", message)
                        await asyncio.sleep(3)
                        await message.channel.delete(reason=f"Ticket closed by {message.author}")
                    except Exception as e:
                        logger.warning("[discord] ticket close failed: %s", e)
                return
            # --- guild moderation ---
            content_l = content_lower
            if mgr.banned_words and any(w in content_l for w in mgr.banned_words):
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention} your message was removed (banned word).",
                        delete_after=6,
                    )
                    await mgr._mod_log("banned_word_delete", message)
                except Exception as e:
                    logger.warning("[discord] mod delete failed: %s", e)
                return
            # --- simple mod commands (admins only) ---
            if message.content.startswith("!") and message.guild:
                perms = message.author.guild_permissions
                if not (perms.administrator or perms.manage_messages):
                    return
                parts = message.content.split()
                cmd = parts[0].lower()
                try:
                    if cmd == "!purge" and len(parts) > 1 and parts[1].isdigit():
                        n = min(int(parts[1]), 100)
                        await message.channel.purge(limit=n + 1)
                        await message.channel.send(f"🧹 Purged {n} messages.", delete_after=5)
                        await mgr._mod_log(f"purge {n}", message)
                    elif cmd == "!kick" and message.mentions:
                        await message.guild.kick(message.mentions[0], reason=f"by {message.author}")
                        await message.channel.send(f"👢 Kicked {message.mentions[0].mention}.")
                        await mgr._mod_log("kick", message)
                    elif cmd == "!ban" and message.mentions:
                        await message.guild.ban(message.mentions[0], reason=f"by {message.author}")
                        await message.channel.send(f"🔨 Banned {message.mentions[0].mention}.")
                        await mgr._mod_log("ban", message)
                except Exception as e:
                    try:
                        await message.channel.send(f"⚠️ Command failed: {e}", delete_after=8)
                    except Exception:
                        pass

        async def runner():
            try:
                await client.start(token)
            except Exception as e:
                mgr.status = "error"
                mgr.error = str(e)[:300]
                logger.error("[discord] bot crashed: %s", e)

        self.task = asyncio.create_task(runner())
        return {"ok": True, "status": self.status}

    async def stop(self):
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass
        if self.task:
            self.task.cancel()
        self.client = None
        self.task = None
        self.status = "stopped"
        self.error = ""
        return {"ok": True, "status": "stopped"}

    # ---------- info ----------
    def info(self) -> dict:
        out = {
            "status": self.status, "error": self.error, "activity_text": self.activity_text,
            "welcome_enabled": self.welcome_enabled, "welcome_message": self.welcome_message,
            "welcome_channel": self.welcome_channel,
            "mass_dm": self.mass_dm_progress or None,
        }
        if self.client and self.client.user:
            out["bot_username"] = str(self.client.user)
            out["bot_id"] = str(self.client.user.id)
            out["guild_count"] = len(self.client.guilds)
            try:
                out["bot_avatar"] = str(self.client.user.display_avatar.url)
            except Exception:
                out["bot_avatar"] = None
        return out

    def _require_running(self):
        if self.status != "running" or not self.client or not self.client.user:
            raise RuntimeError("Bot is not running — start it first")

    # ---------- actions ----------
    async def set_activity(self, text: str):
        self._require_running()
        self.activity_text = text or ""
        await self.client.change_presence(activity=discord.Game(name=text) if text else None)
        return {"ok": True}

    async def set_avatar(self, image_bytes: bytes):
        self._require_running()
        await self.client.user.edit(avatar=image_bytes)
        return {"ok": True}

    async def send_dm(self, discord_user_id: str, text: str) -> dict:
        self._require_running()
        user = await self.client.fetch_user(int(discord_user_id))
        await user.send(text)
        await self._store_dm(user, text, direction="out")
        return {"ok": True, "to": str(user)}

    async def send_channel_message(self, channel_id: str, text: str) -> dict:
        """Post a message to a specific Discord channel by ID. Silent no-op if
        the bot is not currently running so callers don't have to guard it."""
        if self.status != "running" or not self.client:
            return {"ok": False, "reason": "bot not running"}
        try:
            ch = self.client.get_channel(int(channel_id))
            if ch is None:
                ch = await self.client.fetch_channel(int(channel_id))
            await ch.send(text)
            return {"ok": True, "channel": str(channel_id)}
        except Exception as e:
            logger.warning("[discord] send_channel_message failed: %s", e)
            return {"ok": False, "reason": str(e)}

    @staticmethod
    def mask_username(name: str) -> str:
        """Privacy-preserving username mask. 'balkin' → 'b****n', 'jo' → 'j*'."""
        if not name:
            return "***"
        name = str(name)
        if len(name) <= 2:
            return name[0] + "*"
        return name[0] + "*" * (len(name) - 2) + name[-1]

    # ---------- servers ----------
    def list_servers(self) -> list:
        self._require_running()
        return [
            {"id": str(g.id), "name": g.name, "member_count": g.member_count or 0,
             "icon": str(g.icon.url) if g.icon else None}
            for g in self.client.guilds
        ]

    async def leave_server(self, guild_id: str) -> dict:
        self._require_running()
        g = self.client.get_guild(int(guild_id))
        if not g:
            raise RuntimeError("Server not found")
        await g.leave()
        return {"ok": True, "left": g.name}

    # ---------- mass DM ----------
    def start_mass_dm(self, text: str) -> dict:
        self._require_running()
        if self.mass_dm_task and not self.mass_dm_task.done():
            raise RuntimeError("A mass DM is already running")
        self.mass_dm_progress = {"status": "collecting", "sent": 0, "failed": 0, "total": 0}
        mgr = self

        async def run():
            try:
                seen, members = set(), []
                for g in mgr.client.guilds:
                    try:
                        async for m in g.fetch_members(limit=None):
                            if not m.bot and m.id not in seen:
                                seen.add(m.id)
                                members.append(m)
                    except Exception as e:
                        logger.warning("[discord] mass-dm member fetch failed for %s: %s", g.name, e)
                mgr.mass_dm_progress.update({"status": "running", "total": len(members)})
                for m in members:
                    try:
                        await m.send(text)
                        mgr.mass_dm_progress["sent"] += 1
                    except Exception:
                        mgr.mass_dm_progress["failed"] += 1
                    await asyncio.sleep(1.5)  # gentle rate limit — avoids Discord bans
                mgr.mass_dm_progress["status"] = "done"
                logger.info("[discord] mass DM finished: %s", mgr.mass_dm_progress)
            except Exception as e:
                mgr.mass_dm_progress["status"] = "error"
                mgr.mass_dm_progress["error"] = str(e)[:200]

        self.mass_dm_task = asyncio.create_task(run())
        return {"ok": True, "started": True}

    # ---------- persistence ----------
    async def _store_dm(self, user, text: str, direction: str):
        if self.db is None:
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            await self.db.discord_dms.insert_one({
                "id": str(uuid.uuid4()),
                "discord_user_id": str(user.id),
                "discord_username": str(user),
                "direction": direction,
                "text": (text or "")[:2000],
                "created_at": now,
            })
        except Exception as e:
            logger.warning("[discord] dm store failed: %s", e)

    async def _mod_log(self, action: str, message):
        if self.db is None:
            return
        try:
            await self.db.discord_mod_log.insert_one({
                "id": str(uuid.uuid4()),
                "action": action,
                "author": str(message.author),
                "channel": str(message.channel),
                "guild": str(message.guild) if message.guild else None,
                "content": (message.content or "")[:500],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass


bot_manager = DiscordBotManager()
