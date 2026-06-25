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
   CONFIGURAÇÃO GLOBAL
   =========================== */

const BOT_API_URL = "https://pag-bot.onrender.com";
const CLIENT_ID   = "1516506393530601653";

let allServers = [];
let currentUser = null;

function getGuildId() {
    return localStorage.getItem('pagbot_current_guild_id') || '';
}

/* ===========================
   FETCH AUTENTICADO
   =========================== */

async function apiFetch(path, options = {}) {
    const res = await fetch(`${BOT_API_URL}${path}`, {
        ...options,
        credentials: 'include',
    });
    if (res.status === 401) {
        showLoginGate('Sua sessão expirou. Entre novamente para continuar.');
        throw new Error('Não autenticado');
    }
    if (res.status === 403) {
        showToast('Você não tem permissão sobre esse servidor.', 'error');
        throw new Error('Sem permissão');
    }
    if (res.status === 429) {
        showToast('Muitas requisições — espere um pouco e tente de novo.', 'error');
        throw new Error('Rate limit');
    }
    return res;
}

/* ===========================
   AUTENTICAÇÃO / LOGIN GATE
   =========================== */

function showLoginGate(message) {
    const gate = document.getElementById('loginGate');
    const msg  = document.getElementById('loginGateMessage');
    if (msg && message) msg.textContent = message;
    if (gate) gate.classList.add('show');
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.style.display = 'none';
}

function hideLoginGate() {
    const gate = document.getElementById('loginGate');
    if (gate) gate.classList.remove('show');
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.style.display = 'inline-flex';
}

async function checkAuthAndInit() {
    const params = new URLSearchParams(window.location.search);
    const loginResult = params.get('login');
    if (loginResult === 'erro') {
        showToast('Não foi possível concluir o login com o Discord. Tente de novo.', 'error');
    }
    if (loginResult) {
        params.delete('login');
        params.delete('motivo');
        const newUrl = window.location.pathname + (params.toString() ? `?${params}` : '');
        window.history.replaceState({}, '', newUrl);
    }

    try {
        const res  = await fetch(`${BOT_API_URL}/api/auth/me`, { credentials: 'include' });
        const data = await res.json();
        if (data.ok && data.authenticated) {
            currentUser = data.user;
            hideLoginGate();
            startApp();
        } else {
            showLoginGate();
        }
    } catch {
        showLoginGate('Não foi possível conectar ao servidor do bot. Tente novamente em alguns instantes.');
    }
}

async function logout() {
    try {
        await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch {}
    currentUser = null;
    allServers = [];
    showLoginGate('Você saiu. Entre novamente para continuar.');
}

document.getElementById('loginBtn')?.addEventListener('click', () => {
    window.location.href = `${BOT_API_URL}/api/auth/login`;
});
document.getElementById('logoutBtn')?.addEventListener('click', logout);

/* ===========================
   HELPERS
   =========================== */

function formatBRL(value) {
    return Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function formatDateShort(isoStr) {
    if (!isoStr) return '—';
    return new Date(isoStr).toLocaleDateString('pt-BR');
}

function statusBadge(status) {
    const map = {
        'Pago': 'badge-success', 'Ativo': 'badge-success', 'Aberto': 'badge-warning',
        'Pendente': 'badge-warning', 'Cancelado': 'badge-danger', 'Reembolsado': 'badge-danger',
        'Em Andamento': 'badge-info', 'Fechado': 'badge-info', 'Baixo Estoque': 'badge-warning',
    };
    return `<span class="badge ${map[status] || 'badge-info'}">${status}</span>`;
}

function showSkeleton(tbodySelector, cols) {
    const tbody = document.querySelector(tbodySelector);
    if (!tbody) return;
    tbody.innerHTML = Array(3).fill(`
        <tr>${Array(cols).fill('<td><div class="skeleton" style="height:16px;border-radius:4px;"></div></td>').join('')}</tr>
    `).join('');
}

function showEmpty(tbodySelector, cols, message) {
    const tbody = document.querySelector(tbodySelector);
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="${cols}" style="text-align:center;color:var(--text-secondary);padding:32px;">${message}</td></tr>`;
}

/* ===========================
   SERVIDOR / BOT INFO
   =========================== */

async function loadServerInfo() {
    const nameEl    = document.getElementById('serverName');
    const statusEl  = document.getElementById('botStatus');
    const indicator = document.getElementById('onlineIndicator');
    const avatarImg = document.getElementById('serverAvatarImg');
    const avatarSvg = document.getElementById('serverAvatarSvg');
    try {
        const res  = await apiFetch('/api/server-info');
        const data = await res.json();
        if (data.online) {
            if (statusEl)  statusEl.textContent       = "Bot Online";
            if (indicator) indicator.style.background = "#3ba55d";
            if (data.servers && data.servers.length > 0) {
                allServers = data.servers;
                let currentGuildId = getGuildId();
                let server = allServers.find(s => s.id === currentGuildId) || allServers[0];
                localStorage.setItem('pagbot_current_guild_id', server.id);
                aplicarServidor(server, avatarImg, avatarSvg, nameEl);
                loadChannels();
                loadBotName();
            } else {
                if (nameEl) nameEl.textContent = "Nenhum servidor seu tem o bot ainda";
            }
        } else {
            if (nameEl)    nameEl.textContent        = "Bot sem servidor";
            if (statusEl)  statusEl.textContent      = "Bot Offline";
            if (indicator) indicator.style.background = "#ed4245";
        }
    } catch (err) {
        if (nameEl)    nameEl.textContent        = "Bot Offline";
        if (statusEl)  statusEl.textContent      = "Sem conexão";
        if (indicator) indicator.style.background = "#ed4245";
    }
}

function aplicarServidor(server, avatarImg, avatarSvg, nameEl) {
    avatarImg = avatarImg || document.getElementById('serverAvatarImg');
    avatarSvg = avatarSvg || document.getElementById('serverAvatarSvg');
    nameEl    = nameEl    || document.getElementById('serverName');
    if (nameEl) nameEl.textContent = server.name;
    if (server.icon && avatarImg && avatarSvg) {
        avatarImg.src           = server.icon;
        avatarImg.style.display = "block";
        avatarSvg.style.display = "none";
    } else if (avatarImg && avatarSvg) {
        avatarImg.style.display = "none";
        avatarSvg.style.display = "block";
    }
}

function trocarServidor(guildId) {
    const server = allServers.find(s => s.id === guildId);
    if (!server) return;
    localStorage.setItem('pagbot_current_guild_id', guildId);
    aplicarServidor(server);
    fecharDropdownServidor();
    loadChannels();
    loadBotName();
    reloadCurrentPage();
    showToast(`Servidor alterado para ${server.name}`, 'success');
}

function fecharDropdownServidor() {
    const dd = document.getElementById('serverDropdown');
    if (dd) dd.style.display = 'none';
}

function abrirOAuth2() {
    fecharDropdownServidor();
    const url = CLIENT_ID
        ? `https://discord.com/oauth2/authorize?client_id=${CLIENT_ID}&permissions=8&scope=bot%20applications.commands`
        : 'https://discord.com/developers/applications';
    window.open(url, '_blank');
}

function setupServerDropdown() {
    const avatarWrapper = document.querySelector('.server-avatar');
    if (!avatarWrapper) return;
    avatarWrapper.style.cursor   = 'pointer';
    avatarWrapper.style.position = 'relative';

    const dropdown = document.createElement('div');
    dropdown.id = 'serverDropdown';
    dropdown.style.cssText = `
        display:none;position:absolute;top:calc(100% + 10px);right:0;
        background:#2C2F33;border:1px solid #404249;border-radius:10px;
        padding:6px;z-index:200;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,0.5);`;
    avatarWrapper.appendChild(dropdown);

    avatarWrapper.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = dropdown.style.display === 'block';
        if (isOpen) { dropdown.style.display = 'none'; }
        else { renderDropdownServidores(dropdown); dropdown.style.display = 'block'; }
    });
    document.addEventListener('click', () => { dropdown.style.display = 'none'; });
}

