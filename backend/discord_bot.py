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

    # ---------- lifecycle ----------
    async def start(self, db, token: str, activity_text: str = "", banned_words: Optional[list] = None):
        await self.stop()
        self.db = db
        self.banned_words = [w.strip().lower() for w in (banned_words or []) if w.strip()]
        self.activity_text = activity_text or ""
        self.status = "starting"
        self.error = ""

        intents = discord.Intents.default()
        intents.message_content = True
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
        async def on_message(message: discord.Message):
            if message.author.bot:
                return
            # --- DMs → store for the admin DM console ---
            if isinstance(message.channel, discord.DMChannel):
                await mgr._store_dm(message.author, message.content, direction="in")
                return
            # --- guild moderation ---
            content_l = (message.content or "").lower()
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
        out = {"status": self.status, "error": self.error, "activity_text": self.activity_text}
        if self.client and self.client.user:
            out["bot_username"] = str(self.client.user)
            out["bot_id"] = str(self.client.user.id)
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
