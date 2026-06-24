import os
import secrets
import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import datetime
import json
from flask import Flask, request, jsonify, redirect, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from threading import Thread
from functools import wraps
from supabase import create_client, Client
from dotenv import load_dotenv

import auth as auth_mod

load_dotenv()

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

# URL completa do painel — em produção isso deve ser o domínio real do
# seu front-end, NUNCA "*". Aceita tanto domínio puro
# (https://meusite.com) quanto GitHub Pages de projeto, que vem com
# uma subpasta (https://usuario.github.io/NomeDoRepo/).
#
# Dessa URL completa a gente tira duas coisas diferentes:
#   - FRONTEND_URL: usada pra redirecionar o usuário de volta pro
#     painel depois do login (precisa da subpasta, senão ele cai numa
#     página em branco/404 do GitHub Pages).
#   - CORS_ORIGIN: usada no header de CORS, que só entende
#     protocolo+domínio, sem subpasta — senão o navegador bloqueia a
#     resposta da API.
from urllib.parse import urlparse

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
FRONTEND_URL = FRONTEND_ORIGIN.rstrip("/")
_parsed_frontend = urlparse(FRONTEND_ORIGIN)
CORS_ORIGIN = f"{_parsed_frontend.scheme}://{_parsed_frontend.netloc}"

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"

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
        "mp_access_token": "",
        "automations": {
            "mensagens_automaticas": True,
            "cargos_automaticos": True,
            "respostas_automaticas": False,
            "logs_automaticos": True,
            "entrega_automatica": True
        }
    }
    if not supabase:
        return default_settings
    try:
        response = supabase.table("guild_settings").select("*").eq("guild_id", str(guild_id)).execute()
        if response.data and len(response.data) > 0:
            settings = response.data[0]
            # Garante que automations exista
            if "automations" not in settings or not settings["automations"]:
                settings["automations"] = default_settings["automations"]
            return settings
        else:
            supabase.table("guild_settings").insert(default_settings).execute()
            return default_settings
    except Exception as e:
        print(f"❌ Erro ao ler settings: {e}")
        return default_settings


def log_event(guild_id, event_type, description):
    """Salva log no Supabase e tenta enviar no Discord."""
    try:
        if supabase and guild_id:
            supabase.table("activity_logs").insert({
                "guild_id": str(guild_id),
                "event_type": event_type,
                "description": description
            }).execute()
    except Exception as e:
        print(f"Erro ao salvar log no Supabase: {e}")


def get_active_automations(guild_id):
    """Retorna as automações ativas de um servidor."""
    settings = ler_settings(guild_id)
    automations = settings.get("automations", {})
    if isinstance(automations, str):
        try:
            automations = json.loads(automations)
        except:
            automations = {
                "mensagens_automaticas": True,
                "cargos_automaticos": True,
                "respostas_automaticas": False,
                "logs_automaticos": True,
                "entrega_automatica": True
            }
    return automations


# ──────────────────────────────────────────────
#  AUTENTICAÇÃO — SESSÃO E AUTORIZAÇÃO POR GUILD
# ──────────────────────────────────────────────

def get_session():
    """Lê e valida o cookie de sessão da requisição atual."""
    token = request.cookies.get("session")
    if not token:
        return None
    return auth_mod.verify_session_token(token)


def require_auth(f):
    """Exige que exista uma sessão válida (usuário logado via Discord).
    Não checa guild específica — usar quando a rota não recebe guild_id
    ou quando a checagem de guild é feita manualmente dentro da rota."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        session = get_session()
        if not session:
            return jsonify({"ok": False, "error": "Não autenticado. Faça login."}), 401
        return f(session, *args, **kwargs)
    return wrapper


def require_guild(f):
    """Exige sessão válida E que o guild_id pedido esteja entre os
    servidores que o usuário logado administra no Discord."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        session = get_session()
        if not session:
            return jsonify({"ok": False, "error": "Não autenticado. Faça login."}), 401
        guild_id = request.args.get("guild_id") or (request.get_json(silent=True) or {}).get("guild_id")
        if not guild_id:
            return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
        if str(guild_id) not in session.get("guild_ids", []):
            return jsonify({"ok": False, "error": "Você não tem permissão sobre este servidor"}), 403
        return f(str(guild_id), session, *args, **kwargs)
    return wrapper


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
            print(f"❌ Erro ao sincronizar: {e}")
        discord_logger.client = self
        product_deliverer.client = self

bot = MyBot()

@bot.event
async def on_ready():
    print(f'🚀 Bot logado como {bot.user.name} ({bot.user.id})')
    try:
        await discord_logger.on_ready()
    except Exception as e:
        print(f"⚠️ Erro no logger.on_ready: {e}")

@bot.tree.command(name="ping", description="Verifica se o bot está online")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! Latência: {round(bot.latency * 1000)}ms")


# ──────────────────────────────────────────────
#  COMANDOS DE PRODUTOS
# ──────────────────────────────────────────────

