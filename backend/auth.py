"""
Autenticação via Discord OAuth2.

Fluxo:
  1. Front chama GET /api/auth/login -> backend redireciona pro Discord.
  2. Discord redireciona pro callback do backend com ?code=...
  3. Backend troca o code por access_token, busca o usuário e os
     servidores em que ele é admin/owner (MANAGE_GUILD).
  4. Backend cria um cookie de sessão assinado (JWT) contendo
     user_id + lista de guild_ids que o usuário pode administrar.
  5. Esse cookie é exigido em todas as rotas que recebem guild_id —
     se o guild_id pedido não estiver na lista, a API responde 403.

Sem isso, qualquer pessoa que descobrisse um guild_id (não é segredo,
aparece no próprio painel) conseguia ler/editar produtos, pedidos,
cupons e configurações de pagamento de qualquer servidor.
"""

import os
import datetime
from urllib.parse import urlencode

import jwt
import requests

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")  # ex: https://pag-bot.onrender.com/api/auth/callback
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

JWT_SECRET = os.getenv("JWT_SECRET")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))

DISCORD_API = "https://discord.com/api/v10"
MANAGE_GUILD_PERM = 0x20  # bit de permissão "Gerenciar Servidor"

if not JWT_SECRET:
    # Falha alto e cedo: sessão sem segredo forte é sessão falsificável.
    raise RuntimeError(
        "JWT_SECRET não configurado. Defina uma string longa e aleatória "
        "na variável de ambiente JWT_SECRET antes de iniciar o servidor."
    )


# ──────────────────────────────────────────────
#  OAUTH2 — DISCORD
# ──────────────────────────────────────────────

def build_authorize_url(state: str) -> str:
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "none",
    }
    return f"https://discord.com/oauth2/authorize?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(f"{DISCORD_API}/oauth2/token", data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_discord_user(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"{DISCORD_API}/users/@me", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_discord_user_guilds(access_token: str) -> list:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"{DISCORD_API}/users/@me/guilds", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def filter_manageable_guild_ids(guilds: list) -> list:
    """De todos os servidores do usuário no Discord, retorna só os ids
    onde ele é owner ou tem permissão de Gerenciar Servidor."""
    manageable = []
    for g in guilds:
        try:
            is_owner = bool(g.get("owner"))
            perms = int(g.get("permissions", 0))
            if is_owner or (perms & MANAGE_GUILD_PERM):
                manageable.append(str(g["id"]))
        except (TypeError, ValueError, KeyError):
            continue
    return manageable


# ──────────────────────────────────────────────
#  SESSÃO (JWT em cookie httponly)
# ──────────────────────────────────────────────

def create_session_token(user_id: str, username: str, guild_ids: list) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "guild_ids": guild_ids,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=SESSION_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_session_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
