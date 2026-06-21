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
        "mp_access_token": ""
    }
    if not supabase:
        return default_settings
    try:
        response = supabase.table("guild_settings").select("*").eq("guild_id", str(guild_id)).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            supabase.table("guild_settings").insert(default_settings).execute()
            return default_settings
    except Exception as e:
        print(f"❌ Erro ao ler settings: {e}")
        return default_settings


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
    # CORS restrito à origem do painel + cookies habilitados.
    # "*" foi removido de propósito: com cookie de sessão, permitir
    # qualquer origem equivaleria a permitir qualquer site logado
    # como o usuário a chamar a API em nome dele.
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
            continue  # nunca expor servidores que o usuário logado não administra
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
                      'canal_compras', 'canal_logs', 'canal_tickets']:
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
        try:
            supabase.table("activity_logs").insert({
                "guild_id": guild_id,
                "event_type": "produto_criado",
                "description": f"Produto '{product['name']}' criado (R$ {product['price']:.2f})"
            }).execute()
        except Exception:
            pass
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
        try:
            supabase.table("activity_logs").insert({
                "guild_id": guild_id,
                "event_type": "produto_deletado",
                "description": f"Produto '{nome}' deletado"
            }).execute()
        except Exception:
            pass
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
    limit = min(int(request.args.get("limit", 100)), 500)  # evita pedir limites absurdos
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
            "discount_percent": int(data.get("discount_percent", 10)),
            "max_uses": int(data.get("max_uses", 100)),
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