@bot.tree.command(name="produtos", description="Lista todos os produtos disponíveis no servidor")
async def produtos(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if not supabase:
        await interaction.response.send_message("❌ Banco de dados não configurado.", ephemeral=True)
        return

    try:
        res = supabase.table("products").select("*").eq("guild_id", guild_id).eq("status", "Ativo").execute()
        products = res.data or []
        if not products:
            await interaction.response.send_message("📦 Nenhum produto cadastrado neste servidor.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📦 Produtos Disponíveis",
            description=f"{len(products)} produto(s) encontrado(s):",
            color=discord.Color.blue()
        )
        for p in products[:25]:
            stock = p.get("stock", "∞")
            desc = p.get("description", "")[:60]
            embed.add_field(
                name=f"{p['name']} — R$ {float(p['price']):,.2f}",
                value=f"ID: `{p['id']}` | Estoque: {stock}{' | ' + desc if desc else ''}",
                inline=False
            )
        embed.set_footer(text="Use /comprar <id_do_produto> para comprar")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erro ao listar produtos: {e}", ephemeral=True)


@bot.tree.command(name="criar_pix", description="Cria um pagamento PIX manualmente")
@app_commands.describe(valor="Valor do PIX", descricao="Descrição do pagamento")
async def criar_pix(interaction: discord.Interaction, valor: float, descricao: str):
    guild_id = str(interaction.guild_id)
    settings = ler_settings(guild_id)
    metodo = settings.get("payment_method_active", "mercadopago")

    await interaction.response.defer(ephemeral=True)

    try:
        if metodo == "mercadopago":
            # Usa Mercado Pago
            mp_token = settings.get("mp_access_token") or MP_ACCESS_TOKEN
            if not mp_token:
                await interaction.followup.send("❌ Mercado Pago não configurado. Configure no painel.", ephemeral=True)
                return

            processor = PaymentProcessor(mp_token)
            reference = f"PIX-{interaction.user.id}-{int(datetime.datetime.utcnow().timestamp())}"
            payment_data = processor.create_pix_payment(
                amount=valor,
                description=descricao,
                external_reference=reference,
                payer_email=f"user_{interaction.user.id}@discord.bot"
            )

            if "error" in payment_data:
                await interaction.followup.send(f"❌ Erro ao criar PIX: {payment_data['error']}", ephemeral=True)
                return

            qr_code = payment_data.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code", "")
            payment_id = payment_data.get("id", "")

            embed = discord.Embed(
                title="💰 Pagamento PIX — Mercado Pago",
                description=f"**{descricao}**\nValor: **R$ {valor:,.2f}**",
                color=discord.Color.green()
            )
            if qr_code:
                embed.add_field(name="Código PIX (copia e cola):", value=f"```{qr_code}```", inline=False)
            embed.add_field(name="ID do Pagamento:", value=f"`{payment_id}`", inline=False)
            embed.add_field(name="Status:", value="⏳ Aguardando pagamento...", inline=False)
            embed.set_footer(text="Assim que o pagamento for confirmado, o produto será entregue automaticamente.")
            await interaction.followup.send(embed=embed, ephemeral=True)

        else:
            # Usa PIX puro
            pix_key = settings.get("pix_key", "")
            if not pix_key:
                await interaction.followup.send("❌ Chave PIX não configurada. Configure no painel.", ephemeral=True)
                return

            import io
            payload, tipo, chave_fmt = gerar_payload_pix(
                chave_pix=pix_key,
                valor=valor,
                descricao=descricao,
                txid=f"VENDA{interaction.user.id}{int(datetime.datetime.utcnow().timestamp())}"
            )

            qr_bytes = gerar_qrcode_base64(payload)
            embed = discord.Embed(
                title="💰 Pagamento PIX",
                description=f"**{descricao}**\nValor: **R$ {valor:,.2f}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Código PIX (copia e cola):", value=f"```{payload}```", inline=False)
            embed.add_field(name="Chave PIX usada:", value=f"{tipo.upper()}: `{chave_fmt}`", inline=False)
            if qr_bytes:
                file = discord.File(io.BytesIO(qr_bytes), filename="pix_qrcode.png")
                embed.set_image(url="attachment://pix_qrcode.png")
                await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Erro ao criar PIX: {e}", ephemeral=True)


@bot.tree.command(name="comprar", description="Compra um produto do servidor")
@app_commands.describe(produto_id="ID do produto", cupom="Código de cupom de desconto (opcional)")
async def comprar(interaction: discord.Interaction, produto_id: int, cupom: str = None):
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    await interaction.response.defer(ephemeral=True)

    if not supabase:
        await interaction.followup.send("❌ Banco de dados não configurado.", ephemeral=True)
        return

    try:
        # Busca o produto
        res = supabase.table("products").select("*").eq("id", produto_id).eq("guild_id", guild_id).execute()
        if not res.data:
            await interaction.followup.send("❌ Produto não encontrado.", ephemeral=True)
            return

        product = res.data[0]
        if product.get("status") != "Ativo":
            await interaction.followup.send("❌ Este produto não está disponível para venda.", ephemeral=True)
            return

        price = float(product.get("price", 0))

        # Aplica cupom se fornecido
        discount = 0
        if cupom:
            cupom_res = supabase.table("coupons").select("*").eq("guild_id", guild_id).eq("code", cupom.upper()).execute()
            if cupom_res.data and len(cupom_res.data) > 0:
                coupon = cupom_res.data[0]
                # Verifica expiração
                if coupon.get("expires_at") and datetime.datetime.fromisoformat(coupon["expires_at"].replace("Z", "+00:00")) < datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc):
                    await interaction.followup.send("❌ Cupom expirado.", ephemeral=True)
                    return
                # Verifica usos
                max_uses = coupon.get("max_uses")
                uses = coupon.get("uses", 0)
                if max_uses is not None and uses >= max_uses:
                    await interaction.followup.send("❌ Cupom esgotado.", ephemeral=True)
                    return
                discount = coupon.get("discount_percent", 0)
                price = price * (1 - discount / 100)
                # Incrementa uso
                supabase.table("coupons").update({"uses": uses + 1}).eq("id", coupon["id"]).execute()
            else:
                await interaction.followup.send("❌ Cupom inválido.", ephemeral=True)
                return

        if price <= 0:
            # Produto gratuito — entrega direta
            order_ref = f"GRATIS-{interaction.user.id}-{int(datetime.datetime.utcnow().timestamp())}"
            supabase.table("orders").insert({
                "guild_id": guild_id,
                "order_reference": order_ref,
                "customer_id": user_id,
                "customer_name": interaction.user.name,
                "product_id": produto_id,
                "amount": 0,
                "status": "Pago"
            }).execute()

            # Entrega automática
            automations = get_active_automations(guild_id)
            delivery_content = product.get("delivery_content", "")
            if automations.get("entrega_automatica", True) and delivery_content:
                try:
                    await interaction.user.send(f"🎉 Aqui está seu produto **{product['name']}**:\n\n{delivery_content}")
                except:
                    pass

            await interaction.followup.send(f"🎉 **{product['name']}** entregue! Verifique suas DM's.", ephemeral=True)
            log_event(guild_id, "venda", f"Produto gratuito '{product['name']}' entregue para {interaction.user.name}")
            return

        # Cria pedido no banco
        order_ref = f"PED-{interaction.user.id}-{int(datetime.datetime.utcnow().timestamp())}"
        order_data = {
            "guild_id": guild_id,
            "order_reference": order_ref,
            "customer_id": user_id,
            "customer_name": interaction.user.name,
            "product_id": produto_id,
            "amount": round(price, 2),
            "status": "Pendente"
        }
        supabase.table("orders").insert(order_data).execute()

        settings = ler_settings(guild_id)
        metodo = settings.get("payment_method_active", "mercadopago")

        if metodo == "mercadopago":
            mp_token = settings.get("mp_access_token") or MP_ACCESS_TOKEN
            if not mp_token:
                await interaction.followup.send("❌ Mercado Pago não configurado.", ephemeral=True)
                return

            processor = PaymentProcessor(mp_token)
            payment_data = processor.create_pix_payment(
                amount=price,
                description=product["name"],
                external_reference=order_ref,
                payer_email=f"user_{interaction.user.id}@discord.bot"
            )

            if "error" in payment_data:
                await interaction.followup.send(f"❌ Erro ao gerar PIX: {payment_data['error']}", ephemeral=True)
                return

            qr_code = payment_data.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code", "")
            payment_id = payment_data.get("id", "")

            # Salva o payment_id no pedido
            supabase.table("orders").update({"payment_id": str(payment_id)}).eq("order_reference", order_ref).execute()

            embed = discord.Embed(
                title=f"💳 Compra: {product['name']}",
                description=f"Valor: **R$ {price:,.2f}**{f' (-{discount}%)' if discount > 0 else ''}\nPedido: `{order_ref}`",
                color=discord.Color.blue()
            )
            if qr_code:
                embed.add_field(name="Código PIX (copia e cola):", value=f"```{qr_code}```", inline=False)
            embed.add_field(name="Como pagar:", value="1. Copie o código acima\n2. Abra seu app do banco\n3. Cole e confirme o pagamento", inline=False)
            embed.set_footer(text="O produto será entregue automaticamente após o pagamento.")
            await interaction.followup.send(embed=embed, ephemeral=True)

        else:
            # PIX puro
            pix_key = settings.get("pix_key", "")
            if not pix_key:
                await interaction.followup.send("❌ Chave PIX não configurada.", ephemeral=True)
                return

            payload, tipo, chave_fmt = gerar_payload_pix(
                chave_pix=pix_key,
                valor=price,
                descricao=product["name"],
                txid=order_ref
            )

            embed = discord.Embed(
                title=f"💳 Compra: {product['name']}",
                description=f"Valor: **R$ {price:,.2f}**{f' (-{discount}%)' if discount > 0 else ''}\nPedido: `{order_ref}`",
                color=discord.Color.blue()
            )
            embed.add_field(name="Código PIX (copia e cola):", value=f"```{payload}```", inline=False)
            embed.add_field(name="Como pagar:", value="1. Copie o código acima\n2. Abra seu app do banco\n3. Cole e confirme o pagamento\n4. Um administrador confirmará seu pagamento", inline=False)
            embed.set_footer(text="PIX Puro: pagamentos devem ser confirmados manualmente por um admin.")
            await interaction.followup.send(embed=embed, ephemeral=True)

        log_event(guild_id, "venda", f"Pedido {order_ref} criado: {product['name']} por {interaction.user.name} (R$ {price:,.2f})")

    except Exception as e:
        await interaction.followup.send(f"❌ Erro ao processar compra: {e}", ephemeral=True)


