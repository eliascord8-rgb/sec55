"""Better Social Discord Bot
Run on VPS as a systemd service. Requires env vars:
  BS_BACKEND_URL          e.g. https://better-social.pro
  BS_DISCORD_TOKEN        the bot token from Discord developer portal
  BS_BOT_SHARED_SECRET    the same secret configured in Admin → Discord
  BS_DEVELOPER_ROLE       role name (default: "Developer")
"""
import os
import logging
import discord
from discord import app_commands
import httpx
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bs-bot")

BACKEND_URL = os.environ.get("BS_BACKEND_URL", "https://better-social.pro").rstrip("/")
TOKEN = os.environ["BS_DISCORD_TOKEN"]
SHARED_SECRET = os.environ["BS_BOT_SHARED_SECRET"]
DEV_ROLE = os.environ.get("BS_DEVELOPER_ROLE", "Developer")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    try:
        synced = await tree.sync()
        log.info(f"Logged in as {client.user} · synced {len(synced)} commands")
    except Exception as e:
        log.error(f"Command sync failed: {e}")


SERVICE_CHOICES = [
    app_commands.Choice(name="TikTok Live Likes", value="likes"),
    app_commands.Choice(name="TikTok Live Views", value="views"),
    app_commands.Choice(name="TikTok Live Comments", value="comments"),
]


@tree.command(name="buy", description="Place an order via Better Social")
@app_commands.describe(
    service="What to order",
    quantity="How many (e.g. 1000)",
    link="TikTok link or @username",
    coupon="Coupon code (required unless you have the Developer role)",
)
@app_commands.choices(service=SERVICE_CHOICES)
async def buy(
    interaction: discord.Interaction,
    service: app_commands.Choice[str],
    quantity: int,
    link: str,
    coupon: Optional[str] = None,
):
    await interaction.response.defer(thinking=True, ephemeral=True)

    # Role check
    is_developer = False
    if isinstance(interaction.user, discord.Member):
        is_developer = any(r.name == DEV_ROLE for r in interaction.user.roles)

    if not is_developer and not coupon:
        await interaction.followup.send(
            f"❌ You need a coupon to place orders. (Developers with the `{DEV_ROLE}` role can order without one.)",
            ephemeral=True,
        )
        return

    body = {
        "service_type": service.value,
        "link": link,
        "quantity": quantity,
        "coupon_code": coupon,
        "is_developer": is_developer,
        "discord_user_id": str(interaction.user.id),
        "discord_username": str(interaction.user),
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as c:
            r = await c.post(
                f"{BACKEND_URL}/api/discord/order",
                json=body,
                headers={"X-Bot-Secret": SHARED_SECRET},
            )
            data = r.json()
    except Exception as e:
        log.exception("backend error")
        await interaction.followup.send(f"⚠️ Backend error: {e}", ephemeral=True)
        return

    if r.status_code == 200 and data.get("status") == "completed":
        badge = "🛠 Developer" if is_developer else "🎟 Coupon"
        embed = discord.Embed(
            title="✅ Order placed",
            description=f"**{data.get('service')}**\nLink: `{link}`\nQty: **{quantity:,}**",
            color=0xFF007F,
        )
        embed.add_field(name="SMM Order ID", value=f"`{data.get('smm_order_id')}`", inline=True)
        embed.add_field(name="Charged", value=f"${data.get('price', 0):.2f}", inline=True)
        embed.add_field(name="Billed via", value=badge, inline=True)
        embed.set_footer(text=f"Placed by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=False)
    else:
        detail = data.get("detail", "Unknown error")
        await interaction.followup.send(f"❌ Order failed: **{detail}**", ephemeral=True)


@tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 pong", ephemeral=True)


if __name__ == "__main__":
    client.run(TOKEN)
