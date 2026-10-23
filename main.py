import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import re
import io
import json
import asyncio
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN bulunamadı! .env dosyasını kontrol et.")

# ============================================================
# AYARLAR
# ============================================================
API_BASE_URL = "https://solidarksystems.alwaysdata.net"
REQUEST_TIMEOUT = 40

ROLE_PREMIUM_MANAGER = 1561266508750135376   # /premium-ver yetkisi
ROLE_NORMAL_USER     = 1561266654422376519   # normal kullanıcı rolü
LOG_CHANNEL_ID       = 1563238579155509388   # log kanalı

NORMAL_DAILY_LIMIT   = 3      # normal kullanıcı günde kaç sorgu
NORMAL_LINE_LIMIT    = 500    # normal kullanıcı kaç satır alır
PREMIUM_LINE_LIMIT   = 0      # 0 = sınırsız
COOLDOWN_SECONDS     = 10     # sorgular arası bekleme

DATA_FILE = "data.json"
TZ = timezone(timedelta(hours=3))  # Türkiye saati

# ============================================================
# JSON VERİ YÖNETİMİ (veritabanı yerine)
# ============================================================
def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"premium_users": [], "daily_usage": {}, "last_use": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"premium_users": [], "daily_usage": {}, "last_use": {}}


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_premium(user_id: int) -> bool:
    data = load_data()
    return str(user_id) in data["premium_users"]


def today_key() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def get_daily_usage(user_id: int) -> int:
    data = load_data()
    return data["daily_usage"].get(str(user_id), {}).get(today_key(), 0)


def increment_daily_usage(user_id: int):
    data = load_data()
    uid = str(user_id)
    today = today_key()
    if uid not in data["daily_usage"]:
        data["daily_usage"][uid] = {}
    # eski günleri temizle
    data["daily_usage"][uid] = {today: data["daily_usage"][uid].get(today, 0) + 1}
    save_data(data)


def get_last_use(user_id: int) -> float:
    data = load_data()
    return data["last_use"].get(str(user_id), 0)


def set_last_use(user_id: int):
    import time
    data = load_data()
    data["last_use"][str(user_id)] = time.time()
    save_data(data)


# ============================================================
# YARDIMCI
# ============================================================
def is_valid_url(url: str) -> bool:
    pattern = r'^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$'
    return bool(re.match(pattern, url.strip()))


def now_str() -> str:
    return datetime.now(TZ).strftime("%Y %d %B saat: %H:%M:%S")


def has_role(member: discord.Member, role_id: int) -> bool:
    return any(r.id == role_id for r in member.roles)


# ============================================================
# BOT
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash komutlar senkronize edildi.")

    async def on_ready(self):
        print(f"✅ {self.user} olarak giriş yapıldı.")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="/log | BY DARKCC"
            )
        )


bot = MyBot()


# ============================================================
# 📝 LOG GÖNDERİMİ (log kanalına)
# ============================================================
async def send_log_to_channel(
    interaction: discord.Interaction,
    domain: str,
    premium: bool,
    success: bool,
    extra: str = ""
):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        return

    embed = discord.Embed(
        title="📥 Yeni Log Sorgusu",
        color=discord.Color.green() if success else discord.Color.red(),
        timestamp=datetime.now(TZ)
    )
    embed.add_field(name="👤 Kullanıcı", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
    embed.add_field(name="👑 Premium", value="✅ **Var**" if premium else "❌ **Yok**", inline=True)
    embed.add_field(name="🌐 Domain", value=f"`{domain}`", inline=True)
    embed.add_field(name="🕐 Zaman", value=now_str(), inline=False)
    if extra:
        embed.add_field(name="ℹ️ Bilgi", value=extra[:1000], inline=False)
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text="BY DARKCC | Log Sistemi")

    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[LOG KANAL HATASI] {e}")