@bot.tree.command(name="meus_pedidos", description="Lista seus pedidos neste servidor")
async def meus_pedidos(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    if not supabase:
        await interaction.response.send_message("❌ Banco de dados não configurado.", ephemeral=True)
        return

    try:
        res = supabase.table("orders").select("*, products(name)").eq("guild_id", guild_id).eq("customer_id", user_id).order("created_at", desc=True).execute()
        orders = res.data or []
        if not orders:
            await interaction.response.send_message("📭 Você ainda não fez nenhum pedido neste servidor.", ephemeral=True)
            return

        embed = discord.Embed(title="📦 Meus Pedidos", color=discord.Color.blue())
        for o in orders[:10]:
            prod_name = (o.get("products") or {}).get("name", "Produto")
            status_emoji = {"Pago": "✅", "Pendente": "⏳", "Cancelado": "❌"}.get(o.get("status", ""), "❓")
            embed.add_field(
                name=f"Pedido #{o['id']} — {prod_name}",
                value=f"{status_emoji} {o.get('status')} | R$ {float(o.get('amount', 0)):,.2f} | {o.get('created_at', '')[:10]}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Erro ao listar pedidos: {e}", ephemeral=True)


@bot.tree.command(name="ticket", description="Abre um ticket de suporte")
@app_commands.describe(assunto="Assunto do ticket")
async def ticket(interaction: discord.Interaction, assunto: str):
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)

    if not supabase:
        await interaction.response.send_message("❌ Banco de dados não configurado.", ephemeral=True)
        return

    try:
        ticket_data = {
            "guild_id": guild_id,
            "customer_id": user_id,
            "customer_name": interaction.user.name,
            "subject": assunto,
            "status": "Aberto"
        }
        res = supabase.table("tickets").insert(ticket_data).execute()
        ticket_id = res.data[0]["id"] if res.data else "?"

        embed = discord.Embed(
            title="🎫 Ticket Aberto",
            description=f"Seu ticket foi registrado com sucesso!\n**Assunto:** {assunto}",
            color=discord.Color.green()
        )
        embed.add_field(name="ID do Ticket:", value=f"#T{str(ticket_id).zfill(3)}", inline=False)
        embed.set_footer(text="Um membro da equipe responderá em breve.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

        log_event(guild_id, "ticket", f"Ticket #{ticket_id} aberto por {interaction.user.name}: {assunto}")

    except Exception as e:
        await interaction.response.send_message(f"❌ Erro ao abrir ticket: {e}", ephemeral=True)


# ──────────────────────────────────────────────
#  FLASK APP
# ──────────────────────────────────────────────

app = Flask(__name__)

# Rate limiting global — protege contra abuso/scraping. Limites mais
# apertados são aplicados rota a rota (login e escrita de dados).
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour", "40 per minute"],
    storage_uri="memory://",  # em produção com múltiplos workers, troque por Redis
)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
    response.headers["Access-Control-Allow-Credentials"] = "true"
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

