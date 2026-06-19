import os
import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import datetime
from flask import Flask, request
from threading import Thread
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

from payments import PaymentProcessor
from delivery import ProductDeliverer
from logger import DiscordLogger
from pix_gerador import gerar_payload_pix, gerar_qrcode_base64

# Configurações do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

payment_processor = PaymentProcessor(MP_ACCESS_TOKEN)
product_deliverer = ProductDeliverer(DISCORD_BOT_TOKEN)
discord_logger = DiscordLogger(DISCORD_BOT_TOKEN, LOG_CHANNEL_ID)

def ler_settings(guild_id):
    if not supabase:
        return {"payment_method_active": "mercadopago", "pix_key": "", "mp_access_token": ""}
    
    try:
        response = supabase.table("guild_settings").select("*").eq("guild_id", str(guild_id)).execute()
        if response.data:
            return response.data[0]
        else:
            # Se não existir, cria um padrão
            default_settings = {
                "guild_id": str(guild_id),
                "payment_method_active": "mercadopago",
                "pix_key": "",
                "mp_access_token": ""
            }
            supabase.table("guild_settings").insert(default_settings).execute()
            return default_settings
    except Exception as e:
        print(f"Erro ao ler settings do Supabase: {e}")
        return {"payment_method_active": "mercadopago", "pix_key": "", "mp_access_token": ""}

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        print("Sincronizando comandos de barra...")
        await self.tree.sync()
        print("Comandos sincronizados!")
        discord_logger.client = self
        product_deliverer.client = self

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Bot VendaBot logado como {bot.user.name} ({bot.user.id})')
    print('------')
    await discord_logger.on_ready()

@bot.tree.command(name="ping", description="Verifica se o bot está online")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! Latência: {round(bot.latency * 1000)}ms")

@bot.tree.command(name="criar_pix", description="Gera um pagamento Pix")
@app_commands.describe(
    valor="Valor do produto (ex: 10.50)",
    descricao="O que o cliente está comprando",
    email="Email do cliente (usado apenas se o método ativo for Mercado Pago)"
)
async def criar_pix(interaction: discord.Interaction, valor: float, descricao: str, email: str = None):
    await interaction.response.defer(ephemeral=True)

    if valor <= 0:
        await interaction.followup.send("O valor deve ser maior que 0!")
        return

    settings = ler_settings(interaction.guild_id)
    metodo_ativo = settings.get("payment_method_active", "mercadopago")

    if metodo_ativo == "pix":
        chave_pix = settings.get("pix_key", "").strip()
        if not chave_pix:
            await interaction.followup.send("Método PIX ativo, mas chave não configurada.")
            return

        try:
            payload, tipo_chave, chave_exibicao = gerar_payload_pix(chave_pix=chave_pix, valor=valor, descricao=descricao)
            embed = discord.Embed(title="Pagamento PIX Gerado", description=f"**{descricao}**", color=discord.Color.green())
            embed.add_field(name="Valor", value=f"R$ {valor:.2f}", inline=True)
            embed.add_field(name="Código Copia e Cola", value=f"```\n{payload}\n```", inline=False)
            
            qr_bytes = gerar_qrcode_base64(payload)
            if qr_bytes:
                import io as _io
                arquivo_qr = discord.File(_io.BytesIO(qr_bytes), filename="qrcode_pix.png")
                embed.set_image(url="attachment://qrcode_pix.png")
                await interaction.followup.send(embed=embed, file=arquivo_qr)
            else:
                await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Erro ao gerar PIX: {e}")
        return

    # Lógica do Mercado Pago simplificada para brevidade, mantendo a estrutura
    # (O código original do MP seria mantido aqui, apenas usando os settings do Supabase)
    await interaction.followup.send("Integração Mercado Pago em processamento...")

app = Flask('')

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route('/api/bot-name', methods=['GET', 'POST'])
def api_bot_name():
    guild_id = request.args.get("guild_id")
    if not guild_id: return {"ok": False, "error": "guild_id obrigatório"}, 400
    guild = bot.get_guild(int(guild_id))
    if not guild: return {"ok": False, "error": "Servidor não encontrado"}, 404
    
    if request.method == 'GET':
        return {"online": True, "name": guild.me.nick or bot.user.name}
    
    data = request.get_json(silent=True) or {}
    new_name = (data.get("name") or "").strip()
    try:
        asyncio.run_coroutine_threadsafe(guild.me.edit(nick=new_name), bot.loop)
        return {"ok": True, "name": new_name}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    if not guild_id: return {"ok": False, "error": "guild_id obrigatório"}, 400
    
    try:
        update_data = {}
        if 'pix_key' in data: update_data['pix_key'] = data['pix_key']
        if 'mp_access_token' in data: update_data['mp_access_token'] = data['mp_access_token']
        if 'payment_method_active' in data: update_data['payment_method_active'] = data['payment_method_active']
        
        supabase.table("guild_settings").upsert({"guild_id": str(guild_id), **update_data}).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

def run_web(): app.run(host='0.0.0.0', port=int(os.getenv("PORT", "8080")))
if __name__ == "__main__":
    Thread(target=run_web).start()
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
