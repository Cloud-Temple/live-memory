/**
 * Live Memory - Bank (panneau bas-droit, onglets de fichiers)
 */

function renderBankTabs() {
    const tabsEl = document.getElementById('bankTabs');
    const countEl = document.getElementById('bankCount');
    const files = app.bankFiles;

    countEl.textContent = files.length > 0 ? `(${files.length})` : '';

    if (files.length === 0) {
        tabsEl.innerHTML = '';
        document.getElementById('bankContent').innerHTML = '<div class="empty-state">📘 Aucun fichier bank consolidé</div>';
        return;
    }

    // LM2-01 fix : le `${name}` final dans innerHTML était NON ÉCHAPPÉ —
    // un nom de fichier malicieux (`<img src=x onerror=...>`) injecté par
    // un opérateur compromis (ou un LLM dérivant) exécutait du JS arbitraire
    // dans le navigateur de chaque admin ouvrant /live. Échappement systématique
    // + le serveur refuse maintenant les caractères dangereux (LM2-12 fix).
    tabsEl.innerHTML = files.map(f => {
        const name = f.filename || f;
        const safeName = esc(name);
        const active = app.currentBankFile === name ? 'active' : '';
        return `<div class="bank-tab ${active}" onclick="selectBank('${safeName}')">${safeName}</div>`;
    }).join('');

    // Si aucun fichier sélectionné, sélectionner le premier
    if (!app.currentBankFile && files.length > 0) {
        selectBank(files[0].filename || files[0]);
    }
}

async function selectBank(filename) {
    app.currentBankFile = filename;

    // Mettre à jour les onglets actifs
    document.querySelectorAll('.bank-tab').forEach(t => {
        t.classList.toggle('active', t.textContent === filename);
    });

    const el = document.getElementById('bankContent');
    el.innerHTML = '<div class="empty-state">Chargement…</div>';

    try {
        const r = await apiLoadBankFile(app.spaceId, filename);
        if (r.status === 'ok' && r.content) {
            el.innerHTML = `<div class="md-content">${md(r.content)}</div>`;
        } else {
            el.innerHTML = `<div class="empty-state">❌ ${esc(r.message||'Erreur')}</div>`;
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            el.innerHTML = `<div class="empty-state">❌ ${esc(e.message)}</div>`;
        }
    }
}