# ──────────────────────────────────────────────
#  AUTENTICAÇÃO — LOGIN COM DISCORD
# ──────────────────────────────────────────────

@app.route('/api/auth/login')
@limiter.limit("10 per minute")
def api_auth_login():
    state = secrets.token_urlsafe(24)
    resp = redirect(auth_mod.build_authorize_url(state))
    resp.set_cookie(
        "oauth_state", state, max_age=600, httponly=True,
        secure=COOKIE_SECURE, samesite="Lax"
    )
    return resp

@app.route('/api/auth/callback')
@limiter.limit("10 per minute")
def api_auth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    expected_state = request.cookies.get("oauth_state")

    if not code or not state or not expected_state or state != expected_state:
        return redirect(f"{FRONTEND_URL}?login=erro&motivo=state_invalido")

    try:
        token_data = auth_mod.exchange_code_for_token(code)
        access_token = token_data["access_token"]
        user = auth_mod.fetch_discord_user(access_token)
        guilds = auth_mod.fetch_discord_user_guilds(access_token)
        guild_ids = auth_mod.filter_manageable_guild_ids(guilds)

        session_token = auth_mod.create_session_token(
            user_id=user["id"], username=user.get("username", ""), guild_ids=guild_ids
        )

        resp = redirect(f"{FRONTEND_URL}?login=sucesso")
        resp.delete_cookie("oauth_state")
        resp.set_cookie(
            "session", session_token,
            max_age=60 * 60 * 24 * auth_mod.SESSION_DAYS,
            httponly=True, secure=COOKIE_SECURE, samesite="None" if COOKIE_SECURE else "Lax"
        )
        return resp
    except Exception as e:
        print(f"❌ Erro no callback OAuth: {e}")
        return redirect(f"{FRONTEND_URL}?login=erro&motivo=falha_discord")

@app.route('/api/auth/me')
def api_auth_me():
    session = get_session()
    if not session:
        return jsonify({"ok": False, "authenticated": False}), 401
    return jsonify({
        "ok": True,
        "authenticated": True,
        "user": {"id": session["sub"], "username": session.get("username", "")},
        "guild_ids": session.get("guild_ids", []),
    })

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    resp = jsonify({"ok": True})
    resp.delete_cookie("session")
    return resp

