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
