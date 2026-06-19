-- Tabela de Configurações por Servidor
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id TEXT PRIMARY KEY,
    pix_key TEXT,
    mp_access_token TEXT,
    mp_pix_key TEXT,
    payment_method_active TEXT DEFAULT 'mercadopago',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Produtos
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    guild_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    price DECIMAL(10,2) NOT NULL,
    stock TEXT DEFAULT '∞',
    status TEXT DEFAULT 'Ativo',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Pedidos
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    guild_id TEXT NOT NULL,
    order_reference TEXT UNIQUE,
    customer_id TEXT,
    customer_name TEXT,
    product_id INTEGER REFERENCES products(id),
    amount DECIMAL(10,2),
    status TEXT DEFAULT 'Pendente',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Logs
CREATE TABLE IF NOT EXISTS activity_logs (
    id SERIAL PRIMARY KEY,
    guild_id TEXT NOT NULL,
    event_type TEXT,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
