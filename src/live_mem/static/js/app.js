/**
 * Live Memory - Orchestrateur principal
 * Login → sélection espace → chargement → auto-refresh intelligent
 */

// ═══════════════ AUTH ═══════════════

function showLogin(msg='') {
    document.getElementById('loginOverlay').classList.remove('hidden');
    document.getElementById('loginError').textContent = msg ? `❌ ${msg}` : '';
    document.getElementById('loginToken').focus();
}
function hideLogin() { document.getElementById('loginOverlay').classList.add('hidden'); }

async function doLogin() {
    const input = document.getElementById('loginToken');
    const btn = document.getElementById('loginBtn');
    const err = document.getElementById('loginError');
    const token = input.value.trim();
    if (!token) { err.textContent = '❌ Token requis.'; return; }

    btn.disabled = true; btn.textContent = 'Connexion…'; err.textContent = '';
    try {
        const r = await fetch('/api/spaces', { headers: { 'Authorization': `Bearer ${token}` } });
        if (r.status === 401) { err.textContent = '❌ Token invalide.'; return; }
        if (!r.ok) { err.textContent = `❌ Erreur (${r.status}).`; return; }
        const data = await r.json();
        if (data.status !== 'ok') { err.textContent = `❌ ${data.message||'Erreur'}`; return; }

        setAuthToken(token);
        hideLogin();
        input.value = '';
        fillSpaceSelect(data.spaces || []);
    } catch { err.textContent = '❌ Serveur injoignable.'; }
    finally { btn.disabled = false; btn.textContent = 'Se connecter'; }
}

function doLogout() {
    clearAuthToken(); stopRefresh();
    app.spaceId = null; app.info = null; app.notes = []; app.bankFiles = [];
    app.currentBankFile = null; app.agentColors = {};
    document.getElementById('panelLeft').style.display = 'none';
    document.getElementById('panelRight').style.display = 'none';
    document.getElementById('placeholder').style.display = 'flex';
    document.getElementById('spaceSelect').innerHTML = '<option value="">-- Espace --</option>';
    showLogin();
}

async function checkToken() {
    const token = getAuthToken();
    if (!token) { showLogin(); return; }
    try {
        const r = await apiLoadSpaces();
        if (r.status === 'ok') { hideLogin(); fillSpaceSelect(r.spaces || []); }
        else showLogin('Token expiré.');
    } catch (e) {
        if (e.message !== 'Unauthorized') showLogin('Serveur injoignable.');
    }
}

function fillSpaceSelect(spaces) {
    const sel = document.getElementById('spaceSelect');
    sel.innerHTML = '<option value="">-- Espace --</option>';
    // Issue #8 : les <option> natifs ne supportent pas text-overflow:ellipsis,
    // on tronque donc la description côté JS pour éviter que le dropdown
    // ne déborde du viewport quand un espace a une description longue.
    const MAX_DESC = 70;
    spaces.forEach(s => {
        const o = document.createElement('option');
        o.value = s.space_id;
        let desc = '';
        if (s.description) {
            desc = s.description.length > MAX_DESC
                ? s.description.slice(0, MAX_DESC).trimEnd() + '…'
                : s.description;
            // Description complète accessible en tooltip natif
            o.title = s.description;
        }
        o.textContent = s.space_id + (desc ? ' — ' + desc : '');
        sel.appendChild(o);
    });
}

// ═══════════════ CHARGEMENT ESPACE ═══════════════

async function loadSpace(spaceId) {
    if (!spaceId) {
        stopRefresh();
        app.spaceId = null;
        document.getElementById('panelLeft').style.display = 'none';
        document.getElementById('panelRight').style.display = 'none';
        document.getElementById('placeholder').style.display = 'flex';
        return;
    }

    app.spaceId = spaceId;
    app.currentBankFile = null;
    app._noteHash = '';
    app._bankHash = '';

    document.getElementById('placeholder').style.display = 'none';
    document.getElementById('panelLeft').style.display = 'flex';
    document.getElementById('panelRight').style.display = 'flex';

    // Chargement initial complet
    await refresh(true);
    startRefresh();
}

// ═══════════════ REFRESH INTELLIGENT ═══════════════

