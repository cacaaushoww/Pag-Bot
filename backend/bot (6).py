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

def require_guild(f):
    """Decorator: extrai guild_id do request (GET param ou JSON body)."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        guild_id = request.args.get("guild_id") or (request.get_json(silent=True) or {}).get("guild_id")
        if not guild_id:
            return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
        return f(guild_id, *args, **kwargs)
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
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        update_data = {}
        for field in ['pix_key', 'mp_access_token', 'mp_pix_key', 'payment_method_active',
                      'canal_compras', 'canal_logs', 'canal_tickets']:
            if field in data:
                update_data[field] = data[field]
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
        if response.data:
            return jsonify({"ok": True, "active": response.data[0].get("payment_method_active", "mercadopago")})
        return jsonify({"ok": False, "active": "mercadopago"})
    except Exception as e:
        return jsonify({"ok": False, "active": "mercadopago", "error": str(e)})

# ──────────────────────────────────────────────
#  PRODUTOS
# ──────────────────────────────────────────────

@app.route('/api/products', methods=['GET'])
def api_get_products():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        res = supabase.table("products").select("*").eq("guild_id", str(guild_id)).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "products": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/products', methods=['POST'])
def api_create_product():
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        product = {
            "guild_id": str(guild_id),
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
        # Log
        try:
            supabase.table("activity_logs").insert({
                "guild_id": str(guild_id),
                "event_type": "produto_criado",
                "description": f"Produto '{product['name']}' criado (R$ {product['price']:.2f})"
            }).execute()
        except:
            pass
        return jsonify({"ok": True, "product": res.data[0] if res.data else product})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
def api_update_product(product_id):
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "error": "guild_id ou Supabase faltando"}), 400
    try:
        update = {}
        for field in ['name', 'category', 'price', 'stock', 'status', 'description', 'delivery_content']:
            if field in data:
                update[field] = data[field]
        res = supabase.table("products").update(update).eq("id", product_id).eq("guild_id", str(guild_id)).execute()
        return jsonify({"ok": True, "product": res.data[0] if res.data else {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def api_delete_product(product_id):
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "error": "guild_id ou Supabase faltando"}), 400
    try:
        # Busca nome para o log
        prod = supabase.table("products").select("name").eq("id", product_id).execute()
        nome = prod.data[0]["name"] if prod.data else f"#{product_id}"
        supabase.table("products").delete().eq("id", product_id).eq("guild_id", str(guild_id)).execute()
        try:
            supabase.table("activity_logs").insert({
                "guild_id": str(guild_id),
                "event_type": "produto_deletado",
                "description": f"Produto '{nome}' deletado"
            }).execute()
        except:
            pass
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  PEDIDOS
# ──────────────────────────────────────────────

@app.route('/api/orders', methods=['GET'])
def api_get_orders():
    guild_id = request.args.get("guild_id")
    status_filter = request.args.get("status")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        query = supabase.table("orders").select(
            "*, products(name, category)"
        ).eq("guild_id", str(guild_id)).order("created_at", desc=True)
        if status_filter and status_filter != "todos":
            query = query.eq("status", status_filter.capitalize())
        res = query.execute()
        return jsonify({"ok": True, "orders": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
def api_update_order_status(order_id):
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    new_status = data.get("status")
    if not guild_id or not new_status or not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        supabase.table("orders").update({"status": new_status}).eq("id", order_id).eq("guild_id", str(guild_id)).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  CLIENTES
# ──────────────────────────────────────────────

@app.route('/api/clients', methods=['GET'])
def api_get_clients():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        # Agrupa pedidos pagos por customer_id para montar os clientes
        res = supabase.table("orders").select(
            "customer_id, customer_name, amount, created_at, status"
        ).eq("guild_id", str(guild_id)).eq("status", "Pago").execute()

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
def api_client_orders(client_id):
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        res = supabase.table("orders").select(
            "*, products(name)"
        ).eq("guild_id", str(guild_id)).eq("customer_id", client_id).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "orders": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  LOGS
# ──────────────────────────────────────────────

@app.route('/api/logs', methods=['GET'])
def api_get_logs():
    guild_id = request.args.get("guild_id")
    event_type = request.args.get("type")
    limit = int(request.args.get("limit", 100))
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        query = supabase.table("activity_logs").select("*").eq("guild_id", str(guild_id)).order("created_at", desc=True).limit(limit)
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
def api_get_stats():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        return jsonify({"ok": False, "error": "guild_id obrigatório"}), 400
    if not supabase:
        return jsonify({"ok": False, "error": "Supabase não configurado"}), 500
    try:
        now = datetime.datetime.utcnow()
        today_str   = now.strftime("%Y-%m-%d")
        week_ago    = (now - datetime.timedelta(days=7)).isoformat()
        month_ago   = (now - datetime.timedelta(days=30)).isoformat()
        month_start = now.replace(day=1).isoformat()

        orders_res = supabase.table("orders").select(
            "amount, status, created_at"
        ).eq("guild_id", str(guild_id)).eq("status", "Pago").execute()
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

        # Produtos
        prod_res = supabase.table("products").select("id", count="exact").eq("guild_id", str(guild_id)).eq("status", "Ativo").execute()
        stats["produtos_ativos"] = prod_res.count or 0

        # Clientes únicos
        clients_res = supabase.table("orders").select("customer_id").eq("guild_id", str(guild_id)).eq("status", "Pago").execute()
        stats["clientes"] = len(set(r["customer_id"] for r in (clients_res.data or []) if r.get("customer_id")))

        # Tickets abertos
        try:
            tickets_res = supabase.table("tickets").select("id", count="exact").eq("guild_id", str(guild_id)).eq("status", "Aberto").execute()
            stats["tickets_abertos"] = tickets_res.count or 0
        except:
            stats["tickets_abertos"] = 0

        # Pedidos totais (para taxa de conversão fake baseada em real)
        total_orders_res = supabase.table("orders").select("id", count="exact").eq("guild_id", str(guild_id)).execute()
        total = total_orders_res.count or 1
        stats["taxa_conversao"] = round((len(all_paid) / total) * 100, 2)

        # Gráfico: vendas por dia nos últimos 30 dias
        chart_data = {}
        for r in all_paid:
            day = r["created_at"][:10]
            if day >= month_ago[:10]:
                chart_data[day] = chart_data.get(day, 0) + float(r["amount"] or 0)

        # Preenche dias sem venda com 0
        chart_points = []
        for i in range(30):
            day = (now - datetime.timedelta(days=29 - i)).strftime("%Y-%m-%d")
            chart_points.append({"date": day, "value": round(chart_data.get(day, 0), 2)})

        # Top produtos
        orders_with_prod = supabase.table("orders").select(
            "product_id, amount, products(name)"
        ).eq("guild_id", str(guild_id)).eq("status", "Pago").execute()

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
def api_get_coupons():
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "coupons": []}), 400
    try:
        res = supabase.table("coupons").select("*").eq("guild_id", str(guild_id)).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "coupons": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/coupons', methods=['POST'])
def api_create_coupon():
    data = request.get_json(silent=True) or {}
    guild_id = data.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        coupon = {
            "guild_id": str(guild_id),
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
def api_delete_coupon(coupon_id):
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "error": "Dados faltando"}), 400
    try:
        supabase.table("coupons").delete().eq("id", coupon_id).eq("guild_id", str(guild_id)).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  AFILIADOS
# ──────────────────────────────────────────────

@app.route('/api/affiliates', methods=['GET'])
def api_get_affiliates():
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "affiliates": []}), 400
    try:
        res = supabase.table("affiliates").select("*").eq("guild_id", str(guild_id)).order("earnings", desc=True).execute()
        return jsonify({"ok": True, "affiliates": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
#  TICKETS
# ──────────────────────────────────────────────

@app.route('/api/tickets', methods=['GET'])
def api_get_tickets():
    guild_id = request.args.get("guild_id")
    if not guild_id or not supabase:
        return jsonify({"ok": False, "tickets": []}), 400
    try:
        res = supabase.table("tickets").select("*").eq("guild_id", str(guild_id)).order("created_at", desc=True).execute()
        return jsonify({"ok": True, "tickets": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

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
        print("❌ DISCORD_BOT_TOKEN não encontrado.")
        while True:
            asyncio.run(asyncio.sleep(3600))
