/* ===========================
   BLOQUEIO DE ZOOM
   =========================== */

document.addEventListener('touchmove', function(event) {
    if (event.touches.length > 1) event.preventDefault();
}, { passive: false });

let lastTouchEnd = 0;
document.addEventListener('touchend', function(event) {
    const now = Date.now();
    if (now - lastTouchEnd <= 300) event.preventDefault();
    lastTouchEnd = now;
}, false);

document.addEventListener('keydown', function(event) {
    if ((event.ctrlKey || event.metaKey) && (event.key === '+' || event.key === '-' || event.key === '0'))
        event.preventDefault();
});

document.addEventListener('wheel', function(event) {
    if (event.ctrlKey || event.metaKey) event.preventDefault();
}, { passive: false });

/* ===========================
   INTEGRAÇÃO COM O BOT (API REAL)
   =========================== */

const BOT_API_URL = "https://pag-bot.onrender.com";

async function loadServerInfo() {
    const nameEl      = document.getElementById('serverName');
    const statusEl    = document.getElementById('botStatus');
    const indicator   = document.getElementById('onlineIndicator');
    const avatarImg   = document.getElementById('serverAvatarImg');
    const avatarSvg   = document.getElementById('serverAvatarSvg');
    try {
        const res  = await fetch(`${BOT_API_URL}/api/server-info`);
        const data = await res.json();
        if (data.online && data.servers && data.servers.length > 0) {
            const server = data.servers[0];
            if (nameEl)    nameEl.textContent    = server.name;
            if (statusEl)  statusEl.textContent  = "Bot Online";
            if (indicator) indicator.style.background = "#3ba55d";
            if (server.icon && avatarImg && avatarSvg) {
                avatarImg.src          = server.icon;
                avatarImg.style.display = "block";
                avatarSvg.style.display = "none";
            }
        } else {
            if (nameEl)    nameEl.textContent    = "Bot sem servidor";
            if (statusEl)  statusEl.textContent  = "Bot Offline";
            if (indicator) indicator.style.background = "#ed4245";
        }
    } catch (err) {
        console.log("[v0] Erro ao buscar server-info:", err.message);
        if (nameEl)    nameEl.textContent    = "Bot Offline";
        if (statusEl)  statusEl.textContent  = "Sem conexão";
        if (indicator) indicator.style.background = "#ed4245";
    }
}

async function loadChannels() {
    const selects = [
        document.getElementById('channelCompras'),
        document.getElementById('channelLogs'),
        document.getElementById('channelTickets')
    ].filter(Boolean);
    if (selects.length === 0) return;
    try {
        const res  = await fetch(`${BOT_API_URL}/api/channels`);
        const data = await res.json();
        if (data.online && data.channels && data.channels.length > 0) {
            const savedSettings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
            selects.forEach(select => {
                const settingKey = select.dataset.setting;
                select.innerHTML = '<option value="">Selecione um canal...</option>' +
                    data.channels.map(c => `<option value="${c.id}">#${c.name}</option>`).join('');
                if (savedSettings[settingKey]) select.value = savedSettings[settingKey];
            });
        } else {
            selects.forEach(s => { s.innerHTML = '<option value="">Bot offline - sem canais</option>'; });
        }
    } catch (err) {
        console.log("[v0] Erro ao buscar canais:", err.message);
        selects.forEach(s => { s.innerHTML = '<option value="">Sem conexão com o bot</option>'; });
    }
}

async function loadBotName() {
    const input = document.getElementById('botNameInput');
    if (!input) return;
    try {
        const res  = await fetch(`${BOT_API_URL}/api/bot-name`);
        const data = await res.json();
        if (data.online && data.name) {
            input.value          = data.name;
            input.dataset.original = data.name;
        } else {
            input.placeholder = "Bot offline";
        }
    } catch (err) {
        console.log("[v0] Erro ao buscar nome do bot:", err.message);
        input.placeholder = "Sem conexão com o bot";
    }
}

async function saveSettings() {
    const settings = {};
    document.querySelectorAll('[data-setting]').forEach(el => {
        settings[el.dataset.setting] = el.value;
    });
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));

    const input = document.getElementById('botNameInput');
    if (input) {
        const newName  = input.value.trim();
        const original = input.dataset.original || "";
        if (newName && newName !== original) {
            try {
                const res  = await fetch(`${BOT_API_URL}/api/bot-name`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });
                const data = await res.json();
                if (data.ok) {
                    input.dataset.original = newName;
                    showToast("Configurações salvas! Nome do bot atualizado no Discord.");
                    loadServerInfo();
                } else {
                    showToast("Configurações salvas, mas o nome não mudou: " + (data.error || "erro"));
                }
            } catch (err) {
                console.log("[v0] Erro ao trocar nome do bot:", err.message);
                showToast("Configurações salvas, mas falhou ao conectar com o bot.");
            }
            return;
        }
    }
    showToast("Configurações salvas!");
}

