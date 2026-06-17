/* ===========================
   BLOQUEIO DE ZOOM
   =========================== */

document.addEventListener('touchmove', function(event) {
    if (event.touches.length > 1) {
        event.preventDefault();
    }
}, { passive: false });

let lastTouchEnd = 0;
document.addEventListener('touchend', function(event) {
    const now = Date.now();
    if (now - lastTouchEnd <= 300) {
        event.preventDefault();
    }
    lastTouchEnd = now;
}, false);

document.addEventListener('keydown', function(event) {
    if ((event.ctrlKey || event.metaKey) && (event.key === '+' || event.key === '-' || event.key === '0')) {
        event.preventDefault();
    }
});

document.addEventListener('wheel', function(event) {
    if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
    }
}, { passive: false });

/* ===========================
   INTEGRAÇÃO COM O BOT (API REAL)
   =========================== */

// URL da API do bot hospedado no Render
const BOT_API_URL = "https://pag-bot.onrender.com";

// Carrega o nome/ícone do servidor real onde o bot está
async function loadServerInfo() {
    const nameEl = document.getElementById('serverName');
    const statusEl = document.getElementById('botStatus');
    const indicator = document.getElementById('onlineIndicator');
    const avatarImg = document.getElementById('serverAvatarImg');
    const avatarSvg = document.getElementById('serverAvatarSvg');

    try {
        const res = await fetch(`${BOT_API_URL}/api/server-info`);
        const data = await res.json();

        if (data.online && data.servers && data.servers.length > 0) {
            const server = data.servers[0];
            if (nameEl) nameEl.textContent = server.name;
            if (statusEl) statusEl.textContent = "Bot Online";
            if (indicator) indicator.style.background = "#3ba55d";

            // Mostra o ícone real do servidor, se houver
            if (server.icon && avatarImg && avatarSvg) {
                avatarImg.src = server.icon;
                avatarImg.style.display = "block";
                avatarSvg.style.display = "none";
            }
        } else {
            if (nameEl) nameEl.textContent = "Bot sem servidor";
            if (statusEl) statusEl.textContent = "Bot Offline";
            if (indicator) indicator.style.background = "#ed4245";
        }
    } catch (err) {
        console.log("[v0] Erro ao buscar server-info:", err.message);
        if (nameEl) nameEl.textContent = "Bot Offline";
        if (statusEl) statusEl.textContent = "Sem conexão";
        if (indicator) indicator.style.background = "#ed4245";
    }
}

// Carrega os canais reais do servidor e preenche os seletores de Configurações
async function loadChannels() {
    const selects = [
        document.getElementById('channelCompras'),
        document.getElementById('channelLogs'),
        document.getElementById('channelTickets')
    ].filter(Boolean);

    if (selects.length === 0) return;

    try {
        const res = await fetch(`${BOT_API_URL}/api/channels`);
        const data = await res.json();

        if (data.online && data.channels && data.channels.length > 0) {
            const savedSettings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');

            selects.forEach(select => {
                const settingKey = select.dataset.setting;
                select.innerHTML = '<option value="">Selecione um canal...</option>' +
                    data.channels.map(c =>
                        `<option value="${c.id}">#${c.name}</option>`
                    ).join('');

                // Restaura o canal salvo anteriormente
                if (savedSettings[settingKey]) {
                    select.value = savedSettings[settingKey];
                }
            });
        } else {
            selects.forEach(select => {
                select.innerHTML = '<option value="">Bot offline - sem canais</option>';
            });
        }
    } catch (err) {
        console.log("[v0] Erro ao buscar canais:", err.message);
        selects.forEach(select => {
            select.innerHTML = '<option value="">Sem conexão com o bot</option>';
        });
    }
}