function renderDropdownServidores(dropdown) {
    const currentId = getGuildId();
    let serversHtml = '';
    if (allServers.length > 0) {
        serversHtml = allServers.map(server => {
            const isActive = server.id === currentId;
            const iniciais = server.name.slice(0, 2).toUpperCase();
            const iconHtml = server.icon
                ? `<img src="${server.icon}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;">`
                : `<div style="width:28px;height:28px;border-radius:50%;background:#5865F2;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:white;">${iniciais}</div>`;
            return `
                <button onclick="trocarServidor('${server.id}')" style="
                    display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;
                    background:${isActive ? 'rgba(88,101,242,0.15)' : 'transparent'};
                    border:none;border-radius:8px;cursor:pointer;text-align:left;transition:background 0.2s;"
                onmouseover="this.style.background='rgba(88,101,242,0.1)'"
                onmouseout="this.style.background='${isActive ? 'rgba(88,101,242,0.15)' : 'transparent'}'">
                    ${iconHtml}
                    <span style="font-size:13px;font-weight:600;color:${isActive ? '#5865F2' : '#ffffff'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px;">${server.name}</span>
                    ${isActive ? '<svg style="margin-left:auto;flex-shrink:0;" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5865F2" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>' : ''}
                </button>`;
        }).join('');
    } else {
        serversHtml = `<p style="font-size:12px;color:#b5bac1;padding:8px 10px;margin:0;">Nenhum servidor seu encontrado</p>`;
    }
    dropdown.innerHTML = `${serversHtml}
        <div style="border-top:1px solid #404249;margin:6px 0;"></div>
        <button onclick="abrirOAuth2()" style="display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;background:transparent;border:none;color:#43e97b;font-size:13px;font-weight:600;cursor:pointer;border-radius:8px;"
        onmouseover="this.style.background='rgba(67,233,123,0.1)'" onmouseout="this.style.background='transparent'">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            Adicionar servidor
        </button>`;
}

async function loadChannels() {
    const selects = ['channelCompras', 'channelLogs', 'channelTickets'].map(id => document.getElementById(id)).filter(Boolean);
    if (!selects.length) return;
    try {
        const res  = await apiFetch(`/api/channels?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (data.online && data.channels && data.channels.length > 0) {
            const savedSettings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
            selects.forEach(select => {
                const key = select.dataset.setting;
                select.innerHTML = '<option value="">Selecione um canal...</option>' +
                    data.channels.map(c => `<option value="${c.id}">#${c.name}</option>`).join('');
                if (savedSettings[key]) select.value = savedSettings[key];
            });
        } else {
            selects.forEach(s => { s.innerHTML = '<option value="">Bot offline ou fora deste servidor</option>'; });
        }
    } catch {
        selects.forEach(s => { s.innerHTML = '<option value="">Sem conexão com o bot</option>'; });
    }
}

async function loadBotName() {
    const input = document.getElementById('botNameInput');
    if (!input) return;
    try {
        const res  = await apiFetch(`/api/bot-name?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (data.online && data.name) {
            input.value            = data.name;
            input.dataset.original = data.name;
        } else {
            input.placeholder = "Bot offline";
        }
    } catch {
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
                const res  = await apiFetch(`/api/bot-name?guild_id=${getGuildId()}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });
                const data = await res.json();
                if (data.ok) {
                    input.dataset.original = newName;
                    showToast("Configurações salvas! Nome atualizado no Discord.", "success");
                    loadServerInfo();
                    return;
                }
            } catch {}
        }
    }

    try {
        await apiFetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guild_id: getGuildId(), ...settings })
        });
    } catch {}

    showToast("Configurações salvas!", "success");
}

/* ===========================
   DASHBOARD
   =========================== */