# ============================================================
# 🔍 /log
# ============================================================
@bot.tree.command(name="log", description="Belirtilen domain için log checker çalıştırır.")
@app_commands.describe(url="Log checklenecek domain (örn: exxen.com)")
async def log_command(interaction: discord.Interaction, url: str):
    url = url.strip().lower()

    # --- Yetki kontrolü: normal rol VEYA premium ---
    member = interaction.user
    if not isinstance(member, discord.Member):
        return await interaction.response.send_message(
            "❌ Bu komut sadece sunucuda kullanılabilir.", ephemeral=True
        )

    premium = is_premium(interaction.user.id)
    is_normal_role = has_role(member, ROLE_NORMAL_USER)

    if not premium and not is_normal_role:
        return await interaction.response.send_message(
            "🚫 **Bu komutu kullanma yetkin yok.**\n"
            f"Gerekli roller: <@&{ROLE_NORMAL_USER}> veya Premium üyelik.",
            ephemeral=True
        )

    # --- URL kontrol ---
    if not is_valid_url(url):
        return await interaction.response.send_message(
            "❌ **Geçersiz domain!**\nÖrnek: `/log url:exxen.com`",
            ephemeral=True
        )

    # --- Cooldown ---
    import time
    remaining = COOLDOWN_SECONDS - (time.time() - get_last_use(interaction.user.id))
    if remaining > 0:
        return await interaction.response.send_message(
            f"⏳ **Çok hızlısın!** Kalan: **{remaining:.1f} sn**",
            ephemeral=True
        )

    # --- Günlük limit (sadece normal kullanıcı) ---
    if not premium:
        used = get_daily_usage(interaction.user.id)
        if used >= NORMAL_DAILY_LIMIT:
            await send_log_to_channel(
                interaction, url, premium=False, success=False,
                extra=f"Günlük limit aşıldı ({used}/{NORMAL_DAILY_LIMIT})"
            )
            return await interaction.response.send_message(
                f"🚫 **Günlük limit aşıldı!**\n"
                f"Normal kullanıcılar günde **{NORMAL_DAILY_LIMIT}** sorgu yapabilir.\n"
                f"Kalan: **0/{NORMAL_DAILY_LIMIT}**",
                ephemeral=True
            )

    # --- Bekleme göster ---
    wait_time = 2 if premium else 10
    await interaction.response.defer(ephemeral=True)

    if not premium:
        increment_daily_usage(interaction.user.id)
    set_last_use(interaction.user.id)

    # --- 2sn (premium) / 10sn (normal) bekle ---
    await asyncio.sleep(wait_time)

    # --- API isteği ---
    target = f"{API_BASE_URL}/log.php?url={url}"
    try:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(target) as resp:

                if resp.status == 200:
                    text = await resp.text()

                    # --- Satır limiti uygula ---
                    lines = text.splitlines()
                    total_lines = len(lines)
                    line_limit = PREMIUM_LINE_LIMIT if premium else NORMAL_LINE_LIMIT

                    if line_limit > 0 and total_lines > line_limit:
                        truncated = "\n".join(lines[:line_limit])
                        info_msg = (
                            f"⚠️ Toplam **{total_lines}** satır bulundu. "
                            f"Normal kullanıcı limiti **{line_limit}** satır — "
                            f"ilk **{line_limit}** satır gösteriliyor."
                        )
                    else:
                        truncated = text
                        info_msg = f"✅ **{total_lines}** satır log çekildi."

                    final_text = f"BY DARKCC\n\n{truncated}"

                    # --- Log kanalına gönder ---
                    await send_log_to_channel(
                        interaction, url, premium=premium, success=True,
                        extra=f"{total_lines} satır çekildi."
                    )

                    # --- Kullanıcıya DM ---
                    dm_embed = discord.Embed(
                        title=f"🔍 Log Sorgu Sonucu: {url}",
                        description=info_msg,
                        color=discord.Color.green(),
                        timestamp=datetime.now(TZ)
                    )
                    dm_embed.add_field(name="🌐 Domain", value=f"`{url}`", inline=True)
                    dm_embed.add_field(name="📊 Toplam Satır", value=f"`{total_lines}`", inline=True)
                    dm_embed.add_field(
                        name="👑 Premium",
                        value="✅ Var" if premium else f"❌ Yok ({get_daily_usage(interaction.user.id)}/{NORMAL_DAILY_LIMIT})",
                        inline=True
                    )
                    dm_embed.set_footer(text="BY DARKCC")

                    try:
                        # Uzunsa dosya, kısaysa mesaj
                        if len(final_text) > 4000:
                            file = discord.File(
                                io.BytesIO(final_text.encode("utf-8")),
                                filename=f"log_{url.replace('.', '_')}.txt"
                            )
                            await interaction.user.send(embed=dm_embed, file=file)
                        else:
                            await interaction.user.send(embed=dm_embed)
                            await interaction.user.send(f"```\n{final_text[:1900]}\n```")

                        await interaction.followup.send(
                            "✅ **Sonuç DM'ne gönderildi!** 📩",
                            ephemeral=True
                        )

                    except discord.Forbidden:
                        # DM kapalıysa
                        fb = discord.Embed(
                            title=f"⚠️ DM Gönderilemedi: {url}",
                            description="DM kutun kapalı olduğu için sonuç buraya geliyor.\n"
                                        f"**İpucu:** Sunucu ayarlarından DM'lere izin ver.",
                            color=discord.Color.orange()
                        )
                        if len(final_text) > 4000:
                            file = discord.File(
                                io.BytesIO(final_text.encode("utf-8")),
                                filename=f"log_{url.replace('.', '_')}.txt"
                            )
                            await interaction.followup.send(embed=fb, file=file, ephemeral=True)
                        else:
                            await interaction.followup.send(
                                embed=fb,
                                content=f"```\n{final_text[:1900]}\n```",
                                ephemeral=True
                            )

                elif resp.status == 503:
                    await send_log_to_channel(interaction, url, premium, False, "API 503")
                    await interaction.followup.send(
                        "⚠️ **API geçici olarak ulaşılamıyor (503).** Tekrar dene.",
                        ephemeral=True
                    )
                else:
                    await send_log_to_channel(interaction, url, premium, False, f"HTTP {resp.status}")
                    await interaction.followup.send(
                        f"❌ **Hata:** HTTP `{resp.status}`", ephemeral=True
                    )

    except asyncio.TimeoutError:
        await send_log_to_channel(interaction, url, premium, False, "Zaman aşımı")
        await interaction.followup.send(
            "⏰ **Zaman aşımı!** API 40 saniye içinde cevap vermedi.", ephemeral=True
        )
    except aiohttp.ClientConnectorError:
        await send_log_to_channel(interaction, url, premium, False, "Bağlantı hatası")
        await interaction.followup.send(
            "🌐 **Bağlantı hatası!** API sunucusuna ulaşılamıyor.", ephemeral=True
        )
    except Exception as e:
        await send_log_to_channel(interaction, url, premium, False, f"Hata: {str(e)[:100]}")
        await interaction.followup.send(
            f"❌ **Beklenmeyen hata:**\n```\n{str(e)[:500]}\n```", ephemeral=True
        )