async function refresh(force = false) {
    if (!app.spaceId) return;
    updateStatus('refresh');

    try {
        const [notesR, bankR, infoR] = await Promise.all([
            apiLoadNotes(app.spaceId),
            apiLoadBankList(app.spaceId),
            apiLoadSpaceInfo(app.spaceId),
        ]);

        // Détection changement notes
        const newNotes = notesR.status === 'ok' ? (notesR.notes || []) : app.notes;
        const noteHash = newNotes.length + ':' + (newNotes[0]?.timestamp || '');
        const notesChanged = noteHash !== app._noteHash;

        // Détection changement bank
        const newBank = bankR.status === 'ok' ? (bankR.files || []) : app.bankFiles;
        const bankHash = newBank.map(f => f.filename).join(',');
        const bankChanged = bankHash !== app._bankHash;

        // Info (toujours mettre à jour)
        app.info = infoR.status === 'ok' ? infoR : app.info;

        // Mettre à jour seulement ce qui a changé
        if (notesChanged || force) {
            app.notes = newNotes;
            app._noteHash = noteHash;
            renderLive();
        }

        if (bankChanged || force) {
            app.bankFiles = newBank;
            app._bankHash = bankHash;
            renderBankTabs();
        }

        // Dashboard toujours mis à jour (léger)
        renderDashboard();

        updateStatus('ok');
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Refresh:', e);
            updateStatus('error');
        }
    }
}

function updateStatus(s) {
    const el = document.getElementById('globalStatus');
    if (!el) return;
    const dot = el.querySelector('.dot');
    const txt = el.querySelector('.status-text');
    if (s === 'ok') {
        dot.className = 'dot'; dot.style.background = '#4CAF50';
        txt.textContent = fmtTime(new Date().toISOString());
    } else if (s === 'refresh') {
        dot.className = 'dot'; dot.style.background = '#f39c12';
        txt.textContent = '…';
    } else {
        dot.className = 'dot paused'; dot.style.background = '#e74c3c';
        txt.textContent = 'erreur';
    }
}

// ═══════════════ AUTO-REFRESH ═══════════════

function startRefresh() {
    stopRefresh();
    if (app.refreshInterval <= 0) return;
    app.refreshTimer = setInterval(() => refresh(), app.refreshInterval * 1000);
}

function stopRefresh() {
    if (app.refreshTimer) { clearInterval(app.refreshTimer); app.refreshTimer = null; }
}

// ═══════════════ RESIZER ═══════════════

function setupResizer() {
    const resizer = document.getElementById('resizer');
    const livePanel = document.getElementById('livePanel');
    const bankPanel = document.getElementById('bankPanel');
    const panelRight = document.getElementById('panelRight');
    let dragging = false, startY = 0, startLiveH = 0;

    resizer.addEventListener('mousedown', e => {
        e.preventDefault(); dragging = true; startY = e.clientY;
        startLiveH = livePanel.offsetHeight;
        resizer.classList.add('dragging');
        document.body.style.cursor = 'row-resize';
        document.body.style.userSelect = 'none';
    });
    document.addEventListener('mousemove', e => {
        if (!dragging) return;
        const delta = e.clientY - startY;
        const totalH = panelRight.offsetHeight - resizer.offsetHeight;
        const newLiveH = Math.min(totalH - 150, Math.max(200, startLiveH + delta));
        livePanel.style.flex = 'none';
        livePanel.style.height = newLiveH + 'px';
        bankPanel.style.flex = '1';
    });
    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
}

// ═══════════════ INIT ═══════════════

document.addEventListener('DOMContentLoaded', () => {
    // Login
    document.getElementById('loginBtn').addEventListener('click', doLogin);
    document.getElementById('loginToken').addEventListener('keydown', e => { if (e.key==='Enter') doLogin(); });
    document.getElementById('logoutBtn').addEventListener('click', doLogout);

    // Sélection espace → chargement auto
    document.getElementById('spaceSelect').addEventListener('change', function() {
        loadSpace(this.value);
    });

    // Refresh interval
    document.getElementById('refreshInterval').addEventListener('change', function() {
        app.refreshInterval = parseInt(this.value);
        startRefresh();
        const dot = document.querySelector('#globalStatus .dot');
        if (dot) dot.className = app.refreshInterval > 0 ? 'dot' : 'dot paused';
    });

    // Resizer
    setupResizer();

    // Go
    checkToken();
});