async function loadDashboard() {
    document.querySelectorAll('.stat-value').forEach(el => {
        el.innerHTML = '<div class="skeleton" style="height:28px;width:80px;border-radius:6px;display:inline-block;"></div>';
    });

    try {
        const res  = await apiFetch(`/api/stats?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);

        const s = data.stats;
        const vals = document.querySelectorAll('.stat-value');
        if (vals[0]) vals[0].textContent = formatBRL(s.vendas_hoje);
        if (vals[1]) vals[1].textContent = formatBRL(s.vendas_semana);
        if (vals[2]) vals[2].textContent = formatBRL(s.vendas_mes);
        if (vals[3]) vals[3].textContent = formatBRL(s.faturamento_total);
        if (vals[4]) vals[4].textContent = s.produtos_ativos;
        if (vals[5]) vals[5].textContent = s.clientes.toLocaleString('pt-BR');
        if (vals[6]) vals[6].textContent = s.tickets_abertos;
        if (vals[7]) vals[7].textContent = `${s.taxa_conversao}%`;

        renderSalesChart(data.chart || []);
        renderTopProducts(data.top_products || []);
    } catch (e) {
        console.warn("[dashboard] Erro ao carregar stats:", e.message);
        document.querySelectorAll('.stat-value').forEach(el => { el.textContent = '—'; });
    }
}

function renderSalesChart(points) {
    const svg = document.querySelector('#dashboard-page .chart');
    if (!svg || !points.length) return;

    const values = points.map(p => p.value);
    const max    = Math.max(...values, 1);
    const W = 380, H = 140, PAD = 10;
    const xs = points.map((_, i) => PAD + (i / (points.length - 1)) * (W - PAD * 2));
    const ys = values.map(v => PAD + (1 - v / max) * (H - PAD * 2));

    const line    = xs.map((x, i) => `${x},${ys[i]}`).join(' ');
    const area    = `${xs[0]},${H - PAD} ${line} ${xs[xs.length - 1]},${H - PAD}`;

    const maxLabel = max >= 1000 ? `R$${(max/1000).toFixed(1)}k` : `R$${max.toFixed(0)}`;
    const peakIdx = values.indexOf(max);

    svg.innerHTML = `
        <defs>
            <linearGradient id="chartGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" style="stop-color:#667eea;stop-opacity:0.35"/>
                <stop offset="100%" style="stop-color:#667eea;stop-opacity:0"/>
            </linearGradient>
        </defs>
        <text x="42" y="18" font-size="9" fill="var(--text-secondary)">${maxLabel}</text>
        <text x="42" y="${H - PAD + 4}" font-size="9" fill="var(--text-secondary)">R$0</text>
        <line x1="52" y1="${PAD}" x2="52" y2="${H - PAD}" stroke="var(--border)" stroke-width="1"/>
        <line x1="52" y1="${H - PAD}" x2="${W}" y2="${H - PAD}" stroke="var(--border)" stroke-width="1"/>
        <polygon points="${area}" fill="url(#chartGrad)"/>
        <polyline points="${line}" fill="none" stroke="#667eea" stroke-width="2" stroke-linejoin="round"/>
        ${peakIdx > 0 ? `<circle cx="${xs[peakIdx]}" cy="${ys[peakIdx]}" r="4" fill="#667eea"/>
        <text x="${xs[peakIdx]}" y="${ys[peakIdx] - 8}" font-size="9" fill="#667eea" text-anchor="middle">${formatBRL(values[peakIdx]).replace('R$\u00a0','R$')}</text>` : ''}
        <circle cx="${xs[xs.length-1]}" cy="${ys[xs.length-1]}" r="4" fill="#667eea"/>
    `;
}

function renderTopProducts(products) {
    const container = document.querySelector('#dashboard-page .bar-chart');
    if (!container) return;
    if (!products.length) {
        container.innerHTML = '<p style="color:var(--text-secondary);font-size:13px;">Nenhuma venda registrada ainda.</p>';
        return;
    }
    const maxCount = products[0].count || 1;
    const colors   = [
        'linear-gradient(90deg,#667eea,#764ba2)',
        'linear-gradient(90deg,#f093fb,#f5576c)',
        'linear-gradient(90deg,#4facfe,#00f2fe)',
        'linear-gradient(90deg,#43e97b,#38f9d7)',
        'linear-gradient(90deg,#fa709a,#fee140)'
    ];
    container.innerHTML = products.map((p, i) => `
        <div class="bar-item">
            <div class="bar-label">${p.name}</div>
            <div class="bar-container">
                <div class="bar" style="width:${Math.round((p.count / maxCount) * 100)}%;background:${colors[i % colors.length]};"></div>
            </div>
            <div class="bar-value">${p.count} venda${p.count !== 1 ? 's' : ''} · ${formatBRL(p.revenue)}</div>
        </div>
    `).join('');
}

/* ===========================
   PRODUTOS
   =========================== */

let productsData = [];

async function loadProducts() {
    showSkeleton('#produtos-page .data-table tbody', 6);
    try {
        const res  = await apiFetch(`/api/products?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        productsData = data.products || [];
        renderProducts(productsData);
    } catch (e) {
        showEmpty('#produtos-page .data-table tbody', 6, `Erro ao carregar produtos: ${e.message}`);
    }
}

function renderProducts(products) {
    const tbody = document.querySelector('#produtos-page .data-table tbody');
    if (!tbody) return;
    if (!products.length) {
        showEmpty('#produtos-page .data-table tbody', 6, 'Nenhum produto cadastrado. Clique em "Adicionar Produto" para começar.');
        return;
    }
    tbody.innerHTML = products.map(p => `
        <tr>
            <td><strong>${p.name}</strong>${p.description ? `<br><small style="color:var(--text-secondary)">${p.description}</small>` : ''}</td>
            <td>${p.category || '—'}</td>
            <td>${formatBRL(p.price)}</td>
            <td>${p.stock || '∞'}</td>
            <td>${statusBadge(p.status || 'Ativo')}</td>
            <td>
                <button class="action-btn" onclick="editProduct(${p.id})" title="Editar">
                    <i data-lucide="edit-3"></i>
                </button>
                <button class="action-btn" onclick="deleteProduct(${p.id}, '${p.name.replace(/'/g, "\\'")}')" title="Deletar">
                    <i data-lucide="trash-2"></i>
                </button>
            </td>
        </tr>
    `).join('');
    if (window.lucide) lucide.createIcons();
}

function openAddProductModal() {
    showModal('Adicionar Produto', `
        <div class="form-group"><label>Nome *</label><input type="text" id="pName" placeholder="Ex: Curso Premium"></div>
        <div class="form-group"><label>Categoria</label>
            <select id="pCategory"><option>Digital</option><option>Educação</option><option>Serviço</option><option>Software</option><option>Outro</option></select>
        </div>
        <div class="form-group"><label>Preço (R$) *</label><input type="number" id="pPrice" step="0.01" min="0" placeholder="99.90"></div>
        <div class="form-group"><label>Estoque</label><input type="text" id="pStock" placeholder="∞ para ilimitado"></div>
        <div class="form-group"><label>Descrição</label><input type="text" id="pDesc" placeholder="Descrição curta do produto"></div>
        <div class="form-group"><label>Conteúdo de Entrega</label><input type="text" id="pDelivery" placeholder="Link, código, texto enviado após compra"></div>
        <button class="btn btn-primary btn-large" onclick="submitProduct()">Salvar Produto</button>
    `);
}

async function submitProduct(id = null) {
    const name     = document.getElementById('pName').value.trim();
    const category = document.getElementById('pCategory').value;
    const price    = parseFloat(document.getElementById('pPrice').value);
    const stock    = document.getElementById('pStock').value.trim() || '∞';
    const desc     = document.getElementById('pDesc').value.trim();
    const delivery = document.getElementById('pDelivery').value.trim();

    if (!name || isNaN(price)) { showToast('Nome e preço são obrigatórios!', 'error'); return; }

    const payload = { guild_id: getGuildId(), name, category, price, stock, description: desc, delivery_content: delivery };
    try {
        const res = await apiFetch(
            id ? `/api/products/${id}` : `/api/products`,
            { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }
        );
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        closeModal();
        showToast(id ? 'Produto atualizado!' : 'Produto criado!', 'success');
        loadProducts();
    } catch (e) {
        showToast(`Erro: ${e.message}`, 'error');
    }
}

function editProduct(id) {
    const p = productsData.find(x => x.id === id);
    if (!p) return;
    showModal('Editar Produto', `
        <div class="form-group"><label>Nome *</label><input type="text" id="pName" value="${p.name}"></div>
        <div class="form-group"><label>Categoria</label>
            <select id="pCategory">
                ${['Digital','Educação','Serviço','Software','Outro'].map(c => `<option${p.category===c?' selected':''}>${c}</option>`).join('')}
            </select>
        </div>
        <div class="form-group"><label>Preço (R$) *</label><input type="number" id="pPrice" step="0.01" value="${p.price}"></div>
        <div class="form-group"><label>Estoque</label><input type="text" id="pStock" value="${p.stock || '∞'}"></div>
        <div class="form-group"><label>Descrição</label><input type="text" id="pDesc" value="${p.description || ''}"></div>
        <div class="form-group"><label>Conteúdo de Entrega</label><input type="text" id="pDelivery" value="${p.delivery_content || ''}"></div>
        <button class="btn btn-primary btn-large" onclick="submitProduct(${id})">Atualizar Produto</button>
    `);
}

async function deleteProduct(id, name) {
    if (!confirm(`Deletar "${name}"? Esta ação não pode ser desfeita.`)) return;
    try {
        const res  = await apiFetch(`/api/products/${id}?guild_id=${getGuildId()}`, { method: 'DELETE' });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        showToast('Produto deletado!', 'success');
        loadProducts();
    } catch (e) {
        showToast(`Erro: ${e.message}`, 'error');
    }
}

/* ===========================
   PEDIDOS
   =========================== */

let currentOrderFilter = 'todos';

async function loadOrders(filter = currentOrderFilter) {
    currentOrderFilter = filter;
    showSkeleton('#pedidos-page .data-table tbody', 6);
    try {
        const res  = await apiFetch(`/api/orders?guild_id=${getGuildId()}&status=${filter}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        renderOrders(data.orders || []);
    } catch (e) {
        showEmpty('#pedidos-page .data-table tbody', 6, `Erro ao carregar pedidos: ${e.message}`);
    }
}

function renderOrders(orders) {
    const tbody = document.querySelector('#pedidos-page .data-table tbody');
    if (!tbody) return;
    if (!orders.length) {
        showEmpty('#pedidos-page .data-table tbody', 6, 'Nenhum pedido encontrado.');
        return;
    }
    tbody.innerHTML = orders.map(o => `
        <tr>
            <td>#${String(o.id).padStart(6, '0')}</td>
            <td>${o.customer_name || '—'}</td>
            <td>${(o.products && o.products.name) || '—'}</td>
            <td>${formatBRL(o.amount)}</td>
            <td>${formatDateShort(o.created_at)}</td>
            <td>${statusBadge(o.status)}</td>
        </tr>
    `).join('');
}

/* ===========================
   CLIENTES
   =========================== */

async function loadClients() {
    const grid = document.querySelector('.clients-grid');
    if (!grid) return;
    grid.innerHTML = Array(3).fill(`
        <div class="client-card">
            <div class="skeleton" style="width:64px;height:64px;border-radius:50%;margin:0 auto 16px;"></div>
            <div class="skeleton" style="height:18px;width:60%;margin:0 auto 8px;border-radius:4px;"></div>
            <div class="skeleton" style="height:12px;width:40%;margin:0 auto;border-radius:4px;"></div>
        </div>
    `).join('');

    try {
        const res  = await apiFetch(`/api/clients?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        renderClients(data.clients || []);
    } catch (e) {
        grid.innerHTML = `<p style="color:var(--text-secondary);grid-column:1/-1;text-align:center;padding:32px;">Erro ao carregar clientes: ${e.message}</p>`;
    }
}

function renderClients(clients) {
    const grid = document.querySelector('.clients-grid');
    if (!grid) return;
    if (!clients.length) {
        grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:48px;color:var(--text-secondary);">
            <p style="font-size:32px;margin-bottom:12px;">👥</p>
            <p>Nenhum cliente ainda. As compras pagas aparecerão aqui.</p>
        </div>`;
        return;
    }
    const initials = name => name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
    const colors   = ['#5865F2','#f5576c','#43e97b','#4facfe','#fa709a','#667eea'];
    grid.innerHTML = clients.map((c, i) => `
        <div class="client-card">
            <div class="client-avatar">
                <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                    <circle cx="32" cy="32" r="31" fill="${colors[i % colors.length]}"/>
                    <text x="32" y="42" font-size="26" font-weight="bold" fill="white" text-anchor="middle">${initials(c.name)}</text>
                </svg>
            </div>
            <h3>${c.name}</h3>
            <p class="client-id">ID: ${c.id}</p>
            <div class="client-stats">
                <div class="stat"><span class="label">Total Gasto</span><span class="value">${formatBRL(c.total_spent)}</span></div>
                <div class="stat"><span class="label">Compras</span><span class="value">${c.purchase_count}</span></div>
            </div>
            <p class="last-purchase">Última compra: ${formatDateShort(c.last_purchase)}</p>
            <button class="btn btn-secondary btn-small" onclick="verHistoricoCliente('${c.id}', '${c.name.replace(/'/g,"\\'")}')">Ver Histórico</button>
        </div>
    `).join('');
}

async function verHistoricoCliente(clientId, clientName) {
    showModal(`Histórico — ${clientName}`, `<div style="color:var(--text-secondary);padding:16px;text-align:center;">Carregando...</div>`);
    try {
        const res  = await apiFetch(`/api/clients/${encodeURIComponent(clientId)}/orders?guild_id=${getGuildId()}`);
        const data = await res.json();
        const orders = data.orders || [];
        if (!orders.length) {
            document.getElementById('modalBody').innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:24px;">Nenhum pedido encontrado.</p>';
            return;
        }
        document.getElementById('modalBody').innerHTML = `
            <table class="data-table" style="margin-top:8px;">
                <thead><tr><th>Pedido</th><th>Produto</th><th>Valor</th><th>Data</th><th>Status</th></tr></thead>
                <tbody>${orders.map(o => `
                    <tr>
                        <td>#${String(o.id).padStart(6,'0')}</td>
                        <td>${(o.products && o.products.name) || '—'}</td>
                        <td>${formatBRL(o.amount)}</td>
                        <td>${formatDateShort(o.created_at)}</td>
                        <td>${statusBadge(o.status)}</td>
                    </tr>
                `).join('')}</tbody>
            </table>`;
    } catch (e) {
        document.getElementById('modalBody').innerHTML = `<p style="color:var(--danger);">Erro: ${e.message}</p>`;
    }
}

/* ===========================
   LOGS
   =========================== */

let logsData = [];

async function loadLogs() {
    showSkeleton('#logs-page .data-table tbody', 4);
    try {
        const res  = await apiFetch(`/api/logs?guild_id=${getGuildId()}&limit=100`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        logsData = data.logs || [];
        renderLogs(logsData);
    } catch (e) {
        showEmpty('#logs-page .data-table tbody', 4, `Erro ao carregar logs: ${e.message}`);
    }
}

function renderLogs(logs) {
    const tbody = document.querySelector('#logs-page .data-table tbody');
    if (!tbody) return;
    if (!logs.length) {
        showEmpty('#logs-page .data-table tbody', 4, 'Nenhuma atividade registrada ainda.');
        return;
    }
    const typeMap = {
        'produto_criado': ['badge-success', 'Produto'],
        'produto_deletado': ['badge-danger', 'Produto'],
        'venda': ['badge-success', 'Venda'],
        'reembolso': ['badge-warning', 'Reembolso'],
        'alteracao': ['badge-info', 'Alteração'],
        'ticket': ['badge-info', 'Ticket'],
        'afiliado_criado': ['badge-success', 'Afiliado'],
    };
    tbody.innerHTML = logs.map(l => {
        const [cls, label] = typeMap[l.event_type] || ['badge-info', l.event_type || 'Sistema'];
        return `
            <tr>
                <td>${formatDate(l.created_at)}</td>
                <td><span class="badge ${cls}">${label}</span></td>
                <td>${l.description || '—'}</td>
                <td>${l.user || 'Sistema'}</td>
            </tr>`;
    }).join('');
}

/* ===========================
   CUPONS
   =========================== */

let couponsData = [];

async function loadCoupons() {
    const grid = document.querySelector('.coupons-grid');
    if (!grid) return;
    grid.innerHTML = '<div style="color:var(--text-secondary);padding:24px;">Carregando...</div>';
    try {
        const res  = await apiFetch(`/api/coupons?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        couponsData = data.coupons || [];
        renderCoupons(couponsData);
    } catch (e) {
        grid.innerHTML = `<p style="color:var(--danger);">Erro: ${e.message}</p>`;
    }
}

function renderCoupons(coupons) {
    const grid = document.querySelector('.coupons-grid');
    if (!grid) return;
    if (!coupons.length) {
        grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:48px;color:var(--text-secondary);">
            <p style="font-size:32px;margin-bottom:12px;">🎟️</p>
            <p>Nenhum cupom criado ainda.</p>
        </div>`;
        return;
    }
    grid.innerHTML = coupons.map(c => `
        <div class="coupon-card">
            <div class="coupon-header">
                <h3>${c.code}</h3>
                <span class="coupon-badge">${c.discount_percent}% OFF</span>
            </div>
            <div class="coupon-details">
                <p><strong>Usos:</strong> ${c.uses || 0}/${c.max_uses || '∞'}</p>
                <p><strong>Expira:</strong> ${c.expires_at ? formatDateShort(c.expires_at) : 'Sem expiração'}</p>
                <p><strong>Criado:</strong> ${formatDateShort(c.created_at)}</p>
            </div>
            <div class="coupon-actions">
                <button class="btn btn-danger btn-small" onclick="deleteCoupon(${c.id}, '${c.code}')">Deletar</button>
            </div>
        </div>
    `).join('');
}

function openAddCouponModal() {
    showModal('Criar Cupom', `
        <div class="form-group"><label>Código *</label><input type="text" id="cCode" placeholder="Ex: DESCONTO20" style="text-transform:uppercase;"></div>
        <div class="form-group"><label>Desconto (%) *</label><input type="number" id="cDiscount" min="1" max="100" placeholder="10"></div>
        <div class="form-group"><label>Máximo de Usos</label><input type="number" id="cMaxUses" placeholder="100 (vazio = ilimitado)"></div>
        <div class="form-group"><label>Data de Expiração</label><input type="date" id="cExpires"></div>
        <button class="btn btn-primary btn-large" onclick="submitCoupon()">Criar Cupom</button>
    `);
}

async function submitCoupon() {
    const code     = document.getElementById('cCode').value.trim().toUpperCase();
    const discount = parseInt(document.getElementById('cDiscount').value);
    const maxUses  = parseInt(document.getElementById('cMaxUses').value) || null;
    const expires  = document.getElementById('cExpires').value || null;
    if (!code || isNaN(discount)) { showToast('Código e desconto são obrigatórios!', 'error'); return; }
    try {
        const res = await apiFetch('/api/coupons', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guild_id: getGuildId(), code, discount_percent: discount, max_uses: maxUses, expires_at: expires })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        closeModal();
        showToast('Cupom criado!', 'success');
        loadCoupons();
    } catch (e) {
        showToast(`Erro: ${e.message}`, 'error');
    }
}

async function deleteCoupon(id, code) {
    if (!confirm(`Deletar cupom "${code}"?`)) return;
    try {
        const res  = await apiFetch(`/api/coupons/${id}?guild_id=${getGuildId()}`, { method: 'DELETE' });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        showToast('Cupom deletado!', 'success');
        loadCoupons();
    } catch (e) {
        showToast(`Erro: ${e.message}`, 'error');
    }
}

/* ===========================
   AFILIADOS
   =========================== */

async function loadAffiliates() {
    showSkeleton('#afiliados-page .data-table tbody', 6);
    try {
        const res  = await apiFetch(`/api/affiliates?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        renderAffiliates(data.affiliates || []);
    } catch (e) {
        showEmpty('#afiliados-page .data-table tbody', 6, `Erro ao carregar afiliados: ${e.message}`);
    }
}

function renderAffiliates(affiliates) {
    const tbody = document.querySelector('#afiliados-page .data-table tbody');
    if (!tbody) return;
    if (!affiliates.length) {
        showEmpty('#afiliados-page .data-table tbody', 6, 'Nenhum afiliado cadastrado.');
        return;
    }
    tbody.innerHTML = affiliates.map(a => `
        <tr>
            <td>${a.name || '—'}</td>
            <td>${a.code || '—'}</td>
            <td>${a.commission_percent || 15}%</td>
            <td>${(a.clicks || 0).toLocaleString('pt-BR')}</td>
            <td>${(a.conversions || 0).toLocaleString('pt-BR')}</td>
            <td>${formatBRL(a.earnings)}</td>
        </tr>
    `).join('');
}

function openAddAffiliateModal() {
    showModal('Cadastrar Afiliado', `
        <div class="form-group"><label>Nome *</label><input type="text" id="aName" placeholder="Ex: João Silva"></div>
        <div class="form-group"><label>Código do Cupom *</label><input type="text" id="aCode" placeholder="Ex: JOAO20" style="text-transform:uppercase;"></div>
        <div class="form-group"><label>Comissão (%)</label><input type="number" id="aCommission" min="1" max="100" value="15" placeholder="15"></div>
        <button class="btn btn-primary btn-large" onclick="submitAffiliate()">Cadastrar Afiliado</button>
    `);
}

async function submitAffiliate() {
    const name       = document.getElementById('aName').value.trim();
    const code       = document.getElementById('aCode').value.trim().toUpperCase();
    const commission = parseInt(document.getElementById('aCommission').value) || 15;
    if (!name || !code) { showToast('Nome e código são obrigatórios!', 'error'); return; }
    try {
        const res = await apiFetch('/api/affiliates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guild_id: getGuildId(), name, code, commission_percent: commission })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        closeModal();
        showToast('Afiliado cadastrado!', 'success');
        loadAffiliates();
    } catch (e) {
        showToast(`Erro: ${e.message}`, 'error');
    }
}

/* ===========================
   TICKETS
   =========================== */

async function loadTickets() {
    showSkeleton('#tickets-page .data-table tbody', 6);
    try {
        const res  = await apiFetch(`/api/tickets?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        renderTickets(data.tickets || []);
        updateTicketStats(data.tickets || []);
    } catch (e) {
        showEmpty('#tickets-page .data-table tbody', 6, `Erro ao carregar tickets: ${e.message}`);
    }
}

function renderTickets(tickets) {
    const tbody = document.querySelector('#tickets-page .data-table tbody');
    if (!tbody) return;
    if (!tickets.length) {
        showEmpty('#tickets-page .data-table tbody', 6, 'Nenhum ticket.');
        return;
    }
    tbody.innerHTML = tickets.map(t => `
        <tr>
            <td>#T${String(t.id).padStart(3,'0')}</td>
            <td>${t.customer_name || '—'}</td>
            <td>${t.subject || '—'}</td>
            <td>${statusBadge(t.status || 'Aberto')}</td>
            <td>${t.assignee || '—'}</td>
            <td>${formatDateShort(t.created_at)}</td>
            <td>
                ${t.status === 'Aberto' ? `<button class="btn btn-secondary btn-small" onclick="closeTicket(${t.id})">Fechar</button>` : '—'}
            </td>
        </tr>
    `).join('');
}

function updateTicketStats(tickets) {
    const abertos  = tickets.filter(t => t.status === 'Aberto').length;
    const fechados = tickets.filter(t => t.status === 'Fechado').length;
    const els      = document.querySelectorAll('.ticket-stat .big-number');
    if (els[0]) els[0].textContent = abertos;
    if (els[1]) els[1].textContent = fechados;
}

async function closeTicket(id) {
    if (!confirm('Fechar este ticket?')) return;
    try {
        const res  = await apiFetch(`/api/tickets/${id}/close?guild_id=${getGuildId()}`, { method: 'PATCH' });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error);
        showToast('Ticket fechado!', 'success');
        loadTickets();
    } catch (e) {
        showToast(`Erro: ${e.message}`, 'error');
    }
}

/* ===========================
   PAGAMENTOS
   =========================== */

async function loadPaymentMethodActive() {
    const pixToggle = document.getElementById('pixMethodToggle');
    const mpToggle  = document.getElementById('mpMethodToggle');
    if (!pixToggle || !mpToggle) return;
    let metodoAtivo = 'mercadopago';
    try {
        const res  = await apiFetch(`/api/payment-method?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (data.ok && data.active) metodoAtivo = data.active;
    } catch {
        const saved = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
        metodoAtivo = saved.payment_method_active || 'mercadopago';
    }
    pixToggle.checked = (metodoAtivo === 'pix');
    mpToggle.checked  = (metodoAtivo === 'mercadopago');
    aplicarEstiloMetodoAtivo(metodoAtivo);
}

function aplicarEstiloMetodoAtivo(metodoAtivo) {
    const pixCard   = document.querySelector('.integration-card[data-method="pix"]');
    const mpCard    = document.querySelector('.integration-card[data-method="mercadopago"]');
    const pixStatus = document.getElementById('pixStatusLabel');
    const mpStatus  = document.getElementById('mpStatusLabel');
    if (pixCard) pixCard.classList.toggle('method-active', metodoAtivo === 'pix');
    if (mpCard)  mpCard.classList.toggle('method-active', metodoAtivo === 'mercadopago');
    if (pixStatus) pixStatus.textContent = metodoAtivo === 'pix'         ? '✅ Ativo no /criar_pix' : 'Conectado';
    if (mpStatus)  mpStatus.textContent  = metodoAtivo === 'mercadopago' ? '✅ Ativo no /criar_pix' : 'Conectado';
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
        const res  = await apiFetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payment_method_active: metodo, guild_id: getGuildId() })
        });
        const data = await res.json();
        showToast(metodo === 'pix' ? 'PIX ativado!' : 'Mercado Pago ativado!', data.ok ? 'success' : 'error');
    } catch {
        showToast('Bot offline: método salvo localmente.');
    }
}

