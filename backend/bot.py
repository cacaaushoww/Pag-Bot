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
from pix_gerador import gerar_payload_pix, gerar_qrcode_base64

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

payment_processor = PaymentProcessor(MP_ACCESS_TOKEN)
product_deliverer = ProductDeliverer(DISCORD_BOT_TOKEN)
discord_logger = DiscordLogger(DISCORD_BOT_TOKEN, LOG_CHANNEL_ID)
data_backup = DataBackup()

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'database.json'))


def ler_settings(guild_id=None):
    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        if guild_id:
            guild_id_str = str(guild_id)
            all_guild_settings = db.get('guild_settings', {})
            # Se não existir config para este servidor, retorna o padrão
            return all_guild_settings.get(guild_id_str, {
                "payment_method_active": "mercadopago",
                "pix_key": "",
                "mp_access_token": ""
            })
        
        # Fallback para compatibilidade ou retorno vazio
        return db.get('settings', {})
    except Exception as e:
        print(f"Erro ao ler settings do database.json: {e}")
        return {}


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
        daily_backup.start()
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

    # ── MÉTODO: PIX DIRETO ──────────────────────────────────────────────────
    if metodo_ativo == "pix":
        chave_pix = settings.get("pix_key", "").strip()

        if not chave_pix:
            await interaction.followup.send(
                "O método PIX está ativo, mas nenhuma chave PIX foi configurada no painel.\n"
                "Vá em **Pagamentos → PIX → Configurar** e salve uma chave."
            )
            return

        try:
            # gerar_payload_pix agora retorna (payload, tipo_chave, chave_formatada)
            payload, tipo_chave, chave_exibicao = gerar_payload_pix(
                chave_pix=chave_pix,
                valor=valor,
                descricao=descricao,
            )
        except Exception as e:
            await interaction.followup.send(f"Erro ao gerar o código PIX: {e}")
            return

        labels = {
            'cpf': 'CPF',
            'cnpj': 'CNPJ',
            'telefone': 'Telefone',
            'email': 'E-mail',
            'aleatoria': 'Chave Aleatória',
        }

        embed = discord.Embed(
            title="Pagamento PIX Gerado",
            description=f"**{descricao}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Valor",  value=f"R$ {valor:.2f}",              inline=True)
        embed.add_field(name="Status", value="Aguardando Pagamento",       inline=True)
        embed.add_field(
            name="Código Copia e Cola",
            value=f"```\n{payload}\n```",
            inline=False
        )
        embed.set_footer(text="Cole este código no app do seu banco. O valor já vem preenchido.")

        qr_bytes = gerar_qrcode_base64(payload)
        if qr_bytes:
            import io as _io
            arquivo_qr = discord.File(_io.BytesIO(qr_bytes), filename="qrcode_pix.png")
            embed.set_image(url="attachment://qrcode_pix.png")
            await interaction.followup.send(embed=embed, file=arquivo_qr)
        else:
            await interaction.followup.send(embed=embed)

        await discord_logger.log_event(
            "PIX_CREATED",
            f"PIX direto de R$ {valor:.2f} gerado por {interaction.user.name}\n"
            f"Descrição: {descricao}\n"
            f"Tipo de chave: {labels.get(tipo_chave, '?')} ({chave_exibicao})"
        )
        print(f"✅ PIX direto criado — tipo: {tipo_chave}, chave: {chave_exibicao}")
        return

    # ── MÉTODO: MERCADO PAGO ────────────────────────────────────────────────
    if not email or "@" not in email:
        await interaction.followup.send("Email inválido! O método Mercado Pago exige um email do cliente.")
        return

    external_reference = f"ORDER-{interaction.user.id}-{int(datetime.datetime.now().timestamp())}"

    print(f"\n📝 Tentando criar PIX (Mercado Pago):")
    print(f"  Valor: R$ {valor}  Descrição: {descricao}  Email: {email}  Reference: {external_reference}")

    payment_data = payment_processor.create_pix_payment(valor, descricao, external_reference, email)

    print(f"\n📦 Resposta da API:")
    print(json.dumps(payment_data, indent=2, ensure_ascii=False))

    if "error" in payment_data:
        error = payment_data["error"]
        await interaction.followup.send(
            f"Erro ao gerar PIX:\n```\n{error}\n```\n\n"
            f"**Verifique:**\n"
            f"• MP_ACCESS_TOKEN está configurado no Render?\n"
            f"• O token é válido e não expirou?\n"
            f"• A conta do Mercado Pago está em boa situação?"
        )
        return

    qr_code = None
    copy_paste = None

    if "point_of_interaction" in payment_data:
        try:
            qr_code = payment_data["point_of_interaction"]["transaction_data"]["qr_code"]
            copy_paste = qr_code
        except (KeyError, TypeError):
            pass

    if not qr_code and "transaction_data" in payment_data:
        try:
            qr_code = payment_data["transaction_data"]["qr_code"]
            copy_paste = qr_code
        except (KeyError, TypeError):
            pass

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

    if qr_code and copy_paste:
        embed = discord.Embed(
            title="Pagamento PIX Gerado",
            description=f"**{descricao}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Valor",  value=f"R$ {valor:.2f}",        inline=True)
        embed.add_field(name="Status", value="Aguardando Pagamento", inline=True)
        embed.add_field(
            name="Código Copia e Cola",
            value=f"```\n{copy_paste}\n```",
            inline=False
        )
        embed.set_footer(text="Pague para receber seu produto automaticamente!")
        await interaction.followup.send(embed=embed)

        await discord_logger.log_event(
            "PIX_CREATED",
            f"PIX de R$ {valor:.2f} gerado por {interaction.user.name}\n"
            f"Descrição: {descricao}\nReference: {external_reference}"
        )
        print(f"✅ PIX criado com sucesso (método: mercadopago)!")
    else:
        await interaction.followup.send(
            f"⚠️ PIX foi criado, mas não consegui extrair o QR Code!\n\n"
            f"**Resposta da API (para debug):**\n"
            f"```json\n{json.dumps(payment_data, indent=2, ensure_ascii=False)[:1800]}\n```"
        )


