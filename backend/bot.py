import os
import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import datetime
from flask import Flask, request
from threading import Thread

from payments import PaymentProcessor
from delivery import ProductDeliverer
from logger import DiscordLogger
from backup import DataBackup

# Configurações de Tokens via Variáveis de Ambiente (Segurança)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# Inicializar clientes das funcionalidades
payment_processor = PaymentProcessor(MP_ACCESS_TOKEN)
product_deliverer = ProductDeliverer(DISCORD_BOT_TOKEN)
discord_logger = DiscordLogger(DISCORD_BOT_TOKEN, LOG_CHANNEL_ID)
data_backup = DataBackup()

# Configuração do bot Discord
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Sincroniza os comandos de barra com o Discord
        print("Sincronizando comandos de barra...")
        await self.tree.sync()
        print("Comandos sincronizados!")
        
        # Iniciar tarefas em background
        daily_backup.start()
        
        # Configurar logger e deliverer
        discord_logger.client = self
        product_deliverer.client = self

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Bot VendaBot logado como {bot.user.name} ({bot.user.id})')
    print('------')
    await discord_logger.on_ready()

# --- SLASH COMMANDS (/) ---

@bot.tree.command(name="ping", description="Verifica se o bot está online")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latência: {round(bot.latency * 1000)}ms")

@bot.tree.command(name="criar_pix", description="Gera um pagamento Pix real")
@app_commands.describe(
    valor="Valor do produto (ex: 10.50)",
    descricao="O que o cliente está comprando",
    email="Email do cliente para o Mercado Pago"
)
async def criar_pix(interaction: discord.Interaction, valor: float, descricao: str, email: str):
    await interaction.response.defer(ephemeral=True)
    
    # Validações básicas
    if valor <= 0:
        await interaction.followup.send("❌ O valor deve ser maior que 0!")
        return
    
    if not email or "@" not in email:
        await interaction.followup.send("❌ Email inválido!")
        return
    
    external_reference = f"ORDER-{interaction.user.id}-{int(datetime.datetime.now().timestamp())}"
    
    print(f"\n📝 Tentando criar PIX:")
    print(f"  Valor: R$ {valor}")
    print(f"  Descrição: {descricao}")
    print(f"  Email: {email}")
    print(f"  Reference: {external_reference}")
    
    payment_data = payment_processor.create_pix_payment(valor, descricao, external_reference, email)
    
    # Debug: imprime a resposta completa
    print(f"\n📦 Resposta da API:")
    print(json.dumps(payment_data, indent=2, ensure_ascii=False))
    
    # Verifica se houve erro
    if "error" in payment_data:
        error = payment_data["error"]
        await interaction.followup.send(
            f"❌ Erro ao gerar PIX:\n```\n{error}\n```\n\n"
            f"**Verifique:**\n"
            f"• MP_ACCESS_TOKEN está configurado no Render?\n"
            f"• O token é válido e não expirou?\n"
            f"• A conta do Mercado Pago está em boa situação?"
        )
        return
    
    # Tenta extrair o QR Code de diferentes possíveis locais na resposta
    qr_code = None
    copy_paste = None
    
    # Tentativa 1: point_of_interaction (estrutura esperada)
    if "point_of_interaction" in payment_data:
        try:
            qr_code = payment_data["point_of_interaction"]["transaction_data"]["qr_code"]
            copy_paste = payment_data["point_of_interaction"]["transaction_data"]["qr_code"]
        except (KeyError, TypeError):
            pass
    
    # Tentativa 2: Procurar diretamente em transaction_data
    if not qr_code and "transaction_data" in payment_data:
        try:
            qr_code = payment_data["transaction_data"]["qr_code"]
            copy_paste = payment_data["transaction_data"]["qr_code"]
        except (KeyError, TypeError):
            pass
    
    # Tentativa 3: Procurar por "qr_code" em qualquer lugar
    if not qr_code:
        def find_qr_code(obj):
            if isinstance(obj, dict):
                if "qr_code" in obj:
                    return obj["qr_code"]
                for value in obj.values():
                    result = find_qr_code(value)
                    if result:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = find_qr_code(item)
                    if result:
                        return result
            return None
        
        qr_code = find_qr_code(payment_data)
        copy_paste = qr_code
    
    # Se conseguiu extrair o QR Code
    if qr_code and copy_paste:
        embed = discord.Embed(
            title="💳 Pagamento PIX Gerado",
            description=f"**{descricao}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Valor", value=f"R$ {valor:.2f}", inline=True)
        embed.add_field(name="Status", value="⏳ Aguardando Pagamento", inline=True)
        embed.add_field(
            name="Código Copia e Cola",
            value=f"```\n{copy_paste}\n```",
            inline=False
        )
        embed.set_footer(text="Pague para receber seu produto automaticamente!")
        
        await interaction.followup.send(embed=embed)
        
        # Log do evento
        await discord_logger.log_event(
            "PIX_CREATED",
            f"PIX de R$ {valor:.2f} gerado por {interaction.user.name}\n"
            f"Descrição: {descricao}\n"
            f"Reference: {external_reference}"
        )
        print(f"✅ PIX criado com sucesso!")
        
    else:
        # Se não conseguiu extrair, mostra a resposta completa para debug
        await interaction.followup.send(
            f"⚠️ PIX foi criado, mas não consegui extrair o QR Code!\n\n"
            f"**Resposta da API (para debug):**\n"
            f"```json\n{json.dumps(payment_data, indent=2, ensure_ascii=False)[:1800]}\n```"
        )
        print(f"⚠️ Não foi possível extrair QR Code da resposta")