function setupPaymentMethodToggles() {
    document.querySelectorAll('.payment-method-toggle').forEach(toggle => {
        toggle.addEventListener('change', (e) => {
            const metodo = e.target.dataset.method;
            setPaymentMethodActive(e.target.checked ? metodo : (metodo === 'pix' ? 'mercadopago' : 'pix'));
        });
    });
}

/* ===========================
   PIX / MERCADO PAGO CONFIG
   =========================== */

function detectarTipoChavePix(chave) {
    chave = chave.trim();
    const digitos = chave.replace(/\D/g, '');
    if (/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(chave)) return 'aleatoria';
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(chave)) return 'email';
    if (/^\+?55\s?\(?\d{2}\)?\s?\d{4,5}-?\d{4}$/.test(chave) || /^\(?\d{2}\)?\s?\d{4,5}-?\d{4}$/.test(chave)) return 'telefone';
    if (digitos.length === 14) return 'cnpj';
    if (digitos.length === 11) return 'cpf';
    return chave.length > 0 ? 'aleatoria' : null;
}

function formatarChavePix(chave) {
    chave = chave.trim();
    const tipo = detectarTipoChavePix(chave);
    const d    = chave.replace(/\D/g, '');
    if (tipo === 'cpf' && d.length === 11) return { tipo, label: 'CPF', exibicao: `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9)}` };
    if (tipo === 'cnpj' && d.length === 14) return { tipo, label: 'CNPJ', exibicao: `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12)}` };
    if (tipo === 'telefone') { const nums = d.startsWith('55') ? d.slice(2) : d; return { tipo, label: 'Telefone', exibicao: `+55 (${nums.slice(0,2)}) ${nums.slice(2,7)}-${nums.slice(7)}` }; }
    if (tipo === 'email') return { tipo, label: 'E-mail', exibicao: chave.toLowerCase() };
    return { tipo: 'aleatoria', label: 'Chave Aleatória', exibicao: chave };
}

