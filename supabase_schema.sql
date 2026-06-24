-- ============================================================
--  VENDABOT — SCHEMA COMPLETO DO SUPABASE
--  Atualizado: 2026-06-24
-- ============================================================

-- Tabela: guild_settings
-- Configurações por servidor do Discord
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id             TEXT PRIMARY KEY,
    payment_method_active TEXT DEFAULT 'mercadopago',
    pix_key              TEXT DEFAULT '',
    mp_access_token      TEXT DEFAULT '',
    mp_pix_key           TEXT DEFAULT '',
    canal_compras        TEXT DEFAULT '',
    canal_logs           TEXT DEFAULT '',
    canal_tickets        TEXT DEFAULT '',
    automations          JSONB DEFAULT '{"mensagens_automaticas": true, "cargos_automaticos": true, "respostas_automaticas": false, "logs_automaticos": true, "entrega_automatica": true}'::jsonb,
    created_at           TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabela: products
-- Produtos cadastrados por servidor
CREATE TABLE IF NOT EXISTS products (
    id               SERIAL PRIMARY KEY,
    guild_id         TEXT NOT NULL,
    name             TEXT NOT NULL,
    category         TEXT DEFAULT 'Digital',
    price            DECIMAL(10,2) NOT NULL,
    stock            TEXT DEFAULT '∞',
    status           TEXT DEFAULT 'Ativo',
    description      TEXT DEFAULT '',
    delivery_content TEXT DEFAULT '',
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_products_guild ON products(guild_id);
CREATE INDEX idx_products_status ON products(status);

-- Tabela: orders
-- Pedidos de compra
CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    guild_id        TEXT NOT NULL,
    order_reference TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    customer_name   TEXT DEFAULT '',
    product_id      INTEGER REFERENCES products(id) ON DELETE SET NULL,
    amount          DECIMAL(10,2) NOT NULL DEFAULT 0,
    status          TEXT DEFAULT 'Pendente',
    payment_id      TEXT DEFAULT '',
    coupon_code     TEXT DEFAULT '',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_orders_guild ON orders(guild_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_reference ON orders(order_reference);

-- Tabela: activity_logs
-- Logs de atividades do sistema
CREATE TABLE IF NOT EXISTS activity_logs (
    id          SERIAL PRIMARY KEY,
    guild_id    TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    description TEXT DEFAULT '',
    "user"      TEXT DEFAULT 'Sistema',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_logs_guild ON activity_logs(guild_id);
CREATE INDEX idx_logs_type ON activity_logs(event_type);
CREATE INDEX idx_logs_created ON activity_logs(created_at DESC);

-- Tabela: clients
-- Base de clientes (view materializada dos compradores)
CREATE TABLE IF NOT EXISTS clients (
    id            TEXT PRIMARY KEY,
    guild_id      TEXT NOT NULL,
    name          TEXT DEFAULT 'Desconhecido',
    total_spent   DECIMAL(10,2) DEFAULT 0,
    purchase_count INTEGER DEFAULT 0,
    last_purchase TIMESTAMP WITH TIME ZONE,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_clients_guild ON clients(guild_id);

-- Tabela: tickets
-- Sistema de suporte/tickets
CREATE TABLE IF NOT EXISTS tickets (
    id          SERIAL PRIMARY KEY,
    guild_id    TEXT NOT NULL,
    customer_id TEXT DEFAULT '',
    customer_name TEXT DEFAULT '',
    subject     TEXT NOT NULL,
    status      TEXT DEFAULT 'Aberto',
    assignee    TEXT DEFAULT '',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at   TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_tickets_guild ON tickets(guild_id);
CREATE INDEX idx_tickets_status ON tickets(status);

-- Tabela: coupons
-- Cupons de desconto
CREATE TABLE IF NOT EXISTS coupons (
    id               SERIAL PRIMARY KEY,
    guild_id         TEXT NOT NULL,
    code             TEXT NOT NULL,
    discount_percent INTEGER NOT NULL DEFAULT 10,
    max_uses         INTEGER,
    uses             INTEGER DEFAULT 0,
    expires_at       TIMESTAMP WITH TIME ZONE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_coupons_guild ON coupons(guild_id);
CREATE INDEX idx_coupons_code ON coupons(code);

-- Tabela: affiliates
-- Programa de afiliação
CREATE TABLE IF NOT EXISTS affiliates (
    id                SERIAL PRIMARY KEY,
    guild_id          TEXT NOT NULL,
    name              TEXT NOT NULL,
    code              TEXT NOT NULL,
    commission_percent INTEGER DEFAULT 15,
    clicks            INTEGER DEFAULT 0,
    conversions       INTEGER DEFAULT 0,
    earnings          DECIMAL(10,2) DEFAULT 0,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_affiliates_guild ON affiliates(guild_id);
CREATE INDEX idx_affiliates_code ON affiliates(code);

-- ============================================================
--  ROW LEVEL SECURITY (RLS) — Habilitar se necessário
-- ============================================================
-- Para habilitar RLS nas tabelas, descomente as linhas abaixo:
-- ALTER TABLE guild_settings ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE products ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE activity_logs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE coupons ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE affiliates ENABLE ROW LEVEL SECURITY;