/* ===========================
   DETECÇÃO DE CHAVE PIX (lado cliente)
   =========================== */

function detectarTipoChavePix(chave) {
    chave = chave.trim();
    const digitos = chave.replace(/\D/g, '');

    // Chave aleatória (UUID)
    if (/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(chave))
        return 'aleatoria';
    // E-mail
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(chave))
        return 'email';
    // Telefone
    if (/^\+?55\s?\(?\d{2}\)?\s?\d{4,5}-?\d{4}$/.test(chave) ||
        /^\(?\d{2}\)?\s?\d{4,5}-?\d{4}$/.test(chave))
        return 'telefone';
    // CNPJ: 14 dígitos
    if (/^\d{2}\.?\d{3}\.?\d{3}\/?0001-?\d{2}$/.test(chave) || digitos.length === 14)
        return 'cnpj';
    // CPF: 11 dígitos
    if (/^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$/.test(chave) || digitos.length === 11)
        return 'cpf';

    return chave.length > 0 ? 'aleatoria' : null;
}

function formatarChavePix(chave) {
    chave = chave.trim();
    const tipo = detectarTipoChavePix(chave);
    const d    = chave.replace(/\D/g, '');

    if (tipo === 'cpf' && d.length === 11)
        return { tipo, label: 'CPF', exibicao: `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9)}` };

    if (tipo === 'cnpj' && d.length === 14)
        return { tipo, label: 'CNPJ', exibicao: `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12)}` };

    if (tipo === 'telefone') {
        const nums = d.startsWith('55') ? d.slice(2) : d;
        const fmt  = nums.length === 11
            ? `+55 (${nums.slice(0,2)}) ${nums.slice(2,7)}-${nums.slice(7)}`
            : `+55 (${nums.slice(0,2)}) ${nums.slice(2,6)}-${nums.slice(6)}`;
        return { tipo, label: 'Telefone', exibicao: fmt };
    }
    if (tipo === 'email')     return { tipo, label: 'E-mail',         exibicao: chave.toLowerCase() };
    if (tipo === 'aleatoria') return { tipo, label: 'Chave Aleatória', exibicao: chave.toLowerCase() };
    return { tipo: null, label: '', exibicao: chave };
}

const PIX_ICONS = {
    cpf:       '🪪',
    cnpj:      '🏢',
    telefone:  '📱',
    email:     '📧',
    aleatoria: '🔑',
};

/* ===========================
   CONFIGURAÇÃO DE PAGAMENTOS
   =========================== */

function abrirConfigPix() {
    const saved = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    showModal('Configurar PIX', `
        <div class="form-group">
            <label>Chave PIX</label>
            <input type="text" id="pixKeyInput"
                placeholder="CPF, CNPJ, e-mail, telefone ou chave aleatória"
                value="${saved.pix_key || ''}"
                autocomplete="off"
                oninput="atualizarPreviewChave(this.value)">
        </div>

        <div id="pixKeyPreview" style="
            display: none;
            align-items: center;
            gap: 12px;
            padding: 12px 14px;
            border-radius: 10px;
            background: rgba(88,101,242,0.08);
            border: 1px solid rgba(88,101,242,0.28);
            margin-bottom: 16px;
        ">
            <span id="pixKeyIcon" style="font-size:24px; line-height:1;"></span>
            <div style="display:flex; flex-direction:column; gap:3px;">
                <span id="pixKeyTipoLabel" style="
                    font-size:10px; font-weight:700; text-transform:uppercase;
                    letter-spacing:.7px; color:var(--text-secondary);
                "></span>
                <span id="pixKeyFormatada" style="
                    font-size:14px; font-weight:600; color:var(--text-primary);
                    font-family: monospace; letter-spacing:.3px;
                "></span>
            </div>
        </div>

        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:16px;">
            O nome do recebedor e a cidade usam valores padrão (VENDABOT / SAO PAULO).
        </p>
        <button class="btn btn-primary btn-large" onclick="salvarConfigPix()">Salvar</button>
    `);

    if (saved.pix_key) atualizarPreviewChave(saved.pix_key);
}