const PIX_ICONS = { cpf:'credit-card', cnpj:'building-2', telefone:'phone', email:'mail', aleatoria:'key' };

function abrirConfigPix() {
    const saved = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    showModal('Configurar PIX', `
        <div class="form-group">
            <label>Chave PIX</label>
            <input type="text" id="pixKeyInput" placeholder="CPF, CNPJ, e-mail, telefone ou chave aleatória" value="${saved.pix_key || ''}" oninput="atualizarPreviewChave(this.value)">
        </div>
        <div id="pixKeyPreview" style="display:none;align-items:center;gap:12px;padding:12px 14px;border-radius:10px;background:rgba(88,101,242,0.08);border:1px solid rgba(88,101,242,0.28);margin-bottom:16px;">
            <div id="pixKeyIcon" style="color:var(--primary);"></div>
            <div style="display:flex;flex-direction:column;gap:3px;">
                <span id="pixKeyTipoLabel" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-secondary);"></span>
                <span id="pixKeyFormatada" style="font-size:14px;font-weight:600;color:var(--text-primary);font-family:monospace;"></span>
            </div>
        </div>
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
    if (!valor.trim()) { preview.style.display = 'none'; return; }
    const r = formatarChavePix(valor);
    if (!r.tipo) { preview.style.display = 'none'; return; }
    icon.innerHTML    = `<i data-lucide="${PIX_ICONS[r.tipo] || 'key'}" style="width:24px;height:24px;"></i>`;
    if (window.lucide) lucide.createIcons();
    label.textContent = r.label;
    fmt.textContent   = r.exibicao;
    preview.style.display = 'flex';
}

async function salvarConfigPix() {
    const key = document.getElementById('pixKeyInput').value.trim();
    if (!key) { showToast('Insira uma chave PIX!'); return; }
    const settings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    settings.pix_key = key;
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));
    try {
        await apiFetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pix_key: key, guild_id: getGuildId() })
        });
    } catch {}
    closeModal();
    showToast('Chave PIX salva!', 'success');
}

function abrirConfigMercadoPago() {
    const saved = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    showModal('Configurar Mercado Pago', `
        <div class="form-group"><label>Access Token</label><input type="text" id="mpTokenInput" placeholder="APP_USR-..." value="${saved.mp_access_token || ''}"></div>
        <div class="form-group"><label>Chave PIX da conta MP</label><input type="text" id="mpPixKeyInput" placeholder="E-mail ou chave cadastrada no Mercado Pago" value="${saved.mp_pix_key || ''}"></div>
        <div id="mpTesteResult" style="margin-bottom:16px;padding:12px;border-radius:8px;display:none;font-size:13px;"></div>
        <div style="display:flex;gap:8px;">
            <button class="btn btn-secondary" style="flex:1" onclick="testarTokenMP()">Testar conexão</button>
            <button class="btn btn-primary" style="flex:1" onclick="salvarConfigMercadoPago()">Salvar</button>
        </div>
    `);
}

async function testarTokenMP() {
    const resultEl = document.getElementById('mpTesteResult');
    resultEl.style.display='block'; resultEl.style.color='var(--text-secondary)'; resultEl.textContent='⏳ Testando...';
    try {
        const res  = await apiFetch('/api/test-mp');
        const data = await res.json();
        if (data.ok && data.email) { resultEl.style.color='var(--success)'; resultEl.textContent=`✅ Conectado — ${data.email}`; }
        else { resultEl.style.color='var(--danger)'; resultEl.textContent=`❌ ${data.error || 'Token inválido.'}`; }
    } catch { resultEl.style.color='var(--danger)'; resultEl.textContent='❌ Erro de conexão.'; }
}

async function salvarConfigMercadoPago() {
    const token  = document.getElementById('mpTokenInput').value.trim();
    const pixKey = document.getElementById('mpPixKeyInput').value.trim();
    if (!token) { showToast('Insira o Access Token!'); return; }
    const settings = JSON.parse(localStorage.getItem('pagbot_settings') || '{}');
    settings.mp_access_token = token;
    settings.mp_pix_key = pixKey;
    localStorage.setItem('pagbot_settings', JSON.stringify(settings));
    try {
        await apiFetch('/api/config', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ mp_access_token: token, mp_pix_key: pixKey, guild_id: getGuildId() })
        });
    } catch {}
    closeModal();
    showToast('Mercado Pago configurado!', 'success');
}

/* ===========================
   AUTOMAÇÕES
   =========================== */

let currentAutomations = {
    mensagens_automaticas: true,
    cargos_automaticos: true,
    respostas_automaticas: false,
    logs_automaticos: true,
    entrega_automatica: true
};

async function loadAutomations() {
    try {
        const res = await apiFetch(`/api/automations?guild_id=${getGuildId()}`);
        const data = await res.json();
        if (data.ok && data.automations) {
            currentAutomations = data.automations;
        }
        renderAutomationToggles();
    } catch (e) {
        console.warn('Erro ao carregar automações:', e);
        renderAutomationToggles();
    }
}

function renderAutomationToggles() {
    const container = document.querySelector('.automations-grid');
    if (!container) return;
    const items = [
        { key: 'mensagens_automaticas', title: 'Mensagens Automáticas', desc: 'Enviar mensagens automáticas após compra', icon: 'message-square' },
        { key: 'cargos_automaticos', title: 'Cargos Automáticos', desc: 'Atribuir cargos automaticamente aos compradores', icon: 'shield-check' },
        { key: 'respostas_automaticas', title: 'Respostas Automáticas', desc: 'Responder automaticamente a mensagens', icon: 'reply-all' },
        { key: 'logs_automaticos', title: 'Logs Automáticos', desc: 'Registrar automaticamente todas as atividades', icon: 'file-text' },
        { key: 'entrega_automatica', title: 'Entrega Automática', desc: 'Entregar produtos automaticamente após pagamento', icon: 'send' }
    ];
    container.innerHTML = items.map(item => `
        <div class="automation-card">
            <div class="automation-header">
                <div style="display:flex;align-items:center;gap:10px;">
                    <i data-lucide="${item.icon}" style="width:20px;height:20px;color:var(--primary);"></i>
                    <h3>${item.title}</h3>
                </div>
                <label class="switch">
                    <input type="checkbox" data-automation="${item.key}" ${currentAutomations[item.key] ? 'checked' : ''} onchange="toggleAutomation('${item.key}', this.checked)">
                    <span class="slider"></span>
                </label>
            </div>
            <p>${item.desc}</p>
        </div>
    `).join('');
    if (window.lucide) lucide.createIcons();
}

async function toggleAutomation(key, value) {
    currentAutomations[key] = value;
    try {
        const res = await apiFetch('/api/automations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guild_id: getGuildId(), automations: currentAutomations })
        });
        const data = await res.json();
        showToast(data.ok ? 'Automação salva!' : 'Erro ao salvar.', data.ok ? 'success' : 'error');
    } catch {
        showToast('Salvo localmente. Bot offline.', 'info');
    }
}

/* ===========================
   NAVEGAÇÃO
   =========================== */

const PAGE_LOADERS = {
    'dashboard':    loadDashboard,
    'produtos':     loadProducts,
    'pedidos':      () => loadOrders('todos'),
    'clientes':     loadClients,
    'tickets':      loadTickets,
    'cupons':       loadCoupons,
    'afiliados':    loadAffiliates,
    'pagamentos':   loadPaymentMethodActive,
    'logs':         loadLogs,
    'automacoes':   loadAutomations,
};

let currentPage = 'dashboard';

function showPage(pageName) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const selectedPage = document.getElementById(`${pageName}-page`);
    if (selectedPage) selectedPage.classList.add('active');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageName);
    });
    document.querySelectorAll('.mobile-menu-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageName);
    });

    if (window.innerWidth < 768) document.getElementById('sidebar').classList.remove('active');
    document.querySelector('.main-content').scrollTop = 0;

    currentPage = pageName;
    if (PAGE_LOADERS[pageName]) PAGE_LOADERS[pageName]();
}

function reloadCurrentPage() {
    if (PAGE_LOADERS[currentPage]) PAGE_LOADERS[currentPage]();
}

/* ===========================
   MODAL & TOAST
   =========================== */

const modal      = document.getElementById('modal');
const modalClose = document.getElementById('modalClose');
const modalTitle = document.getElementById('modalTitle');
const modalBody  = document.getElementById('modalBody');

function showModal(title, content) {
    modalTitle.textContent = title;
    modalBody.innerHTML    = content;
    if (window.lucide) lucide.createIcons();
    modal.classList.add('show');
}

function closeModal() { modal.classList.remove('show'); }
modalClose.addEventListener('click', closeModal);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

function showToast(message, type = 'info') {
    const toast    = document.getElementById('toast');
    const toastMsg = document.getElementById('toastMessage');
    if (!toast || !toastMsg) return;
    const icons = {
        success: '<i data-lucide="check-circle"></i>',
        error:   '<i data-lucide="alert-circle"></i>',
        info:    '<i data-lucide="info"></i>',
    };
    toastMsg.innerHTML  = `${icons[type] || icons.info} <span>${message}</span>`;
    if (window.lucide) lucide.createIcons();
    toast.className     = `toast show ${type}`;
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => { toast.classList.remove('show'); }, 3500);
}

/* ===========================
   BUSCA EM TEMPO REAL
   =========================== */

document.getElementById('productSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    renderProducts(productsData.filter(p => p.name.toLowerCase().includes(q) || (p.category || '').toLowerCase().includes(q)));
});

document.getElementById('logsSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    renderLogs(logsData.filter(l => (l.description || '').toLowerCase().includes(q) || (l.event_type || '').toLowerCase().includes(q)));
});

/* ===========================
   FILTRO DE PEDIDOS
   =========================== */

document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        loadOrders(btn.dataset.filter);
    });
});

/* ===========================
   EVENTOS DE CLIQUE
   =========================== */

document.getElementById('addProductBtn')?.addEventListener('click', openAddProductModal);
document.getElementById('addCouponBtn')?.addEventListener('click', openAddCouponModal);
document.getElementById('addAffiliateBtn')?.addEventListener('click', openAddAffiliateModal);
document.getElementById('saveSettingsBtn')?.addEventListener('click', saveSettings);

document.addEventListener('click', (e) => {
    const card = e.target.closest('.integration-card');
    if (!card) return;
    const btn = e.target.closest('.btn');
    if (!btn || btn.textContent.trim() !== 'Configurar') return;
    const titulo = card.querySelector('h4')?.textContent.trim();
    if (titulo === 'PIX')          abrirConfigPix();
    if (titulo === 'Mercado Pago') abrirConfigMercadoPago();
});

/* ===========================
   NAVEGAÇÃO
   =========================== */

const menuToggle = document.getElementById('menuToggle');
const sidebar    = document.getElementById('sidebar');

menuToggle.addEventListener('click', () => sidebar.classList.toggle('active'));
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); showPage(item.dataset.page); });
});
document.querySelectorAll('.mobile-menu-item').forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); showPage(item.dataset.page); });
});

/* ===========================
   INICIALIZAÇÃO
   =========================== */

function startApp() {
    showPage('dashboard');
    loadServerInfo();
    setupPaymentMethodToggles();
    setupServerDropdown();
    setInterval(loadServerInfo, 60000);
}

checkAuthAndInit();