@bot.tree.command(name="entregar", description="Entrega um produto manualmente para um usuário")
@app_commands.describe(
    usuario="O usuário que vai receber o produto",
    produto="Link ou detalhes do produto"
)
async def entregar(interaction: discord.Interaction, usuario: discord.Member, produto: str):
    await interaction.response.defer()
    
    success = await product_deliverer.send_product(usuario.id, produto)
    
    if success:
        await interaction.followup.send(f"✅ Produto entregue com sucesso para {usuario.mention}!")
        await discord_logger.log_event("MANUAL_DELIVERY", f"Produto entregue para {usuario.name} por {interaction.user.name}")
    else:
        await interaction.followup.send(f"❌ Falha ao entregar para {usuario.mention}. DMs fechadas?")

# --- TAREFAS E WEB SERVER ---

@tasks.loop(hours=24)
async def daily_backup():
    sample_data = {"timestamp": str(datetime.datetime.now()), "status": "ok"}
    data_backup.create_backup(sample_data, "vendabot_backup")

app = Flask('')

# Libera o acesso do painel (GitHub Pages) à API do bot (CORS)
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route('/')
def home(): return "VendaBot Slash Online!"

@app.route('/api/status')
def api_status():
    """Status geral do bot para o painel."""
    is_ready = bot.is_ready()
    return {
        "online": is_ready,
        "bot_name": bot.user.name if bot.user else None,
        "guild_count": len(bot.guilds) if is_ready else 0,
    }

@app.route('/api/server-info')
def api_server_info():
    """Retorna o(s) servidor(es) onde o bot está."""
    if not bot.is_ready():
        return {"online": False, "servers": []}

    servers = []
    for guild in bot.guilds:
        servers.append({
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "icon": str(guild.icon.url) if guild.icon else None,
        })
    return {"online": True, "servers": servers}

@app.route('/api/channels')
def api_channels():
    """Lista os canais de texto reais do servidor para os seletores de configuração."""
    if not bot.is_ready() or not bot.guilds:
        return {"online": False, "channels": []}

    guild_id = request.args.get("guild_id")
    guild = None
    if guild_id:
        guild = discord.utils.get(bot.guilds, id=int(guild_id))
    if guild is None:
        guild = bot.guilds[0]

    channels = []
    for channel in guild.text_channels:
        channels.append({
            "id": str(channel.id),
            "name": channel.name,
            "category": channel.category.name if channel.category else None,
        })
    return {"online": True, "guild_name": guild.name, "channels": channels}

@app.route('/api/bot-name', methods=['GET', 'POST'])
def api_bot_name():
    """Lê o nome atual do bot (GET) ou altera o nome do bot no Discord (POST)."""
    if not bot.is_ready() or not bot.user:
        return {"online": False, "name": None}

    if request.method == 'GET':
        return {"online": True, "name": bot.user.name}

    data = request.get_json(silent=True) or {}
    new_name = (data.get("name") or "").strip()
    if not new_name:
        return {"ok": False, "error": "Nome vazio"}, 400

    if not DISCORD_BOT_TOKEN:
        return {"ok": False, "error": "Token do bot não configurado"}, 500

    try:
        resp = requests.patch(
            "https://discord.com/api/v10/users/@me",
            headers={
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"username": new_name},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"ok": True, "name": new_name}

        try:
            err = resp.json()
            msg = err.get("message", "Erro do Discord")
            if resp.status_code == 429 or "rate" in str(err).lower():
                retry = err.get("retry_after")
                msg = f"Limite de troca de nome atingido. Tente novamente em {int(retry)}s." if retry else "Limite de troca de nome atingido (2 por hora)."
        except Exception:
            msg = f"Erro {resp.status_code} do Discord"
        return {"ok": False, "error": msg}, 400
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

def run_web(): app.run(host='0.0.0.0', port=int(os.getenv("PORT", "8080")))
def keep_alive(): Thread(target=run_web).start()

if __name__ == "__main__":
    keep_alive()
    if DISCORD_BOT_TOKEN:
        try:
            bot.run(DISCORD_BOT_TOKEN)
        except Exception as e:
            print(f"Erro ao iniciar bot: {e}")
    else:
        print("DISCORD_BOT_TOKEN não encontrado nas variáveis de ambiente.")