@app.route('/api/server-info')
@require_auth
def api_server_info(session):
    if not bot.is_ready():
        if bot.user:
            return jsonify({"online": True, "servers": [], "message": "Bot logado, carregando servidores..."})
        return jsonify({"online": False, "servers": []})

    permitido = set(session.get("guild_ids", []))
    servers = []
    for guild in bot.guilds:
        if str(guild.id) not in permitido:
            continue
        servers.append({
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "icon": str(guild.icon.url) if guild.icon else None,
        })
    return jsonify({"online": True, "servers": servers})

@app.route('/api/channels')
@require_guild
def api_channels(guild_id, session):
    if not bot.is_ready():
        return jsonify({"online": False, "channels": [], "error": "Bot ainda não está pronto"})
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return jsonify({"online": True, "channels": [], "error": "Bot não está nesse servidor"})
    channels = []
    for channel in guild.text_channels:
        channels.append({
            "id": str(channel.id),
            "name": channel.name,
            "category": channel.category.name if channel.category else None,
        })
    return jsonify({"online": True, "guild_name": guild.name, "channels": channels})

@app.route('/api/bot-name', methods=['GET', 'POST'])
@require_guild
def api_bot_name(guild_id, session):
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
@limiter.limit("20 per minute")
@require_guild
def api_config(guild_id, session):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        update_data = {}
        for field in ['pix_key', 'mp_access_token', 'mp_pix_key', 'payment_method_active',
                      'canal_compras', 'canal_logs', 'canal_tickets', 'automations']:
            if field in data:
                update_data[field] = data[field]
        supabase.table("guild_settings").upsert({"guild_id": guild_id, **update_data}).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/payment-method')
@require_guild
def api_payment_method(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "active": "mercadopago"})
    try:
        response = supabase.table("guild_settings").select("payment_method_active").eq("guild_id", guild_id).execute()
        if response.data:
            return jsonify({"ok": True, "active": response.data[0].get("payment_method_active", "mercadopago")})
        return jsonify({"ok": False, "active": "mercadopago"})
    except Exception as e:
        return jsonify({"ok": False, "active": "mercadopago", "error": str(e)})

# ──────────────────────────────────────────────
#  TESTE MERCADO PAGO (seguro, pelo backend)
# ──────────────────────────────────────────────

@app.route('/api/test-mp')
@require_guild
def api_test_mp(guild_id, session):
    """Testa a conexão com Mercado Pago usando o token configurado (pelo backend, não expõe token no frontend)."""
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        settings = ler_settings(guild_id)
        mp_token = settings.get("mp_access_token") or MP_ACCESS_TOKEN
        if not mp_token:
            return jsonify({"ok": False, "error": "Access Token não configurado"}), 400

        headers = {"Authorization": f"Bearer {mp_token}"}
        resp = requests.get("https://api.mercadopago.com/v1/account", headers=headers, timeout=10)
        data = resp.json()

        if resp.ok and data.get("email"):
            return jsonify({"ok": True, "email": data["email"]})
        else:
            return jsonify({"ok": False, "error": data.get("message", "Token inválido")}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ──────────────────────────────────────────────
#  WEBHOOK MERCADO PAGO
# ──────────────────────────────────────────────

@app.route('/webhook/mercadopago', methods=['POST'])
@limiter.limit("60 per minute")
def webhook_mercadopago():
    """Recebe notificações do Mercado Pago sobre mudanças de status de pagamento."""
    data = request.get_json(silent=True) or {}
    payment_id = data.get("data", {}).get("id") or data.get("id")
    topic = data.get("topic") or data.get("type", "")

    if not payment_id or topic not in ["payment", "merchant_order", ""]:
        return jsonify({"ok": True}), 200  # Confirma recebimento mesmo se não processar

    try:
        # Busca detalhes do pagamento no MP
        headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
        resp = requests.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers=headers, timeout=10)
        if not resp.ok:
            return jsonify({"ok": True}), 200

        payment_data = resp.json()
        status = payment_data.get("status", "")
        external_ref = payment_data.get("external_reference", "")

        if status in ["approved", "authorized"] and external_ref:
            # Busca o pedido no banco
            if supabase:
                order_res = supabase.table("orders").select("*, products(*)").eq("order_reference", external_ref).execute()
                if order_res.data and len(order_res.data) > 0:
                    order = order_res.data[0]
                    if order.get("status") != "Pago":
                        # Atualiza status para Pago
                        supabase.table("orders").update({"status": "Pago"}).eq("order_reference", external_ref).execute()

                        guild_id = order.get("guild_id")
                        product = order.get("products") or {}

                        # Entrega automática
                        automations = get_active_automations(guild_id)
                        delivery_content = product.get("delivery_content", "")
                        customer_id = order.get("customer_id")

                        if automations.get("entrega_automatica", True) and delivery_content and customer_id:
                            try:
                                future = asyncio.run_coroutine_threadsafe(
                                    bot.get_user(int(customer_id)) or bot.fetch_user(int(customer_id)),
                                    bot.loop
                                )
                                user = future.result(timeout=10)
                                if user:
                                    asyncio.run_coroutine_threadsafe(
                                        user.send(f"🎉 Pagamento confirmado! Aqui está seu produto **{product.get('name', '')}**:\n\n{delivery_content}"),
                                        bot.loop
                                    )
                            except Exception as e:
                                print(f"Erro na entrega automática: {e}")

                        # Mensagem automática no canal de compras
                        if automations.get("mensagens_automaticas", True) and guild_id:
                            try:
                                settings = ler_settings(guild_id)
                                canal_id = settings.get("canal_compras")
                                if canal_id:
                                    guild = bot.get_guild(int(guild_id))
                                    if guild:
                                        channel = guild.get_channel(int(canal_id))
                                        if channel:
                                            embed = discord.Embed(
                                                title="🎉 Nova Venda!",
                                                description=f"**{order.get('customer_name')}** comprou **{product.get('name', 'Produto')}** por R$ {float(order.get('amount', 0)):,.2f}",
                                                color=discord.Color.green()
                                            )
                                            asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
                            except Exception as e:
                                print(f"Erro ao enviar mensagem automática: {e}")

                        # Logs automáticos
                        if automations.get("logs_automaticos", True):
                            log_event(guild_id, "venda", f"Pagamento confirmado: {product.get('name', 'Produto')} para {order.get('customer_name')} — R$ {float(order.get('amount', 0)):,.2f}")

        return jsonify({"ok": True}), 200

    except Exception as e:
        print(f"Erro no webhook MP: {e}")
        return jsonify({"ok": True}), 200  # Sempre retorna 200 pro MP não reenviar


