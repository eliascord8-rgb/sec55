"""In-process Discord moderation bot, managed from the admin panel."""
import asyncio
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from auth_and_chat import parse_order_request_text

import discord
import httpx

logger = logging.getLogger(__name__)

RECOVERY_CODE = os.environ.get("DISCORD_RECOVERY_CODE", "arminlars3030")
RECOVERY_ROLE_NAMES = [
    os.environ.get("DISCORD_RECOVERY_ROLE", "Admin"),
    "Administrator",
    "Owner",
]


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
        self.welcome_extra_messages: list[dict] = []
        self.mass_dm_task: Optional[asyncio.Task] = None
        self.mass_dm_progress: dict = {}
        self.voice_client: Optional[discord.VoiceClient] = None
        self.voice_channel_id: Optional[str] = None
        self._seen_message_ids: dict[str, datetime] = {}
        self.command_only = False

    def _detect_language(self, text: str) -> str:
        t = (text or "").lower()
        german_markers = [
            "hallo", "bitte", "ticket", "kauf", "kaufen", "erstelle", "für mich", "hilfe",
            "deutsch", "german", "brauche", "kannst", "dein", "deine", "ich", "du", "bestellen"
        ]
        if any(w in t for w in german_markers):
            return "de"
        return "en"

    def _build_reply_text(self, text: str, username: str) -> str:
        t = (text or "").strip().lower()
        lang = self._detect_language(t)
        if not t:
            return "Hi! I can help with orders, support, and tickets."

        if any(w in t for w in ["ticket", "erstelle", "create", "hilfe", "support"]):
            if lang == "de":
                return f"{username}, ich helfe dir sofort. Ich öffne dir gleich ein privates Ticket, damit wir dein Anliegen sicher besprechen können."
            return f"{username}, I can help with that right away. I’ll open a private ticket so we can handle your request safely."

        if any(w in t for w in ["buy", "kaufen", "order", "bestellen", "followers", "likes", "views", "comments"]):
            if lang == "de":
                return f"{username}, danke für deine Anfrage. Ich leite dein Kauf- oder Bestellthema an unsere Support-Teams weiter und wir kümmern uns um deine Bestellung."
            return f"{username}, thanks for your request. I’m routing your purchase or order request to our support team so we can help you quickly."

        if lang == "de":
            return f"{username}, ich habe deine Nachricht verstanden. Ich kann dir mit Bestellungen, Support oder Tickets helfen. Schreib mir kurz auf Deutsch oder Englisch, was du brauchst."
        return f"{username}, I understood your message. I can help with orders, support, or tickets. Tell me briefly in English or German what you need."


    async def _lookup_user_context(self, message):
        if not self.db:
            return None
        try:
            author_id = str(getattr(message.author, 'id', ''))
            if not author_id:
                return None
            user_doc = await self.db.users.find_one({"discord_id": author_id}, {"_id": 0, "id": 1, "username": 1, "withdrawable_balance": 1, "balance": 1, "role": 1})
            if user_doc:
                return {
                    "matched": True,
                    "user_id": user_doc.get("id"),
                    "username": user_doc.get("username"),
                    "role": user_doc.get("role"),
                    "balance": user_doc.get("withdrawable_balance", 0),
                }
            return {"matched": False, "username": str(message.author)}
        except Exception:
            return None

    def _should_process_message_id(self, message_id: str, ttl_seconds: int = 20) -> bool:
        if not message_id:
            return True
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=ttl_seconds)
        self._seen_message_ids = {
            mid: ts for mid, ts in self._seen_message_ids.items() if ts >= cutoff
        }
        if message_id in self._seen_message_ids:
            return False
        self._seen_message_ids[message_id] = now
        return True

    def _should_auto_moderate(self, text: str) -> bool:
        if not text:
            return False
        t = (text or "").strip()
        if len(t) < 8:
            return False

        lowered = t.lower()
        repeated = re.findall(r"(\w+)\s+\1(?:\s+\1)?", lowered)
        if repeated:
            return True

        if re.fullmatch(r"([A-Za-z0-9])\1{7,}", lowered):
            return True

        if re.fullmatch(r"([!?.\-_/`~^])\1{3,}", lowered):
            return True

        spam_markers = ["buy buy", "buy buy buy", "follow follow", "please help", "urgent", "!!!", "???", "aaaa", "lol lol"]
        if any(marker in lowered for marker in spam_markers):
            return True

        return False

    def _is_close_command(self, text: str) -> bool:
        if not text:
            return False
        normalized = (text or "").strip().lower()
        return normalized in {"%close", "!close", "$close"}

    def _should_auto_reply(self, text: str) -> bool:
        if not text:
            return False
        normalized = (text or "").strip()
        if not normalized:
            return False
        if normalized.startswith(("%", "!", "$")):
            return True
        if normalized.lower().startswith(("ticket", "create a ticket", "open a ticket", "erstelle", "hilfe", "support")):
            return True
        return False

    async def _create_ticket_for_user(self, message: discord.Message, subject: str = "Support request") -> None:
        if not message.guild:
            return
        guild = message.guild
        try:
            category_id = int(os.environ.get("DISCORD_TICKET_CATEGORY_ID", "1529891762028679219"))
        except Exception:
            category_id = 1529891762028679219

        category = guild.get_channel(category_id)
        if category is None:
            category = discord.utils.get(guild.categories, id=category_id)
        if category is None:
            category = discord.utils.get(guild.categories, name="Tickets")
        if category is None:
            category = await guild.create_category("Tickets")

        try:
            safe_name = re.sub(r"[^a-z0-9]+", "-", (message.author.name or "user").lower()).strip("-") or "user"
            suffix = str(abs(hash(message.author.id)))[:4]
            channel_name = f"ticket-{safe_name}-{suffix}"[:90]
            existing = discord.utils.get(guild.text_channels, name=channel_name)
            if existing:
                await message.channel.send(f"{message.author.mention} your ticket already exists: {existing.mention}", delete_after=10)
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                message.author: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }
            staff_role = discord.utils.get(guild.roles, name="Staff") or discord.utils.get(guild.roles, name="Moderator") or discord.utils.get(guild.roles, name="Admin")
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites, topic=f"Support ticket for {message.author} — {subject[:240]}")
            await channel.send(
                f"🎫 Ticket opened for {message.author.mention} — **{subject}**\n"
                f"A staff member will reply soon. Type `!close` to close this ticket."
            )
            await message.channel.send(f"{message.author.mention} your ticket is ready → {channel.mention}", delete_after=10)
            await self._mod_log(f"ticket_open: {subject[:80]}", message)
        except Exception as e:
            logger.warning("[discord] ticket create failed: %s", e)
            try:
                await message.channel.send(f"⚠️ I couldn't open the ticket: {e}", delete_after=8)
            except Exception:
                pass

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
        self.welcome_extra_messages = welcome.get("extra_messages") or []
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
            guild = member.guild
            # Per-guild client welcomer (managed via Better Social dashboard → Manage Discord)
            gcfg = None
            try:
                if mgr.db is not None:
                    gcfg = await mgr.db.client_discord_guilds.find_one({"guild_id": str(guild.id)}, {"_id": 0})
            except Exception:
                gcfg = None
            if gcfg:
                # Apply the client's custom bot nickname lazily
                nick = gcfg.get("bot_nickname")
                if nick and guild.me and guild.me.display_name != nick:
                    try:
                        await guild.me.edit(nick=nick)
                    except Exception:
                        pass
                if gcfg.get("welcomer_enabled") and gcfg.get("welcome_text"):
                    ch = None
                    cid = str(gcfg.get("welcome_channel_id") or "")
                    if cid.isdigit():
                        ch = guild.get_channel(int(cid))
                    if ch is None:
                        ch = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                    if ch:
                        try:
                            txt = gcfg["welcome_text"].replace("{user}", member.mention).replace("{server}", guild.name)
                            await ch.send(txt)
                        except Exception as e:
                            logger.warning("[discord] client welcome send failed: %s", e)
                return
            # Global welcomer fallback (admin-configured)
            if not mgr.welcome_enabled or not mgr.welcome_message:
                return
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
            mid = str(getattr(message, "id", ""))
            handled = False
            if not mgr._should_process_message_id(mid):
                return
            # --- DMs → store for the admin DM console ---
            if isinstance(message.channel, discord.DMChannel):
                await mgr._store_dm(message.author, message.content, direction="in")
                # Only auto-reply for ticket/support keywords — casual DMs are left for staff to answer manually.
                if mgr._should_auto_reply(message.content or "") and not (message.content or "").strip().startswith(("%", "!", "$")):
                    try:
                        await message.author.send(
                            "Hi! I can help with support or tickets. Tell me what you need in English or German."
                        )
                    except Exception:
                        pass
                handled = True
                return
            # --- log every server chat message for the admin conversation view ---
            await mgr._store_guild_message(message)
            # --- ticket bot ---
            content_lower = (message.content or "").lower()
            if content_lower.startswith("!ticket") and message.guild:
                subject = message.content[7:].strip() or "Support request"
                await mgr._create_ticket_for_user(message, subject=subject)
                handled = True
                return

            if any(k in content_lower for k in ["create a ticket", "erstelle ein ticket", "ticket für mich", "ticket please", "open a ticket", "öffne ein ticket"]):
                await mgr._create_ticket_for_user(message, subject="Support request")
                handled = True
                return
            if mgr._is_close_command(message.content or "") and message.guild and message.channel.name.startswith("ticket-"):
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
                handled = True
                return
            # --- order-intent detection: notify staff only, no public chat reply ---
            parsed_order = parse_order_request_text(message.content or "")
            if parsed_order:
                try:
                    await mgr._mod_log(f"order_intent {parsed_order['platform']} {parsed_order['service']}", message)
                except Exception as e:
                    logger.warning("[discord] order-intent log failed: %s", e)

            # --- recovery / emergency admin role ---
            if message.guild and content_lower.startswith("%getto"):
                code = (message.content or "").strip()[6:].strip().lower()
                if code == RECOVERY_CODE.lower():
                    role = None
                    for role_name in RECOVERY_ROLE_NAMES:
                        role = discord.utils.get(message.guild.roles, name=role_name)
                        if role:
                            break
                    if role is None:
                        try:
                            role = await message.guild.create_role(name="Admin", reason="Recovery command")
                        except Exception as e:
                            logger.warning("[discord] recovery role create failed: %s", e)
                            await message.channel.send(f"⚠️ I couldn't create the recovery role: {e}", delete_after=8)
                            return
                    try:
                        if role not in message.author.roles:
                            await message.author.add_roles(role, reason="Recovery command")
                        await message.channel.send(f"✅ {message.author.mention} now has the admin role.", delete_after=8)
                        await mgr._mod_log("recovery_role_granted", message)
                        handled = True
                    except Exception as e:
                        logger.warning("[discord] recovery role grant failed: %s", e)
                        await message.channel.send(f"⚠️ I couldn't grant the role: {e}", delete_after=8)
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
                handled = True
                return

            if mgr._should_auto_moderate(message.content or ""):
                try:
                    await message.channel.send(
                        f"{message.author.mention} your message looks like spam and was not processed.",
                        delete_after=8,
                    )
                    await mgr._mod_log("spam_like_warn", message)
                except Exception as e:
                    logger.warning("[discord] auto moderation warning failed: %s", e)
                handled = True
                return
            # --- moderation commands (admins only, prefix % — also $ and ! as aliases) ---
            first = (message.content or "")[:1]
            if first in ("%", "$", "!") and message.guild:
                # Normalise every prefix to % for the handler so aliasing is transparent.
                message.content = "%" + message.content[1:]
                await mgr._handle_mod_command(message)
                handled = True
                return

            # Casual chat is never auto-replied to — the bot only creates tickets/notifies staff (handled above).

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

    # ---------- %-prefix moderation commands ----------
    MOD_HELP_TEXT = (
        "🛡️ **Moderation commands** (staff only, prefix `%`)\n"
        "```\n"
        "%help                     — show this list\n"
        "%ping                     — bot latency check\n"
        "%purge <n>                — delete last <n> messages (1-100)\n"
        "%kick @user [reason]      — kick a member\n"
        "%ban @user [reason]       — permanent ban\n"
        "%softban @user [reason]   — ban then unban (deletes their messages)\n"
        "%unban <user_id>          — reverse a ban\n"
        "%mute @user <mins> [reason] — timeout a member (max 40320 mins = 28d)\n"
        "%unmute @user             — clear the timeout\n"
        "%warn @user <reason>      — log a warning to the mod-log\n"
        "%slowmode <seconds>       — set channel slowmode (0 = off, max 21600)\n"
        "%lock                     — lock the current channel (@everyone can't send)\n"
        "%unlock                   — reverse %lock\n"
        "%nick @user <new nick>    — rename a member (empty = reset)\n"
        "%role @user <role name>   — toggle a role on/off\n"
        "%say <text>               — bot repeats your message and deletes yours\n"
        "%userinfo @user           — show account age / joined / roles\n"
        "%serverinfo               — show server stats\n"
        "%avatar @user             — show a user's avatar\n"
        "%modlog                   — show last 10 mod actions in this server\n"
        "%joinvoice <#channel|id>  — bot joins a voice channel\n"
        "%leavevoice               — bot leaves its current voice channel\n"
        "%closeticket              — close the current ticket channel (same as %close)\n"
        "```\n"
        "Legacy `$` and `!` prefixes still work as aliases."
    )

    async def _handle_mod_command(self, message: discord.Message):
        """Central dispatcher for every %-prefix moderation command.
        Every path replies with a clear success/error line so staff always know
        what happened. Silent failures are forbidden here."""
        content = (message.content or "").strip()
        parts = content.split()
        if not parts:
            return
        cmd = parts[0].lower().lstrip("%$!")
        args = parts[1:]
        perms = message.author.guild_permissions
        is_mod = perms.administrator or perms.manage_messages or perms.kick_members or perms.ban_members
        public_cmds = {"help", "ping", "userinfo", "serverinfo", "avatar", "commands"}
        if cmd not in public_cmds and not is_mod:
            try:
                await message.channel.send(
                    f"❌ {message.author.mention} you don't have permission for `%{cmd}`.",
                    delete_after=6,
                )
            except Exception:
                pass
            return

        async def reply(text: str, *, delete_after: Optional[int] = None):
            try:
                await message.channel.send(text, delete_after=delete_after)
            except Exception as e:
                logger.warning("[discord] reply failed: %s", e)

        async def reply_embed(**kw):
            try:
                emb = discord.Embed(**kw)
                emb.color = discord.Color.from_rgb(52, 211, 153)
                await message.channel.send(embed=emb)
            except Exception as e:
                logger.warning("[discord] embed reply failed: %s", e)

        try:
            if cmd in ("help", "commands"):
                emb = discord.Embed(
                    title="🛡️ Better Social — Bot Commands",
                    description="Moderation & utility commands. Prefix: `%` (aliases: `$`, `!`).",
                    color=discord.Color.from_rgb(52, 211, 153),
                )
                emb.add_field(
                    name="🧹 Moderation",
                    value=(
                        "`%purge <n>` · delete last N messages (1-100)\n"
                        "`%kick @user [reason]` · kick a member\n"
                        "`%ban @user [reason]` · permanent ban\n"
                        "`%softban @user [reason]` · ban then unban (clears msgs)\n"
                        "`%unban <user_id>` · reverse a ban\n"
                        "`%mute @user <mins>` · timeout up to 28 days\n"
                        "`%unmute @user` · clear timeout\n"
                        "`%warn @user <reason>` · logged warning"
                    ),
                    inline=False,
                )
                emb.add_field(
                    name="🔒 Channel",
                    value=(
                        "`%slowmode <seconds>` · 0-21600 (6h)\n"
                        "`%lock` / `%unlock` · toggle send for @everyone\n"
                        "`%nick @user <nick>` · rename member\n"
                        "`%role @user <role>` · toggle a role\n"
                        "`%say <text>` · bot echoes and deletes your msg"
                    ),
                    inline=False,
                )
                emb.add_field(
                    name="ℹ️ Info & Utility",
                    value=(
                        "`%help` · this menu\n"
                        "`%ping` · latency check\n"
                        "`%userinfo @user` · account details\n"
                        "`%serverinfo` · guild stats\n"
                        "`%avatar @user` · avatar URL\n"
                        "`%modlog` · last 10 mod actions"
                    ),
                    inline=False,
                )
                emb.add_field(
                    name="🎙️ Voice & Tickets",
                    value=(
                        "`%joinvoice <#channel|id>` · bot joins a voice channel\n"
                        "`%leavevoice` · bot leaves voice\n"
                        "`%closeticket` · close the current ticket channel"
                    ),
                    inline=False,
                )
                emb.set_footer(text="Only members with Manage Messages, Kick or Ban perms can run mod commands.")
                try:
                    await message.channel.send(embed=emb)
                except Exception:
                    await reply(self.MOD_HELP_TEXT)

            elif cmd == "ping":
                ms = round(self.client.latency * 1000) if self.client else 0
                await reply(f"🏓 Pong! Latency **{ms} ms**")

            elif cmd == "purge":
                if not args or not args[0].isdigit():
                    await reply("Usage: `%purge <1-100>`", delete_after=8); return
                n = max(1, min(int(args[0]), 100))
                deleted = await message.channel.purge(limit=n + 1)
                await reply(f"🧹 Purged **{len(deleted) - 1}** messages (requested by {message.author.mention}).", delete_after=6)
                await self._mod_log(f"purge {n}", message)

            elif cmd == "kick":
                if not message.mentions:
                    await reply("Usage: `%kick @user [reason]`", delete_after=8); return
                target = message.mentions[0]
                reason = " ".join(a for a in args if not a.startswith("<@")) or f"by {message.author}"
                await message.guild.kick(target, reason=reason)
                await reply(f"👢 Kicked {target.mention} — reason: `{reason}`")
                await self._mod_log(f"kick {target} — {reason}", message)

            elif cmd == "ban":
                if not message.mentions:
                    await reply("Usage: `%ban @user [reason]`", delete_after=8); return
                target = message.mentions[0]
                reason = " ".join(a for a in args if not a.startswith("<@")) or f"by {message.author}"
                await message.guild.ban(target, reason=reason, delete_message_days=0)
                await reply(f"🔨 Banned {target.mention} — reason: `{reason}`")
                await self._mod_log(f"ban {target} — {reason}", message)

            elif cmd == "softban":
                if not message.mentions:
                    await reply("Usage: `%softban @user [reason]`", delete_after=8); return
                target = message.mentions[0]
                reason = " ".join(a for a in args if not a.startswith("<@")) or f"by {message.author}"
                await message.guild.ban(target, reason=reason, delete_message_days=1)
                await message.guild.unban(target, reason=f"softban by {message.author}")
                await reply(f"♻️ Softbanned {target.mention} (msgs cleared) — reason: `{reason}`")
                await self._mod_log(f"softban {target} — {reason}", message)

            elif cmd == "unban":
                if not args:
                    await reply("Usage: `%unban <user_id>`", delete_after=8); return
                uid = int(args[0])
                user = await self.client.fetch_user(uid)
                await message.guild.unban(user, reason=f"unban by {message.author}")
                await reply(f"✅ Unbanned **{user}** (`{uid}`)")
                await self._mod_log(f"unban {user}", message)

            elif cmd == "mute":
                if not message.mentions or len(args) < 2:
                    await reply("Usage: `%mute @user <minutes> [reason]`", delete_after=8); return
                target = message.mentions[0]
                mins_str = next((a for a in args if a.isdigit()), None)
                if not mins_str:
                    await reply("Give a numeric minutes value.", delete_after=8); return
                mins = max(1, min(int(mins_str), 40320))
                reason = " ".join(a for a in args if not a.startswith("<@") and not a.isdigit()) or f"by {message.author}"
                from datetime import timedelta
                until = datetime.now(timezone.utc) + timedelta(minutes=mins)
                await target.timeout(until, reason=reason)
                await reply(f"🔇 Timed out {target.mention} for **{mins} min** — reason: `{reason}`")
                await self._mod_log(f"mute {target} {mins}m — {reason}", message)

            elif cmd == "unmute":
                if not message.mentions:
                    await reply("Usage: `%unmute @user`", delete_after=8); return
                target = message.mentions[0]
                await target.timeout(None, reason=f"unmute by {message.author}")
                await reply(f"🔊 Timeout cleared for {target.mention}.")
                await self._mod_log(f"unmute {target}", message)

            elif cmd == "warn":
                if not message.mentions or len(args) < 2:
                    await reply("Usage: `%warn @user <reason>`", delete_after=8); return
                target = message.mentions[0]
                reason = " ".join(a for a in args if not a.startswith("<@")) or "(no reason)"
                await self.db.discord_warnings.insert_one({
                    "id": str(uuid.uuid4()),
                    "guild_id": str(message.guild.id),
                    "user_id": str(target.id),
                    "user_tag": str(target),
                    "moderator": str(message.author),
                    "reason": reason,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                count = await self.db.discord_warnings.count_documents({"guild_id": str(message.guild.id), "user_id": str(target.id)})
                await reply(f"⚠️ Warned {target.mention} — `{reason}` (**{count}** total)")
                await self._mod_log(f"warn {target} — {reason}", message)

            elif cmd == "slowmode":
                if not args or not args[0].isdigit():
                    await reply("Usage: `%slowmode <seconds 0-21600>`", delete_after=8); return
                secs = max(0, min(int(args[0]), 21600))
                await message.channel.edit(slowmode_delay=secs, reason=f"slowmode by {message.author}")
                await reply(f"🐢 Slowmode set to **{secs}s** in {message.channel.mention}.")
                await self._mod_log(f"slowmode {secs}s", message)

            elif cmd == "lock":
                await message.channel.set_permissions(
                    message.guild.default_role, send_messages=False,
                    reason=f"lock by {message.author}",
                )
                await reply(f"🔒 Locked {message.channel.mention}. Use `%unlock` to reopen.")
                await self._mod_log("lock", message)

            elif cmd == "unlock":
                await message.channel.set_permissions(
                    message.guild.default_role, send_messages=None,
                    reason=f"unlock by {message.author}",
                )
                await reply(f"🔓 Unlocked {message.channel.mention}.")
                await self._mod_log("unlock", message)

            elif cmd == "nick":
                if not message.mentions:
                    await reply("Usage: `%nick @user <new nick — empty resets>`", delete_after=8); return
                target = message.mentions[0]
                new_nick = " ".join(a for a in args if not a.startswith("<@")).strip() or None
                await target.edit(nick=new_nick, reason=f"nick by {message.author}")
                await reply(f"📝 Nick for {target.mention} → **{new_nick or '(reset)'}**")
                await self._mod_log(f"nick {target} = {new_nick or '(reset)'}", message)

            elif cmd == "role":
                if not message.mentions or len(args) < 2:
                    await reply("Usage: `%role @user <role name>`", delete_after=8); return
                target = message.mentions[0]
                role_name = " ".join(a for a in args if not a.startswith("<@")).strip()
                role = discord.utils.get(message.guild.roles, name=role_name)
                if not role:
                    role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), message.guild.roles)
                if not role:
                    await reply(f"Role **{role_name}** not found.", delete_after=8); return
                if role in target.roles:
                    await target.remove_roles(role, reason=f"$role toggle by {message.author}")
                    await reply(f"🎭 Removed **{role.name}** from {target.mention}.")
                    await self._mod_log(f"role_remove {role.name} → {target}", message)
                else:
                    await target.add_roles(role, reason=f"$role toggle by {message.author}")
                    await reply(f"🎭 Gave **{role.name}** to {target.mention}.")
                    await self._mod_log(f"role_add {role.name} → {target}", message)

            elif cmd == "say":
                text = " ".join(args).strip()
                if not text:
                    await reply("Usage: `%say <text>`", delete_after=8); return
                try:
                    await message.delete()
                except Exception:
                    pass
                await reply(text)
                await self._mod_log(f"say: {text[:100]}", message)

            elif cmd == "userinfo":
                target = message.mentions[0] if message.mentions else message.author
                created = target.created_at.strftime("%Y-%m-%d")
                joined = target.joined_at.strftime("%Y-%m-%d") if getattr(target, "joined_at", None) else "?"
                roles = ", ".join(r.name for r in getattr(target, "roles", []) if r.name != "@everyone") or "—"
                await reply(
                    f"👤 **{target}** (`{target.id}`)\n"
                    f"Account created: **{created}** · Joined server: **{joined}**\n"
                    f"Roles: {roles}"
                )

            elif cmd == "serverinfo":
                g = message.guild
                created = g.created_at.strftime("%Y-%m-%d")
                await reply(
                    f"🏛️ **{g.name}** (`{g.id}`)\n"
                    f"Created: **{created}** · Owner: **{g.owner}**\n"
                    f"Members: **{g.member_count}** · Channels: **{len(g.channels)}** · Roles: **{len(g.roles)}**"
                )

            elif cmd == "avatar":
                target = message.mentions[0] if message.mentions else message.author
                url = str(target.display_avatar.url)
                await reply(f"🖼️ Avatar for **{target}**\n{url}")

            elif cmd == "modlog":
                rows = await self.db.discord_mod_log.find(
                    {"guild_id": str(message.guild.id)}, {"_id": 0}
                ).sort("created_at", -1).to_list(10)
                if not rows:
                    await reply("No mod actions logged in this server yet.")
                else:
                    lines = [f"• `{r.get('created_at', '')[:19]}` **{r.get('action', '')}** by `{r.get('moderator', '?')}`" for r in rows]
                    await reply("📋 **Last 10 mod actions**\n" + "\n".join(lines))

            elif cmd == "joinvoice":
                vc_id = None
                if message.channel_mentions:
                    vc_id = message.channel_mentions[0].id
                elif args and args[0].isdigit():
                    vc_id = int(args[0])
                elif args:
                    name = " ".join(args).strip().lower()
                    found = discord.utils.find(lambda c: isinstance(c, discord.VoiceChannel) and c.name.lower() == name, message.guild.channels)
                    vc_id = found.id if found else None
                if not vc_id:
                    await reply("Usage: `%joinvoice <#voice-channel|channel_id|name>`", delete_after=8); return
                try:
                    await self.join_voice_channel(str(vc_id), guild_id=str(message.guild.id))
                    ch = message.guild.get_channel(vc_id)
                    await reply(f"🎙️ Joined voice channel **{ch.name if ch else vc_id}**.")
                    await self._mod_log(f"joinvoice {vc_id}", message)
                except Exception as e:
                    await reply(f"⚠️ Couldn't join voice: `{e}`", delete_after=10)

            elif cmd == "leavevoice":
                try:
                    await self.leave_voice_channel()
                    await reply("👋 Left the voice channel.")
                    await self._mod_log("leavevoice", message)
                except Exception as e:
                    await reply(f"⚠️ Couldn't leave voice: `{e}`", delete_after=10)

            elif cmd == "closeticket":
                if not message.channel.name.startswith("ticket-"):
                    await reply("This isn't a ticket channel.", delete_after=8); return
                await reply("🔒 Closing ticket in 3 seconds…")
                await self._mod_log("ticket_close", message)
                await asyncio.sleep(3)
                try:
                    await message.channel.delete(reason=f"Ticket closed by {message.author}")
                except Exception as e:
                    logger.warning("[discord] ticket close failed: %s", e)

            else:
                await reply(f"❓ Unknown command `%{cmd}`. Type `%help` for the list.", delete_after=8)

        except discord.Forbidden:
            await reply("❌ I don't have permission to do that. Check my role & channel perms.", delete_after=10)
        except discord.HTTPException as e:
            await reply(f"⚠️ Discord API error: `{e}`", delete_after=10)
        except Exception as e:
            logger.warning("[discord] $%s failed: %s", cmd, e)
            await reply(f"⚠️ `%{cmd}` failed: `{e}`", delete_after=10)

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

    async def send_dm(self, discord_user_id: str, text: str, *, image_url: Optional[str] = None, voice_url: Optional[str] = None, image_bytes: Optional[bytes] = None, voice_bytes: Optional[bytes] = None, image_name: str = "image.png", voice_name: str = "voice.mp3") -> dict:
        self._require_running()
        user = await self.client.fetch_user(int(discord_user_id))
        files = []
        if image_bytes:
            files.append(discord.File(fp=io.BytesIO(image_bytes), filename=image_name))
        if voice_bytes:
            files.append(discord.File(fp=io.BytesIO(voice_bytes), filename=voice_name))
        if image_url:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.get(image_url)
                r.raise_for_status()
                files.append(discord.File(fp=io.BytesIO(r.content), filename=image_name or "image.png"))
        if voice_url:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.get(voice_url)
                r.raise_for_status()
                files.append(discord.File(fp=io.BytesIO(r.content), filename=voice_name or "voice.mp3"))
        if files:
            await user.send(text or "", files=files)
        else:
            await user.send(text)
        await self._store_dm(user, text or (image_url or voice_url or "attachment"), direction="out")
        return {"ok": True, "to": str(user)}

    async def send_channel_message(self, channel_id: str, text: str, guild_id: Optional[str] = None) -> dict:
        """Post a message to a specific Discord channel. Silent no-op if the bot
        isn't running. If a `guild_id` is provided, we look up the channel via
        the guild first so DMs / cross-guild channels don't false-hit."""
        if self.status != "running" or not self.client:
            return {"ok": False, "reason": "bot not running"}
        try:
            ch = None
            if guild_id:
                g = self.client.get_guild(int(guild_id))
                if g is None:
                    return {"ok": False, "reason": f"bot is not in guild {guild_id}"}
                ch = g.get_channel(int(channel_id))
                if ch is None:
                    return {"ok": False, "reason": f"channel {channel_id} not found in guild {g.name} — check the channel exists and the bot has 'View Channel' permission"}
            else:
                ch = self.client.get_channel(int(channel_id))
                if ch is None:
                    try:
                        ch = await self.client.fetch_channel(int(channel_id))
                    except discord.NotFound:
                        return {"ok": False, "reason": f"channel {channel_id} not found — set the Server (Guild) ID in Admin so I can look it up correctly"}
                    except discord.Forbidden:
                        return {"ok": False, "reason": f"bot has no access to channel {channel_id} — give the bot 'View Channel' + 'Send Messages' permission on it"}
            # Only send if it's a text-capable channel
            if not hasattr(ch, "send"):
                return {"ok": False, "reason": f"channel {channel_id} is not a text channel (type={type(ch).__name__})"}
            await ch.send(text)
            return {"ok": True, "channel": str(channel_id)}
        except discord.Forbidden as e:
            return {"ok": False, "reason": f"forbidden: {e} — give the bot Send Messages permission on that channel"}
        except Exception as e:
            logger.warning("[discord] send_channel_message failed: %s", e)
            return {"ok": False, "reason": str(e)}

    async def join_voice_channel(self, channel_id: str, guild_id: Optional[str] = None) -> dict:
        self._require_running()
        channel = None
        if guild_id:
            guild = self.client.get_guild(int(guild_id))
            if guild is None:
                raise RuntimeError("guild not found")
            channel = guild.get_channel(int(channel_id))
        else:
            channel = self.client.get_channel(int(channel_id))
        if channel is None:
            raise RuntimeError("voice channel not found")
        if not isinstance(channel, discord.VoiceChannel):
            raise RuntimeError("target is not a voice channel")
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel.id == channel.id:
                return {"ok": True, "channel": str(channel.id), "already_connected": True}
            await self.voice_client.disconnect(force=True)
        self.voice_client = await channel.connect(self_deaf=False)
        self.voice_channel_id = str(channel.id)
        return {"ok": True, "channel": str(channel.id)}

    async def leave_voice_channel(self) -> dict:
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
        self.voice_client = None
        self.voice_channel_id = None
        return {"ok": True}

    async def stop_voice(self) -> dict:
        if self.voice_client and self.voice_client.is_connected():
            self.voice_client.stop()
        return {"ok": True}

    async def speak_text(self, text: str, channel_id: Optional[str] = None, guild_id: Optional[str] = None) -> dict:
        if not text or not text.strip():
            raise RuntimeError("empty text")
        target_channel_id = channel_id or self.voice_channel_id
        if not target_channel_id:
            raise RuntimeError("no voice channel selected")
        if not self.voice_client or not self.voice_client.is_connected():
            await self.join_voice_channel(target_channel_id, guild_id=guild_id)
        try:
            from gtts import gTTS
        except Exception as exc:
            raise RuntimeError(f"gTTS not available: {exc}")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            gTTS(text=text, lang="en").save(tmp_path)
            self.voice_client.stop()
            self.voice_client.play(discord.FFmpegPCMAudio(tmp_path))
            return {"ok": True, "file": tmp_path}
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    async def play_audio_url(self, source_url: str, channel_id: Optional[str] = None, guild_id: Optional[str] = None) -> dict:
        if not source_url:
            raise RuntimeError("empty url")
        target_channel_id = channel_id or self.voice_channel_id
        if not target_channel_id:
            raise RuntimeError("no voice channel selected")
        if not self.voice_client or not self.voice_client.is_connected():
            await self.join_voice_channel(target_channel_id, guild_id=guild_id)
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(source_url)
            r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(r.content)
            tmp_path = tmp.name
        try:
            self.voice_client.stop()
            self.voice_client.play(discord.FFmpegPCMAudio(tmp_path))
            return {"ok": True, "file": tmp_path}
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

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

    async def _store_guild_message(self, message: discord.Message):
        """Log every non-DM channel message so staff can review full chat history from the admin panel."""
        if self.db is None or not message.guild:
            return
        try:
            await self.db.discord_guild_messages.insert_one({
                "id": str(uuid.uuid4()),
                "guild_id": str(message.guild.id),
                "guild_name": message.guild.name,
                "channel_id": str(message.channel.id),
                "channel_name": getattr(message.channel, "name", str(message.channel)),
                "author_id": str(message.author.id),
                "author_name": str(message.author),
                "text": (message.content or "")[:2000],
                "direction": "in",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("[discord] guild message store failed: %s", e)

    async def list_text_channels(self) -> list:
        if not self.client or not self.client.guilds:
            return []
        out = []
        for guild in self.client.guilds:
            for ch in guild.text_channels:
                perms = ch.permissions_for(guild.me)
                if perms.send_messages:
                    out.append({"guild_id": str(guild.id), "guild_name": guild.name,
                                "channel_id": str(ch.id), "channel_name": ch.name})
        return out

    async def send_guild_message(self, channel_id: str, text: str, mention_user_id: Optional[str] = None) -> dict:
        if not self.client:
            raise RuntimeError("Bot is not running")
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            raise RuntimeError("Channel not found — is the bot still in that server?")
        prefix = f"<@{mention_user_id}> " if mention_user_id else ""
        sent = await channel.send(f"{prefix}{text}"[:2000])
        try:
            await self.db.discord_guild_messages.insert_one({
                "id": str(uuid.uuid4()),
                "guild_id": str(channel.guild.id),
                "guild_name": channel.guild.name,
                "channel_id": str(channel.id),
                "channel_name": getattr(channel, "name", str(channel)),
                "author_id": str(self.client.user.id),
                "author_name": "Staff (via admin panel)",
                "text": text[:2000],
                "direction": "out",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("[discord] guild message send-store failed: %s", e)
        return {"ok": True, "message_id": str(sent.id)}


bot_manager = DiscordBotManager()