# ============================================================
# 👑 /premium-ver  (Sadece yetkili rol)
# ============================================================
@bot.tree.command(name="premium-ver", description="[YETKİLİ] Bir kullanıcıya premium verir.")
@app_commands.describe(kullanici="Premium verilecek kullanıcı")
async def premium_ver(interaction: discord.Interaction, kullanici: discord.User):
    if not isinstance(interaction.user, discord.Member) or \
       not has_role(interaction.user, ROLE_PREMIUM_MANAGER):
        return await interaction.response.send_message(
            f"🚫 **Yetkin yok!**\nSadece <@&{ROLE_PREMIUM_MANAGER}> rolüne sahipler kullanabilir.",
            ephemeral=True
        )

    data = load_data()
    if str(kullanici.id) in data["premium_users"]:
        return await interaction.response.send_message(
            f"ℹ️ **{kullanici.mention}** zaten premium.", ephemeral=True
        )

    data["premium_users"].append(str(kullanici.id))
    save_data(data)

    # Log kanalına bilgi
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        e = discord.Embed(
            title="👑 Premium Verildi",
            color=discord.Color.gold(),
            timestamp=datetime.now(TZ)
        )
        e.add_field(name="Kullanıcı", value=f"{kullanici.mention}\n`{kullanici}`", inline=False)
        e.add_field(name="Yetkili", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
        e.add_field(name="Zaman", value=now_str(), inline=False)
        e.set_footer(text="BY DARKCC | Premium Sistemi")
        try:
            await channel.send(embed=e)
        except Exception:
            pass

    await interaction.response.send_message(
        f"✅ **{kullanici.mention}** artık **Premium**!\n"
        f"Artık **sınırsız** sorgu ve **500+ satır** log çekebilir.",
        ephemeral=False
    )


# ============================================================
# 🚫 /premium-al  (Sadece yetkili rol)
# ============================================================
@bot.tree.command(name="premium-al", description="[YETKİLİ] Bir kullanıcının premiumunu kaldırır.")
@app_commands.describe(kullanici="Premiumu kaldırılacak kullanıcı")
async def premium_al(interaction: discord.Interaction, kullanici: discord.User):
    if not isinstance(interaction.user, discord.Member) or \
       not has_role(interaction.user, ROLE_PREMIUM_MANAGER):
        return await interaction.response.send_message(
            f"🚫 **Yetkin yok!**\nSadece <@&{ROLE_PREMIUM_MANAGER}> rolüne sahipler kullanabilir.",
            ephemeral=True
        )

    data = load_data()
    if str(kullanici.id) not in data["premium_users"]:
        return await interaction.response.send_message(
            f"ℹ️ **{kullanici.mention}** zaten premium değil.", ephemeral=True
        )

    data["premium_users"].remove(str(kullanici.id))
    save_data(data)

    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        e = discord.Embed(
            title="🚫 Premium Kaldırıldı",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(TZ)
        )
        e.add_field(name="Kullanıcı", value=f"{kullanici.mention}\n`{kullanici}`", inline=False)
        e.add_field(name="Yetkili", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
        e.add_field(name="Zaman", value=now_str(), inline=False)
        e.set_footer(text="BY DARKCC | Premium Sistemi")
        try:
            await channel.send(embed=e)
        except Exception:
            pass

    await interaction.response.send_message(
        f"✅ **{kullanici.mention}** kullanıcısının premiumu kaldırıldı.",
        ephemeral=False
    )


# ============================================================
# 👑 /premium-liste  (Sadece yetkili rol)
# ============================================================
@bot.tree.command(name="premium-liste", description="[YETKİLİ] Premium kullanıcıları listeler.")
async def premium_liste(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or \
       not has_role(interaction.user, ROLE_PREMIUM_MANAGER):
        return await interaction.response.send_message(
            f"🚫 **Yetkin yok!**", ephemeral=True
        )

    data = load_data()
    users = data["premium_users"]

    if not users:
        return await interaction.response.send_message(
            "ℹ️ **Hiç premium kullanıcı yok.**", ephemeral=True
        )

    e = discord.Embed(
        title=f"👑 Premium Kullanıcılar ({len(users)})",
        color=discord.Color.gold(),
        timestamp=datetime.now(TZ)
    )
    liste = "\n".join([f"<@{uid}> (`{uid}`)" for uid in users[:30]])
    if len(users) > 30:
        liste += f"\n... ve **{len(users)-30}** kişi daha"
    e.description = liste
    e.set_footer(text="BY DARKCC | Premium Sistemi")
    await interaction.response.send_message(embed=e, ephemeral=True)


# ============================================================
# 🚀 BAŞLAT
# ============================================================
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Hatalı Bot Token!")
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
