import discord
from discord.ext import commands
import aiohttp
import os
import io

# BURAYA BOT TOKENINI YAZ
TOKEN = 'BURAYA_DISCORD_BOT_TOKENINI_YAZ'

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents)

# Senin API adresin
API_BASE_URL = "https://solidarksystems.alwaysdata.net"

@bot.event
async def on_ready():
    print(f'{bot.user} olarak giriş yapıldı.')
    print(f'Bot Sunucusu: {bot.user.name}')

@bot.command(name='log')
async def log_command(ctx, url: str):
    """
    Kullanım: /log exxen.com
    Belirtilen URL için log çekme işlemi yapar.
    """
    await ctx.defer()  # İşlem uzun sürerse bekleme göstergesi çıkarır

    # API URL'sini oluşturuyoruz
    target_url = f"{API_BASE_URL}/log.php?url={url}"
    
    try:
        async with aiohttp.ClientSession() as session:
            # İsteği atıyoruz
            async with session.get(target_url) as response:
                if response.status == 200:
                    text = await response.text()
                    
                    # Gelen içeriğin başına BY DARKCC ekliyoruz
                    final_result = f"BY DARKCC\n\n{text}"

                    # Discord mesaj sınırı 2000 karakterdir.
                    if len(final_result) > 1900:
                        # Dosyayı diske yazmak yerine bellekte (in-memory) oluşturup gönderiyoruz
                        file_data = io.BytesIO(final_result.encode('utf-8'))
                        file_name = f"log_{url.replace('.', '_')}.txt"
                        
                        embed = discord.Embed(
                            title=f"🔍 Log Sorgu Sonucu: {url}",
                            description="Sonuçlar mesaj sınırını aştığı için dosya olarak eklendi.",
                            color=discord.Color.red()
                        )
                        embed.set_footer(text="BY DARKCC")
                        
                        await ctx.send(embed=embed, file=discord.File(file_data, filename=file_name))
                    else:
                        # Kısa içerikse doğrudan mesaj olarak gönder
                        embed = discord.Embed(
                            title=f"🔍 Log Sorgu Sonucu: {url}",
                            description=f"```\n{final_result}\n```", 
                            color=discord.Color.red()
                        )
                        embed.set_footer(text="BY DARKCC")
                        await ctx.send(embed=embed)
                        
                elif response.status == 503:
                    await ctx.send("⚠️ API geçici olarak ulaşılamıyor (503 Service Unavailable). Lütfen tekrar deneyin.")
                else:
                    await ctx.send(f"❌ Hata oluştu: HTTP {response.status}")

    except Exception as e:
        await ctx.send(f"❌ Bir hata oluştu: `{str(e)}`")

# Botu başlat
try:
    bot.run(TOKEN)
except discord.LoginFailure:
    print("Hatalı Bot Token! Lütfen TOKEN değişkenini kontrol edin.")
except Exception as e:
    print(f"Beklenmeyen hata: {e}")