@bot.tree.command(name="entregar", description="Entrega um produto manualmente para um usuário")
@app_commands.describe(
    usuario="O usuário que vai receber o produto",
    produto="Link ou detalhes do produto"
)
async def entregar(interaction: discord.Interaction, usuario: discord.Member, produto: str):
    await interaction.response.defer()
    success = await product_deliverer.send_product(usuario.id, produto)
    if success:
        await interaction.followup.send(f"Produto entregue com sucesso para {usuario.mention}!")
        await discord_logger.log_event("MANUAL_DELIVERY", f"Produto entregue para {usuario.name} por {interaction.user.name}")
    else:
        await interaction.followup.send(f"Falha ao entregar para {usuario.mention}. DMs fechadas?")


@tasks.loop(hours=24)
async def daily_backup():
    sample_data = {"timestamp": str(datetime.datetime.now()), "status": "ok"}
    data_backup.create_backup(sample_data, "vendabot_backup")


app = Flask('')

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
    is_ready = bot.is_ready()
    return {
        "online": is_ready,
        "bot_name": bot.user.name if bot.user else None,
        "guild_count": len(bot.guilds) if is_ready else 0,
    }

@app.route('/api/server-info')
def api_server_info():
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
    if not bot.is_ready() or not bot.user:
        return {"online": False, "name": None}
    
    guild_id = request.args.get("guild_id")
    if not guild_id:
        return {"ok": False, "error": "guild_id é obrigatório"}, 400

    guild = bot.get_guild(int(guild_id))
    if not guild:
        return {"ok": False, "error": "Servidor não encontrado"}, 404

    bot_member = guild.me

    if request.method == 'GET':
        return {"online": True, "name": bot_member.nick or bot.user.name}

    data = request.get_json(silent=True) or {}
    new_name = (data.get("name") or "").strip()
    
    if not new_name:
        return {"ok": False, "error": "Nome vazio"}, 400

    try:
        # Em vez de mudar o nome global, muda o apelido no servidor
        await bot_member.edit(nick=new_name)
        return {"ok": True, "name": new_name}
    except discord.Forbidden:
        return {"ok": False, "error": "O bot não tem permissão para mudar o próprio apelido neste servidor."}, 403
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.route('/api/config', methods=['POST', 'OPTIONS'])
def api_config():
    if request.method == 'OPTIONS':
        return '', 204
    
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    
    if not guild_id:
        return {"ok": False, "error": "guild_id é obrigatório"}, 400
    
    guild_id_str = str(guild_id)
    db_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'database.json'))
    
    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        if 'guild_settings' not in db:
            db['guild_settings'] = {}
        
        if guild_id_str not in db['guild_settings']:
            db['guild_settings'][guild_id_str] = {
                "payment_method_active": "mercadopago",
                "pix_key": "",
                "mp_access_token": ""
            }
        
        settings = db['guild_settings'][guild_id_str]
        
        if 'pix_key' in data:
            settings['pix_key'] = data['pix_key']
        if 'mp_access_token' in data:
            settings['mp_access_token'] = data['mp_access_token']
            # Nota: O processador de pagamentos global precisará ser instanciado por request ou ter o token passado
        if 'mp_pix_key' in data:
            settings['mp_pix_key'] = data['mp_pix_key']
        if 'payment_method_active' in data:
            metodo = data['payment_method_active']
            if metodo not in ('pix', 'mercadopago'):
                return {"ok": False, "error": "payment_method_active deve ser 'pix' ou 'mercadopago'"}, 400
            settings['payment_method_active'] = metodo
            
        with open(db_path, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.route('/api/payment-method', methods=['GET'])
def api_payment_method():
    guild_id = request.args.get("guild_id")
    settings = ler_settings(guild_id)
    return {"ok": True, "active": settings.get("payment_method_active", "mercadopago")}


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