// Carrega o nome atual do bot no campo de Configurações
async function loadBotName() {
    const input = document.getElementById('botNameInput');
    if (!input) return;

    try {
        const res = await fetch(`${BOT_API_URL}/api/bot-name`);
        const data = await res.json();
        if (data.online && data.name) {
            input.value = data.name;
            input.dataset.original = data.name;
        } else {
            input.placeholder = "Bot offline";
        }
    } catch (err) {
        console.log("[v0] Erro ao buscar nome do bot:", err.message);
        input.placeholder = "Sem conexão com o bot";
    }
}

// Salva as configurações: canais (local) e nome do bot (altera no Discord)
async function saveSettings() {
    const settings = {};
    document.querySelectorAll('[data-setting]').forEach(el => {
        settings[el.dataset.setting] = el.value;
    });
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));

    // Se o nome do bot mudou, envia para o bot trocar no Discord
    const input = document.getElementById('botNameInput');
    if (input) {
        const newName = input.value.trim();
        const original = input.dataset.original || "";
        if (newName && newName !== original) {
            try {
                const res = await fetch(`${BOT_API_URL}/api/bot-name`, {
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
   BANCO DE DADOS (LOCAL STORAGE)
   =========================== */

let database = {
    products: [
        { id: 1, name: "Curso Premium", category: "Educação", price: 99.90, stock: "∞", status: "Ativo" },
        { id: 2, name: "Ebook Completo", category: "Digital", price: 49.90, stock: "∞", status: "Ativo" }
    ],
    orders: [],
    clients: [],
    coupons: [],
    logs: []
};

function loadDatabase() {
    const localData = localStorage.getItem('pagbot_db');
    if (localData) {
        database = JSON.parse(localData);
    } else {
        saveDatabase();
    }
    updateUI();
}

function saveDatabase() {
    localStorage.setItem('pagbot_db', JSON.stringify(database));
    updateUI();
}

/* ===========================
   ELEMENTOS DO DOM
   =========================== */

const menuToggle = document.getElementById('menuToggle');
const sidebar = document.getElementById('sidebar');
const navItems = document.querySelectorAll('.nav-item');
const mobileMenuItems = document.querySelectorAll('.mobile-menu-item');
const pages = document.querySelectorAll('.page');
const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toastMessage');
const modal = document.getElementById('modal');
const modalClose = document.getElementById('modalClose');
const modalTitle = document.getElementById('modalTitle');
const modalBody = document.getElementById('modalBody');

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
    item.addEventListener('click', (e) => {
        e.preventDefault();
        showPage(item.dataset.page);
    });
});

mobileMenuItems.forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        showPage(item.dataset.page);
    });
});

function updateUI() {
    renderProducts();
    renderOrders();
    renderStats();
}

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
            <td>
                <button class="action-btn" onclick="deleteProduct(${p.id})" title="Deletar">🗑</button>
            </td>
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
    const totalSales = database.orders.reduce((acc, o) => acc + o.amount, 0);
    const productCount = database.products.length;
    const clientCount = database.clients.length;

    const values = document.querySelectorAll('.stat-value');
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
        const title = modalTitle.textContent;

        if (title === 'Adicionar Novo Produto') {
            const name = e.target.querySelector('input[type="text"]').value;
            const category = e.target.querySelector('select').value;
            const price = parseFloat(e.target.querySelector('input[type="number"]').value);
            const stock = e.target.querySelectorAll('input[type="number"]')[1].value || "∞";

            const newProduct = { id: Date.now(), name, category, price, stock, status: "Ativo" };
            database.products.push(newProduct);
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
    modalBody.innerHTML = content;
    modal.classList.add('show');
}

function closeModal() {
    modal.classList.remove('show');
}

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
   INICIALIZAÇÃO
   =========================== */

loadDatabase();
showPage('dashboard');

// Busca dados reais do bot
loadServerInfo();
loadChannels();
loadBotName();

// Atualiza o status do bot a cada 60 segundos
setInterval(loadServerInfo, 60000);

// Liga o botão de salvar configurações
const saveSettingsBtn = document.getElementById('saveSettingsBtn');
if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', saveSettings);
}
