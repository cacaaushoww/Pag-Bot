import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import datetime
from flask import Flask
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
    await interaction.response.defer(ephemeral=True) # Evita timeout e esconde a resposta inicial
    
    external_reference = f"ORDER-{interaction.user.id}-{datetime.datetime.now().timestamp()}"
    payment_data = payment_processor.create_pix_payment(valor, descricao, external_reference, email)
    
    if payment_data and "point_of_interaction" in payment_data:
        transaction_data = payment_data["point_of_interaction"]["transaction_data"]
        qr_code_text = transaction_data["qr_code"]
        
        embed = discord.Embed(title="💳 Pagamento Pix Gerado", color=discord.Color.green())
        embed.add_field(name="Produto", value=descricao, inline=False)
        embed.add_field(name="Valor", value=f"R$ {valor:.2f}", inline=True)
        embed.add_field(name="Código Copia e Cola", value=f"```\n{qr_code_text}\n```", inline=False)
        embed.set_footer(text="Pague para receber seu produto automaticamente!")
        
        await interaction.followup.send(embed=embed)
        await discord_logger.log_event("PIX_CREATED", f"Pix de R$ {valor:.2f} gerado por {interaction.user.name}")
    else:
        await interaction.followup.send("❌ Erro ao gerar Pix. Verifique as configurações do Mercado Pago.")

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
@app.route('/')
def home(): return "VendaBot Slash Online!"

def run_web(): app.run(host='0.0.0.0', port=8080)
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
