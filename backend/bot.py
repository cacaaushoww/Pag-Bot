import os
import discord
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

# Carregar variáveis de ambiente (para tokens e IDs)
# Em um ambiente de produção, use variáveis de ambiente ou um arquivo .env seguro
# Exemplo: DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# Para este exemplo, usaremos placeholders

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
LOG_CHANNEL_ID = 123456789012345678 # Substitua pelo ID do seu canal de logs

# Inicializar clientes das funcionalidades
payment_processor = PaymentProcessor(MP_ACCESS_TOKEN)
product_deliverer = ProductDeliverer(DISCORD_BOT_TOKEN) # O deliverer usa o mesmo token do bot principal
discord_logger = DiscordLogger(DISCORD_BOT_TOKEN, LOG_CHANNEL_ID)
data_backup = DataBackup()

# Configuração do bot Discord
intents = discord.Intents.default()
intents.message_content = True # Necessário para ler o conteúdo das mensagens
intents.members = True # Necessário para buscar membros

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Bot VendaBot logado como {bot.user.name} ({bot.user.id})')
    print('------')
    # Iniciar tarefas em background, se houver
    daily_backup.start()
    # Conectar o logger e deliverer ao cliente do bot principal
    discord_logger.client = bot
    product_deliverer.client = bot
    await discord_logger.client.wait_until_ready()
    await discord_logger.on_ready() # Chamar on_ready do logger para configurar o canal

@bot.command(name="ping")
async def ping(ctx):
    "Verifica se o bot está online."
    await ctx.send("Pong!")

@bot.command(name="criar_pix")
async def create_pix_command(ctx, amount: float, description: str, payer_email: str):
    "Cria um pagamento Pix e retorna o QR Code ou link."
    await ctx.send(f"Gerando pagamento Pix para {amount:.2f} com descrição '{description}'...")
    
    # Em um cenário real, você geraria um external_reference único
    external_reference = f"ORDER-{ctx.author.id}-{datetime.datetime.now().timestamp()}"
    
    payment_data = payment_processor.create_pix_payment(amount, description, external_reference, payer_email)
    
    if payment_data and payment_data.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code_base64"):
        qr_code_base64 = payment_data["point_of_interaction"]["transaction_data"]["qr_code_base64"]
        qr_code_text = payment_data["point_of_interaction"]["transaction_data"]["qr_code"]
        
        # Em um bot real, você enviaria o QR Code como imagem ou o texto para o usuário
        await ctx.send(f"Pagamento Pix gerado! Escaneie o QR Code ou use o código:\n```\n{qr_code_text}\n```\n(Para fins de demonstração, o QR Code real seria uma imagem aqui.)")
        await discord_logger.log_event("PIX_CREATED", f"Pagamento Pix de R$ {amount:.2f} criado por {ctx.author.name}")
    else:
        await ctx.send("Erro ao gerar pagamento Pix. Verifique as configurações do Mercado Pago.")
        await discord_logger.log_event("PIX_ERROR", f"Falha ao criar Pix para {ctx.author.name}")

@bot.command(name="entregar_produto")
async def deliver_product_command(ctx, user_id: int, *, product_details: str):
    "Entrega um produto para um usuário específico via DM."
    await ctx.send(f"Tentando entregar produto para o usuário {user_id}...")
    
    success = await product_deliverer.send_product(user_id, product_details)
    
    if success:
        await ctx.send(f"Produto entregue com sucesso para o usuário {user_id}!")
        await discord_logger.log_event("PRODUCT_DELIVERED", f"Produto entregue para {user_id} por {ctx.author.name}")
    else:
        await ctx.send(f"Falha ao entregar produto para o usuário {user_id}. Verifique o ID e as permissões de DM.")
        await discord_logger.log_event("DELIVERY_ERROR", f"Falha na entrega para {user_id} por {ctx.author.name}")

@tasks.loop(hours=24) # Executa a cada 24 horas
async def daily_backup():
    "Realiza um backup diário dos dados do bot."
    print("Iniciando backup diário...")
    # Em um bot real, você coletaria os dados do seu banco de dados ou de outras fontes
    sample_data = {
        "timestamp": str(datetime.datetime.now()),
        "total_sales_today": 10,
        "active_products": 50,
        "users": ["user1", "user2"]
    }
    backup_file = data_backup.create_backup(sample_data, "vendabot_daily_data")
    if backup_file:
        print(f"Backup diário concluído: {backup_file}")
        await discord_logger.log_event("BACKUP_SUCCESS", f"Backup diário criado: {backup_file}")
    else:
        print("Falha no backup diário.")
        await discord_logger.log_event("BACKUP_FAILURE", "Falha ao criar backup diário.")

@daily_backup.before_loop
async def before_daily_backup():
    await bot.wait_until_ready()
    print("Esperando o bot estar pronto para iniciar o backup diário...")

# Configuração do Flask para o Render
app = Flask('')

@app.route('/')
def home():
    return "VendaBot está online!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# Para rodar o bot
if __name__ == "__main__":
    keep_alive() # Inicia o servidor web em uma thread separada
    # Instalar as dependências necessárias
    print("Certifique-se de instalar as bibliotecas: pip install requests discord.py")
    
    # Iniciar o bot
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("Erro de login: Token do bot inválido. Verifique DISCORD_BOT_TOKEN.")
    except Exception as e:
        print(f"Ocorreu um erro ao iniciar o bot: {e}")