function atualizarPreviewChave(valor) {
    const preview = document.getElementById('pixKeyPreview');
    const icon    = document.getElementById('pixKeyIcon');
    const label   = document.getElementById('pixKeyTipoLabel');
    const fmt     = document.getElementById('pixKeyFormatada');
    if (!preview) return;

    const v = valor.trim();
    if (!v) { preview.style.display = 'none'; return; }

    const resultado = formatarChavePix(v);
    if (!resultado.tipo) { preview.style.display = 'none'; return; }

    icon.textContent  = PIX_ICONS[resultado.tipo] || '🔑';
    label.textContent = resultado.label;
    fmt.textContent   = resultado.exibicao;
    preview.style.display = 'flex';
}

async function salvarConfigPix() {
    const key = document.getElementById('pixKeyInput').value.trim();
    if (!key) { showToast('Insira uma chave PIX!'); return; }

    const settings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    settings.pix_key = key;
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));

    try {
        await fetch(`${BOT_API_URL}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pix_key: key })
        });
    } catch (e) {
        console.log("[v0] Bot offline, chave PIX salva apenas localmente.");
    }

    closeModal();
    showToast('Chave PIX salva!');
}

function abrirConfigMercadoPago() {
    const saved = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    showModal('Configurar Mercado Pago', `
        <div class="form-group">
            <label>Access Token</label>
            <input type="text" id="mpTokenInput" placeholder="APP_USR-..." value="${saved.mp_access_token || ''}">
        </div>
        <div class="form-group">
            <label>Chave PIX</label>
            <input type="text" id="mpPixKeyInput" placeholder="Chave PIX da conta Mercado Pago" value="${saved.mp_pix_key || ''}">
        </div>
        <div id="mpTesteResult" style="margin-bottom:16px;padding:12px;border-radius:8px;display:none;font-size:13px;"></div>
        <div style="display:flex;gap:8px;">
            <button class="btn btn-secondary" style="flex:1" onclick="testarTokenMP()">Testar conexão</button>
            <button class="btn btn-primary" style="flex:1" onclick="salvarConfigMercadoPago()">Salvar</button>
        </div>
    `);
}

async function testarTokenMP() {
    const token    = document.getElementById('mpTokenInput').value.trim();
    const resultEl = document.getElementById('mpTesteResult');
    if (!token) {
        resultEl.style.display    = 'block';
        resultEl.style.background = 'rgba(255,107,107,0.1)';
        resultEl.style.color      = 'var(--danger)';
        resultEl.textContent      = '❌ Insira o Access Token antes de testar.';
        return;
    }
    resultEl.style.display    = 'block';
    resultEl.style.background = 'rgba(181,186,193,0.1)';
    resultEl.style.color      = 'var(--text-secondary)';
    resultEl.textContent      = '⏳ Testando conexão...';
    try {
        const res  = await fetch('https://api.mercadopago.com/v1/account', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (res.ok && data.email) {
            resultEl.style.background = 'rgba(67,233,123,0.1)';
            resultEl.style.color      = 'var(--success)';
            resultEl.textContent      = `✅ Conectado — ${data.email}`;
        } else {
            resultEl.style.background = 'rgba(255,107,107,0.1)';
            resultEl.style.color      = 'var(--danger)';
            resultEl.textContent      = `❌ ${data.message || 'Token inválido ou sem permissão.'}`;
        }
    } catch (e) {
        resultEl.style.background = 'rgba(255,107,107,0.1)';
        resultEl.style.color      = 'var(--danger)';
        resultEl.textContent      = '❌ Erro ao conectar com o Mercado Pago.';
    }
}

async function salvarConfigMercadoPago() {
    const token  = document.getElementById('mpTokenInput').value.trim();
    const pixKey = document.getElementById('mpPixKeyInput').value.trim();
    if (!token) { showToast('Insira o Access Token!'); return; }

    const settings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    settings.mp_access_token = token;
    settings.mp_pix_key      = pixKey;
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));

    try {
        await fetch(`${BOT_API_URL}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mp_access_token: token, mp_pix_key: pixKey })
        });
    } catch (e) {
        console.log("[v0] Bot offline, configuração MP salva apenas localmente.");
    }

    closeModal();
    showToast('Mercado Pago configurado!');
}

/* ===========================
   MÉTODO DE PAGAMENTO ATIVO
   =========================== */

function aplicarEstiloMetodoAtivo(metodoAtivo) {
    const pixCard  = document.querySelector('.integration-card[data-method="pix"]');
    const mpCard   = document.querySelector('.integration-card[data-method="mercadopago"]');
    const pixStatus = document.getElementById('pixStatusLabel');
    const mpStatus  = document.getElementById('mpStatusLabel');

    if (pixCard) pixCard.classList.toggle('method-active', metodoAtivo === 'pix');
    if (mpCard)  mpCard.classList.toggle('method-active', metodoAtivo === 'mercadopago');
    if (pixStatus) pixStatus.textContent = metodoAtivo === 'pix'         ? 'Ativo no /criar_pix' : 'Conectado';
    if (mpStatus)  mpStatus.textContent  = metodoAtivo === 'mercadopago' ? 'Ativo no /criar_pix' : 'Conectado';
}