# ──────────────────────────────────────────────
#  PRODUTOS
# ──────────────────────────────────────────────

@app.route('/api/products', methods=['GET'])
@require_guild
def api_get_products(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        res = supabase.table("products").select("*").eq("guild_id", guild_id).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "products": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/products', methods=['POST'])
@limiter.limit("30 per minute")
@require_guild
def api_create_product(guild_id, session):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        product = {
            "guild_id": guild_id,
            "name": data.get("name", "").strip(),
            "category": data.get("category", "Digital"),
            "price": float(data.get("price", 0)),
            "stock": str(data.get("stock", "∞")),
            "status": data.get("status", "Ativo"),
            "description": data.get("description", ""),
            "delivery_content": data.get("delivery_content", ""),
        }
        if not product["name"]:
            return jsonify({"ok": False, "error": "Nome obrigatório"}), 400
        res = supabase.table("products").insert(product).execute()
        log_event(guild_id, "produto_criado", f"Produto '{product['name']}' criado (R$ {product['price']:.2f})")
        return jsonify({"ok": True, "product": res.data[0] if res.data else product})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@limiter.limit("30 per minute")
@require_guild
def api_update_product(guild_id, session, product_id):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        update = {}
        for field in ['name', 'category', 'price', 'stock', 'status', 'description', 'delivery_content']:
            if field in data:
                update[field] = data[field]
        res = supabase.table("products").update(update).eq("id", product_id).eq("guild_id", guild_id).execute()
        return jsonify({"ok": True, "product": res.data[0] if res.data else {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@limiter.limit("30 per minute")
@require_guild
def api_delete_product(guild_id, session, product_id):
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        prod = supabase.table("products").select("name").eq("id", product_id).eq("guild_id", guild_id).execute()
        nome = prod.data[0]["name"] if prod.data else f"#{product_id}"
        supabase.table("products").delete().eq("id", product_id).eq("guild_id", guild_id).execute()
        log_event(guild_id, "produto_deletado", f"Produto '{nome}' deletado")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  PEDIDOS
# ──────────────────────────────────────────────

@app.route('/api/orders', methods=['GET'])
@require_guild
def api_get_orders(guild_id, session):
    status_filter = request.args.get("status")
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        query = supabase.table("orders").select(
            "*, products(name, category)"
        ).eq("guild_id", guild_id).order("created_at", desc=True)
        if status_filter and status_filter != "todos":
            query = query.eq("status", status_filter.capitalize())
        res = query.execute()
        return jsonify({"ok": True, "orders": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
@limiter.limit("30 per minute")
@require_guild
def api_update_order_status(guild_id, session, order_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if not new_status or not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        supabase.table("orders").update({"status": new_status}).eq("id", order_id).eq("guild_id", guild_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  CLIENTES
# ──────────────────────────────────────────────

@app.route('/api/clients', methods=['GET'])
@require_guild
def api_get_clients(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        res = supabase.table("orders").select(
            "customer_id, customer_name, amount, created_at, status"
        ).eq("guild_id", guild_id).eq("status", "Pago").execute()

        clients_map = {}
        for order in (res.data or []):
            cid = order.get("customer_id") or order.get("customer_name", "Desconhecido")
            if cid not in clients_map:
                clients_map[cid] = {
                    "id": cid,
                    "name": order.get("customer_name", "Desconhecido"),
                    "total_spent": 0,
                    "purchase_count": 0,
                    "last_purchase": order.get("created_at", "")
                }
            clients_map[cid]["total_spent"] += float(order.get("amount") or 0)
            clients_map[cid]["purchase_count"] += 1
            if order.get("created_at", "") > clients_map[cid]["last_purchase"]:
                clients_map[cid]["last_purchase"] = order.get("created_at", "")

        clients = sorted(clients_map.values(), key=lambda c: c["total_spent"], reverse=True)
        return jsonify({"ok": True, "clients": clients})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/clients/<client_id>/orders', methods=['GET'])
@require_guild
def api_client_orders(guild_id, session, client_id):
    if not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        res = supabase.table("orders").select(
            "*, products(name)"
        ).eq("guild_id", guild_id).eq("customer_id", client_id).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "orders": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  LOGS
# ──────────────────────────────────────────────

@app.route('/api/logs', methods=['GET'])
@require_guild
def api_get_logs(guild_id, session):
    event_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 100)), 500)
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        query = supabase.table("activity_logs").select("*").eq("guild_id", guild_id).order("created_at", desc=True).limit(limit)
        if event_type and event_type != "todos":
            query = query.eq("event_type", event_type)
        res = query.execute()
        return jsonify({"ok": True, "logs": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  DASHBOARD — STATS E GRÁFICO
# ──────────────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
@require_guild
def api_get_stats(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        now = datetime.datetime.utcnow()
        week_ago    = (now - datetime.timedelta(days=7)).isoformat()
        month_ago   = (now - datetime.timedelta(days=30)).isoformat()
        month_start = now.replace(day=1).isoformat()

        orders_res = supabase.table("orders").select(
            "amount, status, created_at"
        ).eq("guild_id", guild_id).eq("status", "Pago").execute()
        all_paid = orders_res.data or []

        def sum_since(rows, since_iso):
            return sum(float(r["amount"] or 0) for r in rows if r["created_at"] >= since_iso)

        today_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        stats = {
            "vendas_hoje":  sum_since(all_paid, today_iso),
            "vendas_semana": sum_since(all_paid, week_ago),
            "vendas_mes":   sum_since(all_paid, month_start),
            "faturamento_total": sum(float(r["amount"] or 0) for r in all_paid),
        }

        prod_res = supabase.table("products").select("id", count="exact").eq("guild_id", guild_id).eq("status", "Ativo").execute()
        stats["produtos_ativos"] = prod_res.count or 0

        clients_res = supabase.table("orders").select("customer_id").eq("guild_id", guild_id).eq("status", "Pago").execute()
        stats["clientes"] = len(set(r["customer_id"] for r in (clients_res.data or []) if r.get("customer_id")))

        try:
            tickets_res = supabase.table("tickets").select("id", count="exact").eq("guild_id", guild_id).eq("status", "Aberto").execute()
            stats["tickets_abertos"] = tickets_res.count or 0
        except Exception:
            stats["tickets_abertos"] = 0

        total_orders_res = supabase.table("orders").select("id", count="exact").eq("guild_id", guild_id).execute()
        total = total_orders_res.count or 1
        stats["taxa_conversao"] = round((len(all_paid) / total) * 100, 2)

        chart_data = {}
        for r in all_paid:
            day = r["created_at"][:10]
            if day >= month_ago[:10]:
                chart_data[day] = chart_data.get(day, 0) + float(r["amount"] or 0)

        chart_points = []
        for i in range(30):
            day = (now - datetime.timedelta(days=29 - i)).strftime("%Y-%m-%d")
            chart_points.append({"date": day, "value": round(chart_data.get(day, 0), 2)})

        orders_with_prod = supabase.table("orders").select(
            "product_id, amount, products(name)"
        ).eq("guild_id", guild_id).eq("status", "Pago").execute()

        prod_sales = {}
        for r in (orders_with_prod.data or []):
            pid = r.get("product_id")
            if not pid:
                continue
            name = (r.get("products") or {}).get("name", f"Produto #{pid}")
            if pid not in prod_sales:
                prod_sales[pid] = {"name": name, "count": 0, "revenue": 0}
            prod_sales[pid]["count"] += 1
            prod_sales[pid]["revenue"] += float(r.get("amount") or 0)

        top_products = sorted(prod_sales.values(), key=lambda x: x["count"], reverse=True)[:5]

        return jsonify({
            "ok": True,
            "stats": stats,
            "chart": chart_points,
            "top_products": top_products
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  CUPONS
# ──────────────────────────────────────────────

@app.route('/api/coupons', methods=['GET'])
@require_guild
def api_get_coupons(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "coupons": []}), 400
    try:
        res = supabase.table("coupons").select("*").eq("guild_id", guild_id).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "coupons": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/coupons', methods=['POST'])
@limiter.limit("20 per minute")
@require_guild
def api_create_coupon(guild_id, session):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        coupon = {
            "guild_id": guild_id,
            "code": data.get("code", "").upper().strip(),
            "discount_percent": int(data.get("discount_percent") if data.get("discount_percent") is not None else 10),
            "max_uses": int(data.get("max_uses") if data.get("max_uses") is not None else 100),
            "uses": 0,
            "expires_at": data.get("expires_at"),
        }
        if not coupon["code"]:
            return jsonify({"ok": False, "error": "Código obrigatório"}), 400
        res = supabase.table("coupons").insert(coupon).execute()
        return jsonify({"ok": True, "coupon": res.data[0] if res.data else coupon})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/coupons/<int:coupon_id>', methods=['DELETE'])
@limiter.limit("20 per minute")
@require_guild
def api_delete_coupon(guild_id, session, coupon_id):
    if not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        supabase.table("coupons").delete().eq("id", coupon_id).eq("guild_id", guild_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  AFILIADOS
# ──────────────────────────────────────────────

@app.route('/api/affiliates', methods=['GET'])
@require_guild
def api_get_affiliates(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "affiliates": []}), 400
    try:
        res = supabase.table("affiliates").select("*").eq("guild_id", guild_id).order("earnings", desc=True).execute()
        return jsonify({"ok": True, "affiliates": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/affiliates', methods=['POST'])
@limiter.limit("20 per minute")
@require_guild
def api_create_affiliate(guild_id, session):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        affiliate = {
            "guild_id": guild_id,
            "name": data.get("name", "").strip(),
            "code": data.get("code", "").upper().strip(),
            "commission_percent": int(data.get("commission_percent", 15)),
            "clicks": 0,
            "conversions": 0,
            "earnings": 0
        }
        if not affiliate["name"] or not affiliate["code"]:
            return jsonify({"ok": False, "error": "Nome e código são obrigatórios"}), 400
        res = supabase.table("affiliates").insert(affiliate).execute()
        log_event(guild_id, "afiliado_criado", f"Afiliado '{affiliate['name']}' cadastrado com código {affiliate['code']}")
        return jsonify({"ok": True, "affiliate": res.data[0] if res.data else affiliate})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  TICKETS
# ──────────────────────────────────────────────

@app.route('/api/tickets', methods=['GET'])
@require_guild
def api_get_tickets(guild_id, session):
    if not supabase:
        return jsonify({"ok": False, "tickets": []}), 400
    try:
        res = supabase.table("tickets").select("*").eq("guild_id", guild_id).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "tickets": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/tickets', methods=['POST'])
@limiter.limit("20 per minute")
@require_guild
def api_create_ticket(guild_id, session):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        ticket = {
            "guild_id": guild_id,
            "customer_id": data.get("customer_id", ""),
            "customer_name": data.get("customer_name", ""),
            "subject": data.get("subject", "").strip(),
            "status": "Aberto"
        }
        if not ticket["subject"]:
            return jsonify({"ok": False, "error": "Assunto obrigatório"}), 400
        res = supabase.table("tickets").insert(ticket).execute()
        log_event(guild_id, "ticket", f"Ticket criado por {ticket['customer_name']}: {ticket['subject']}")
        return jsonify({"ok": True, "ticket": res.data[0] if res.data else ticket})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/tickets/<int:ticket_id>/close', methods=['PATCH'])
@limiter.limit("20 per minute")
@require_guild
def api_close_ticket(guild_id, session, ticket_id):
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        supabase.table("tickets").update({
            "status": "Fechado",
            "closed_at": datetime.datetime.utcnow().isoformat()
        }).eq("id", ticket_id).eq("guild_id", guild_id).execute()
        log_event(guild_id, "ticket", f"Ticket #{ticket_id} fechado")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  AUTOMAÇÕES
# ──────────────────────────────────────────────

@app.route('/api/automations', methods=['GET'])
@require_guild
def api_get_automations(guild_id, session):
    try:
        automations = get_active_automations(guild_id)
        return jsonify({"ok": True, "automations": automations})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/automations', methods=['POST'])
@limiter.limit("20 per minute")
@require_guild
def api_set_automations(guild_id, session):
    data = request.get_json(silent=True) or {}
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        automations = data.get("automations", {})
        supabase.table("guild_settings").upsert({
            "guild_id": guild_id,
            "automations": json.dumps(automations) if isinstance(automations, dict) else str(automations)
        }).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def run_web():
    port = int(os.getenv("PORT", "8080"))
    print(f"🌐 Iniciando servidor web (dev) na porta {port}...")
    app.run(host='0.0.0.0', port=port)


def start_discord_bot():
    if DISCORD_BOT_TOKEN:
        try:
            print("🤖 Iniciando Bot do Discord...")
            bot.run(DISCORD_BOT_TOKEN)
        except Exception as e:
            print(f"❌ Erro fatal ao iniciar o bot: {e}")
    else:
        print("❌ DISCORD_BOT_TOKEN não encontrado. Bot não será iniciado.")


# O bot do Discord roda numa thread separada e é iniciado quando este
# módulo é importado — isso cobre tanto `python bot.py` localmente
# quanto produção via gunicorn (Procfile: `backend.bot:app`), onde só
# o objeto `app` é importado e nenhum código do bloco abaixo roda.
#
# ATENÇÃO: por causa disso, em produção use SEMPRE 1 worker do gunicorn
# (ver Procfile). Múltiplos workers abririam múltiplas conexões do
# mesmo bot ao gateway do Discord, o que quebra a sessão. Quando o
# projeto crescer, o caminho certo é separar bot e API em processos
# diferentes (ver SCALING.md) em vez de aumentar workers aqui.
_bot_thread = Thread(target=start_discord_bot, daemon=True)
_bot_thread.start()

if __name__ == "__main__":
    run_web()
