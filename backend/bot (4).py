import os
import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import datetime
import json
from flask import Flask, request, jsonify
from threading import Thread
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Configurações do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase conectado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao conectar no Supabase: {e}")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
LOG_CHANNEL_ID_ENV = os.getenv("LOG_CHANNEL_ID", "0")
LOG_CHANNEL_ID = int(LOG_CHANNEL_ID_ENV) if LOG_CHANNEL_ID_ENV.isdigit() else 0

from payments import PaymentProcessor
from delivery import ProductDeliverer
from logger import DiscordLogger
from pix_gerador import gerar_payload_pix, gerar_qrcode_base64

payment_processor = PaymentProcessor(MP_ACCESS_TOKEN)
product_deliverer = ProductDeliverer(DISCORD_BOT_TOKEN)
discord_logger = DiscordLogger(DISCORD_BOT_TOKEN, LOG_CHANNEL_ID)

def ler_settings(guild_id):
    default_settings = {
        "guild_id": str(guild_id),
        "payment_method_active": "mercadopago",
        "pix_key": "",
        "mp_access_token": ""
    }
    
    if not supabase:
        print("⚠️ Supabase não configurado, usando settings padrão.")
        return default_settings
    
    try:
        response = supabase.table("guild_settings").select("*").eq("guild_id", str(guild_id)).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            print(f"ℹ️ Criando settings padrão para o servidor {guild_id}")
            supabase.table("guild_settings").insert(default_settings).execute()
            return default_settings
    except Exception as e:
        print(f"❌ Erro ao ler settings do Supabase: {e}")
        return default_settings

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        print("🔄 Sincronizando comandos de barra...")
        try:
            await self.tree.sync()
            print("✅ Comandos sincronizados!")
        except Exception as e:
            print(f"❌ Erro ao sincronizar comandos: {e}")
        
        discord_logger.client = self
        product_deliverer.client = self

bot = MyBot()

@bot.event
async def on_ready():
    print(f'🚀 Bot logado como {bot.user.name} ({bot.user.id})')
    print('------')
    try:
        await discord_logger.on_ready()
    except Exception as e:
        print(f"⚠️ Erro no logger.on_ready: {e}")

@bot.tree.command(name="ping", description="Verifica se o bot está online")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! Latência: {round(bot.latency * 1000)}ms")

# Servidor Flask
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, PATCH, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response

@app.route('/')
def home():
    return "VendaBot API Online! 🚀"

@app.route('/api/status')
def api_status():
    return jsonify({
        "online": bot.is_ready(),
        "bot_name": bot.user.name if bot.user else "Iniciando...",
        "supabase": supabase is not None
    })

@app.route('/api/server-info')
def api_server_info():
    if not bot.is_ready():
        if bot.user:
            return jsonify({"online": True, "servers": [], "message": "Bot logado, carregando servidores..."})
        return jsonify({"online": False, "servers": []})
    servers = []
    for guild in bot.guilds:
        servers.append({
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "icon": str(guild.icon.url) if guild.icon else None,
        })
    return jsonify({"online": True, "servers": servers})

@app.route('/api/channels')
def api_channels():
    guild_id = request.args.get("guild_id")
    if not bot.is_ready():
        return jsonify({"online": False, "channels": [], "error": "Bot ainda não está pronto"})
    
    guild = None
    if guild_id and guild_id != "undefined":
        guild = bot.get_guild(int(guild_id))
    
    if not guild and bot.guilds:
        guild = bot.guilds[0]
    
    if not guild:
        return jsonify({"online": True, "channels": [], "error": "Nenhum servidor encontrado"})
        
    channels = []
    for channel in guild.text_channels:
        channels.append({
            "id": str(channel.id),
            "name": channel.name,
            "category": channel.category.name if channel.category else None,
        })
    return jsonify({"online": True, "guild_name": guild.name, "channels": channels})

@app.route('/api/bot-name', methods=['GET', 'POST'])
def api_bot_name():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return jsonify({"ok": False, "error": "Servidor não encontrado"}), 404
    
    if request.method == 'GET':
        return jsonify({"online": True, "name": guild.me.nick or bot.user.name})
    
    data = request.get_json(silent=True) or {}
    new_name = (data.get("name") or "").strip()
    
    try:
        future = asyncio.run_coroutine_threadsafe(guild.me.edit(nick=new_name), bot.loop)
        future.result(timeout=10)
        return jsonify({"ok": True, "name": new_name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado no servidor"}), 500
    
    try:
        update_data = {}
        if 'pix_key' in data: update_data['pix_key'] = data['pix_key']
        if 'mp_access_token' in data: update_data['mp_access_token'] = data['mp_access_token']
        if 'payment_method_active' in data: update_data['payment_method_active'] = data['payment_method_active']
        
        supabase.table("guild_settings").upsert({"guild_id": str(guild_id), **update_data}).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/payment-method')
def api_payment_method():
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "active": "mercadopago"})
    try:
        response = supabase.table("guild_settings").select("payment_method_active").eq("guild_id", str(guild_id)).execute()
        if response.data and len(response.data) > 0:
            return jsonify({"ok": True, "active": response.data[0].get("payment_method_active", "mercadopago")})
        return jsonify({"ok": False, "active": "mercadopago"})
    except Exception as e:
        return jsonify({"ok": False, "active": "mercadopago", "error": str(e)})

def run_web():
    port = int(os.getenv("PORT", "8080"))
    print(f"🌐 Iniciando servidor web na porta {port}...")
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    
    if DISCORD_BOT_TOKEN:
        try:
            print("🤖 Iniciando Bot do Discord...")
            bot.run(DISCORD_BOT_TOKEN)
        except Exception as e:
            print(f"❌ Erro fatal ao iniciar o bot: {e}")
    else:
        print("❌ DISCORD_BOT_TOKEN não encontrado nas variáveis de ambiente.")
        while True:
            asyncio.run(asyncio.sleep(3600))