async function loadPaymentMethodActive() {
    const pixToggle = document.getElementById('pixMethodToggle');
    const mpToggle  = document.getElementById('mpMethodToggle');
    if (!pixToggle || !mpToggle) return;

    let metodoAtivo = 'mercadopago';
    try {
        const res  = await fetch(`${BOT_API_URL}/api/payment-method`);
        const data = await res.json();
        if (data.ok && data.active) metodoAtivo = data.active;
    } catch (e) {
        const saved = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
        metodoAtivo = saved.payment_method_active || 'mercadopago';
    }

    pixToggle.checked = (metodoAtivo === 'pix');
    mpToggle.checked  = (metodoAtivo === 'mercadopago');
    aplicarEstiloMetodoAtivo(metodoAtivo);
}

async function setPaymentMethodActive(metodo) {
    const pixToggle = document.getElementById('pixMethodToggle');
    const mpToggle  = document.getElementById('mpMethodToggle');
    pixToggle.checked = (metodo === 'pix');
    mpToggle.checked  = (metodo === 'mercadopago');
    aplicarEstiloMetodoAtivo(metodo);

    const settings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    settings.payment_method_active = metodo;
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));

    try {
        const res  = await fetch(`${BOT_API_URL}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payment_method_active: metodo })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(metodo === 'pix'
                ? 'PIX ativado! Mercado Pago foi desativado.'
                : 'Mercado Pago ativado! PIX foi desativado.');
        } else {
            showToast('Salvo localmente, mas o bot recusou: ' + (data.error || 'erro'));
        }
    } catch (e) {
        showToast('Bot offline: método salvo localmente.');
    }
}

function setupPaymentMethodToggles() {
    document.querySelectorAll('.payment-method-toggle').forEach(toggle => {
        toggle.addEventListener('change', (e) => {
            const metodo = e.target.dataset.method;
            if (e.target.checked) {
                setPaymentMethodActive(metodo);
            } else {
                setPaymentMethodActive(metodo === 'pix' ? 'mercadopago' : 'pix');
            }
        });
    });
}

/* ===========================
   BANCO DE DADOS (LOCAL STORAGE)
   =========================== */

let database = {
    products: [
        { id: 1, name: "Curso Premium",  category: "Educação", price: 99.90, stock: "∞", status: "Ativo" },
        { id: 2, name: "Ebook Completo", category: "Digital",  price: 49.90, stock: "∞", status: "Ativo" }
    ],
    orders: [], clients: [], coupons: [], logs: []
};

function loadDatabase() {
    const localData = localStorage.getItem('pagbot_db');
    if (localData) database = JSON.parse(localData);
    else saveDatabase();
    updateUI();
}

function saveDatabase() {
    localStorage.setItem('pagbot_db', JSON.stringify(database));
    updateUI();
}

/* ===========================
   ELEMENTOS DO DOM
   =========================== */

const menuToggle      = document.getElementById('menuToggle');
const sidebar         = document.getElementById('sidebar');
const navItems        = document.querySelectorAll('.nav-item');
const mobileMenuItems = document.querySelectorAll('.mobile-menu-item');
const pages           = document.querySelectorAll('.page');
const toast           = document.getElementById('toast');
const toastMessage    = document.getElementById('toastMessage');
const modal           = document.getElementById('modal');
const modalClose      = document.getElementById('modalClose');
const modalTitle      = document.getElementById('modalTitle');
const modalBody       = document.getElementById('modalBody');

/* ===========================
   NAVEGAÇÃO E UI
   =========================== */

function showPage(pageName) {
    pages.forEach(page => page.classList.remove('active'));
    const selectedPage = document.getElementById(`${pageName}-page`);
    if (selectedPage) selectedPage.classList.add('active');

    navItems.forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === pageName) item.classList.add('active');
    });
    mobileMenuItems.forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === pageName) item.classList.add('active');
    });

    if (window.innerWidth < 768) sidebar.classList.remove('active');
    document.querySelector('.main-content').scrollTop = 0;
}

menuToggle.addEventListener('click', () => sidebar.classList.toggle('active'));
navItems.forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); showPage(item.dataset.page); });
});
mobileMenuItems.forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); showPage(item.dataset.page); });
});

function updateUI() { renderProducts(); renderOrders(); renderStats(); }

function renderProducts() {
    const tbody = document.querySelector('#produtos-page .data-table tbody');
    if (!tbody) return;
    tbody.innerHTML = database.products.map(p => `
        <tr>
            <td><strong>${p.name}</strong></td>
            <td>${p.category}</td>
            <td>R$ ${p.price.toFixed(2)}</td>
            <td>${p.stock}</td>
            <td><span class="badge badge-success">${p.status}</span></td>
            <td><button class="action-btn" onclick="deleteProduct(${p.id})" title="Deletar">🗑</button></td>
        </tr>
    `).join('');
}

function renderOrders() {
    const tbody = document.querySelector('#pedidos-page .data-table tbody');
    if (!tbody) return;
    if (database.orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center">Nenhum pedido realizado ainda.</td></tr>';
        return;
    }
    tbody.innerHTML = database.orders.map(o => `
        <tr>
            <td>#${o.id}</td>
            <td>${o.client}</td>
            <td>${o.product}</td>
            <td>R$ ${o.amount.toFixed(2)}</td>
            <td>${o.date}</td>
            <td><span class="badge badge-success">${o.status}</span></td>
        </tr>
    `).join('');
}

function renderStats() {
    const totalSales   = database.orders.reduce((acc, o) => acc + o.amount, 0);
    const productCount = database.products.length;
    const clientCount  = database.clients.length;
    const values       = document.querySelectorAll('.stat-value');
    if (values.length >= 6) {
        values[3].textContent = `R$ ${totalSales.toFixed(2)}`;
        values[4].textContent = productCount;
        values[5].textContent = clientCount;
    }
}

/* ===========================
   AÇÕES
   =========================== */

function deleteProduct(id) {
    if (confirm('Tem certeza que deseja deletar este produto?')) {
        database.products = database.products.filter(p => p.id !== id);
        saveDatabase();
        showToast("Produto deletado!");
    }
}

document.addEventListener('submit', (e) => {
    if (e.target.classList.contains('modal-form')) {
        e.preventDefault();
        if (modalTitle.textContent === 'Adicionar Novo Produto') {
            const name     = e.target.querySelector('input[type="text"]').value;
            const category = e.target.querySelector('select').value;
            const price    = parseFloat(e.target.querySelector('input[type="number"]').value);
            const stock    = e.target.querySelectorAll('input[type="number"]')[1].value || "∞";
            database.products.push({ id: Date.now(), name, category, price, stock, status: "Ativo" });
            saveDatabase();
            closeModal();
            showToast("Produto adicionado com sucesso!");
        }
    }
});

/* ===========================
   MODAIS E TOASTS
   =========================== */

function showModal(title, content) {
    modalTitle.textContent = title;
    modalBody.innerHTML    = content;
    modal.classList.add('show');
}

function closeModal() { modal.classList.remove('show'); }
modalClose.addEventListener('click', closeModal);

function showToast(message) {
    toastMessage.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

const addProductBtn = document.getElementById('addProductBtn');
if (addProductBtn) {
    addProductBtn.addEventListener('click', () => {
        showModal('Adicionar Novo Produto', `
            <form class="modal-form">
                <div class="form-group"><label>Nome</label><input type="text" required></div>
                <div class="form-group"><label>Categoria</label>
                    <select><option>Digital</option><option>Serviço</option><option>Educação</option></select>
                </div>
                <div class="form-group"><label>Preço (R$)</label><input type="number" step="0.01" required></div>
                <div class="form-group"><label>Estoque</label><input type="number" placeholder="Vazio para ∞"></div>
                <button type="submit" class="btn btn-primary btn-large">Salvar</button>
            </form>
        `);
    });
}

/* ===========================
   BOTÕES DE CONFIGURAÇÃO DE PAGAMENTO
   =========================== */

document.addEventListener('click', (e) => {
    const card = e.target.closest('.integration-card');
    if (!card) return;
    const btn = e.target.closest('.btn');
    if (!btn || btn.textContent.trim() !== 'Configurar') return;
    const titulo = card.querySelector('h4').textContent.trim();
    if (titulo === 'PIX')          abrirConfigPix();
    if (titulo === 'Mercado Pago') abrirConfigMercadoPago();
});

/* ===========================
   INICIALIZAÇÃO
   =========================== */

loadDatabase();
showPage('dashboard');

loadServerInfo();
loadChannels();
loadBotName();
loadPaymentMethodActive();
setupPaymentMethodToggles();

setInterval(loadServerInfo, 60000);

const saveSettingsBtn = document.getElementById('saveSettingsBtn');
if (saveSettingsBtn) saveSettingsBtn.addEventListener('click', saveSettings);
