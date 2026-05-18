/**
 * Live Memory Admin — v4
 * CSP-safe: ZERO inline onclick — all via data-action + event delegation
 * Dashboard UX: auto-execute, tables, modals, smart dropdowns
 */

const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;');
function fmtSize(b) { if(!b)return''; if(b<1024)return b+' B'; if(b<1048576)return(b/1024).toFixed(1)+' KB'; return(b/1048576).toFixed(1)+' MB'; }
function fmtDate(iso) { if(!iso)return''; try{return new Date(iso).toLocaleString('fr-FR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'})}catch{return iso;} }
function fmtTime(iso) { if(!iso)return''; try{return new Date(iso).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return iso;} }

// ═══════════════ DATA CACHE ═══════════════
const cache = { spaces:[], tokens:[], backups:[], bankFiles:{}, agents:{} };
async function loadSpaces() { try{const r=await callTool('space_list',{});cache.spaces=r.spaces||[];}catch{cache.spaces=[];} return cache.spaces; }
async function loadTokens() { try{const r=await callTool('admin_list_tokens',{include_revoked:true});cache.tokens=r.tokens||[];}catch{cache.tokens=[];} return cache.tokens; }
async function loadBackups(sid='') { try{const r=await callTool('backup_list',{space_id:sid});cache.backups=r.backups||[];}catch{cache.backups=[];} return cache.backups; }
async function loadBankFiles(sid) { if(!sid)return[]; try{const r=await callTool('bank_list',{space_id:sid});cache.bankFiles[sid]=r.files||[];}catch{cache.bankFiles[sid]=[];} return cache.bankFiles[sid]; }

const CATS = {
    dashboard:{icon:'📊',label:'Dashboard'}, spaces:{icon:'📂',label:'Spaces'}, tokens:{icon:'🔑',label:'Tokens'},
    explorer:{icon:'🔍',label:'Explorer'}, backups:{icon:'💾',label:'Backups'}, graph:{icon:'🌉',label:'Graph Bridge'},
    maintenance:{icon:'🧹',label:'Maintenance'},
};
let activeCat = 'dashboard';

// ═══════════════ LOGIN ═══════════════
function showLogin(msg=''){document.getElementById('loginOverlay').classList.remove('hidden');document.getElementById('loginError').textContent=msg?`❌ ${msg}`:'';document.getElementById('loginToken').focus();}
function hideLogin(){document.getElementById('loginOverlay').classList.add('hidden');}
async function doLogin(){
    const input=document.getElementById('loginToken'),btn=document.getElementById('loginBtn'),err=document.getElementById('loginError'),token=input.value.trim();
    if(!token){err.textContent='❌ Token required.';return;}
    btn.disabled=true;btn.textContent='Signing in…';err.textContent='';
    try{const r=await adminLogin(token);if(r.status!=='ok'){err.textContent=`❌ ${r.message||'Invalid'}`;return;}hideLogin();input.value='';document.getElementById('headerUser').textContent=r.client_name||'';await Promise.all([loadSpaces(),loadTokens()]);buildSidebar();showCategory('dashboard');}catch{err.textContent='❌ Server unreachable.';}finally{btn.disabled=false;btn.textContent='Sign in';}
}
async function doLogout(){await adminLogout();document.getElementById('headerUser').textContent='';showLogin();}

// ═══════════════ SIDEBAR ═══════════════
function buildSidebar(){
    const nav=document.getElementById('sidebarNav');
    nav.innerHTML=Object.entries(CATS).map(([k,c])=>`<button class="sidebar-btn${k===activeCat?' active':''}" data-action="nav" data-cat="${k}"><span class="sidebar-icon">${c.icon}</span>${esc(c.label)}</button>`).join('');
}

function showCategory(cat){
    activeCat=cat;
    document.querySelectorAll('.sidebar-btn').forEach(b=>b.classList.toggle('active',b.dataset.cat===cat));
    const c=document.getElementById('content');
    c.innerHTML='<div class="page-loading">Loading…</div>';
    ({dashboard:renderDashboard,spaces:renderSpaces,tokens:renderTokens,explorer:renderExplorer,backups:renderBackups,graph:renderGraph,maintenance:renderMaintenance}[cat]||renderDashboard)();
}

function spaceSelect(id, required=true, includeEmpty=false){
    const opts=cache.spaces.map(s=>`<option value="${esc(s.space_id)}">${esc(s.space_id)}${s.description?' — '+esc(s.description.substring(0,40)):''}</option>`);
    // Always show a placeholder first so the user must actively select
    const empty=includeEmpty?'<option value="">— all spaces —</option>':'<option value="">— choose a space —</option>';
    return `<select class="form-input" id="${id}">${empty}${opts.join('')}</select>`;
}

// ═══════════════ GLOBAL EVENT DELEGATION (CSP-safe) ═══════════════
document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    e.preventDefault();
    const a = btn.dataset.action;
    const d = btn.dataset;

    // Navigation
    if (a === 'nav') { showCategory(d.cat); return; }

    // Run tool and show result in modal
    if (a === 'run') { runAndShow(d.tool, JSON.parse(d.args || '{}')); return; }

    // Confirm + run dangerous action
    if (a === 'confirm') {
        if (!confirm(d.msg || 'Are you sure?')) return;
        callTool(d.tool, JSON.parse(d.args || '{}')).then(r => {
            if (r.status === 'error') alert(r.message || 'Error');
            else showCategory(activeCat);
        });
        return;
    }

    // Specific actions
    if (a === 'create-space') { showCreateSpace(); return; }
    if (a === 'create-token') { showCreateToken(); return; }
    if (a === 'update-token') { showUpdateToken(d.hash, d.name); return; }
    if (a === 'explore-space') {
        showCategory('explorer');
        setTimeout(() => {
            const sel = document.getElementById('explorerSpace');
            if (sel) { sel.value = d.space; sel.dispatchEvent(new Event('change')); }
        }, 150);
        return;
    }
    if (a === 'read-bank') { readBankFile(d.space, d.file); return; }
    if (a === 'create-backup') { createBackup(); return; }
    if (a === 'backup-all') { backupAll(); return; }
    if (a === 'graph-push') { graphPush(d.space); return; }
    if (a === 'close-modal') { closeModal(); return; }

    // Maintenance actions
    if (a === 'maint-consolidate') { maintConsolidate(); return; }
    if (a === 'maint-compact') { maintCompact(); return; }
    if (a === 'maint-repair') { maintRepair(); return; }
    if (a === 'maint-gc') { maintGc(); return; }
    if (a === 'maint-purge') { maintPurge(); return; }

    // Dashboard health drill-down
    if (a === 'dash-health') { showHealthModal(); return; }

    // Upload rules
    if (a === 'upload-rules') { showUploadRules(d.space); return; }
});

// ═══════════════ DASHBOARD ═══════════════
// Cache health data for modal drill-down
let _dashHealth = {};

async function renderDashboard(){
    const c=document.getElementById('content');
    c.innerHTML='<div class="page"><h2 class="page-title">📊 Dashboard</h2><div class="dash-cards" id="dashCards"><div class="page-loading">Loading…</div></div><div class="dash-identity" id="dashIdentity"></div></div>';
    const [health,whoami,spaces,tokens]=await Promise.all([
        callTool('system_health',{}).catch(()=>({})),
        callTool('system_whoami',{}).catch(()=>({})),
        loadSpaces(),loadTokens()
    ]);
    _dashHealth = health;
    const el=document.getElementById('dashCards');if(!el)return;
    const hst=health.status||'?', hcls=hst==='healthy'?'green':hst==='degraded'?'orange':'red';
    const s3=health.services?.s3?.status||'?', llm=health.services?.llmaas?.status||'?';
    const act=tokens.filter(t=>!t.revoked).length;
    el.innerHTML=`
        <div class="dash-card clickable" data-action="dash-health"><div class="dash-card-icon">❤️</div><div class="dash-card-body">
            <div class="dash-card-value"><span class="badge ${hcls}">${esc(hst)}</span></div>
            <div class="dash-card-label">Health</div>
            <div class="dash-card-detail">S3: <span class="badge ${s3==='ok'?'green':'red'}">${esc(s3)}</span> · LLM: <span class="badge ${llm==='ok'?'green':llm==='warning'?'orange':'red'}">${esc(llm)}</span></div>
        </div></div>
        <div class="dash-card clickable" data-action="nav" data-cat="spaces"><div class="dash-card-icon">📂</div><div class="dash-card-body">
            <div class="dash-card-value">${spaces.length}</div><div class="dash-card-label">Spaces</div><div class="dash-card-detail">Click to manage →</div>
        </div></div>
        <div class="dash-card clickable" data-action="nav" data-cat="tokens"><div class="dash-card-icon">🔑</div><div class="dash-card-body">
            <div class="dash-card-value">${act} <span style="color:#666;font-size:.7rem">/ ${tokens.length}</span></div><div class="dash-card-label">Active Tokens</div><div class="dash-card-detail">${tokens.length-act} revoked →</div>
        </div></div>
        <div class="dash-card"><div class="dash-card-icon">🧠</div><div class="dash-card-body">
            <div class="dash-card-value">${health.version||'?'}</div><div class="dash-card-label">Version</div><div class="dash-card-detail">Uptime: ${health.uptime_seconds?Math.round(health.uptime_seconds/60)+'min':'?'}</div>
        </div></div>`;

    // ── Compact identity bar ──
    const idEl=document.getElementById('dashIdentity');if(!idEl)return;
    const perms=(whoami.permissions||[]).map(p=>`<span class="badge green">${esc(p)}</span>`).join(' ');
    const authBadge=`<span class="badge purple">${esc(whoami.auth_type||'?')}</span>`;
    const warn=whoami.note?` · <span style="color:var(--warn)">⚠️ ${esc(whoami.note)}</span>`:'';
    idEl.innerHTML=`👤 <strong>${esc(whoami.client_name||'?')}</strong> ${authBadge} · ${perms}${warn}`;
}

function showHealthModal(){
    const h=_dashHealth;
    const hst=h.status||'?', hcls=hst==='healthy'?'green':hst==='degraded'?'orange':'red';
    let html=`<div class="pretty-table">`;
    html+=`<div class="pretty-row"><span class="pretty-k">Status</span><span class="pretty-v"><span class="badge ${hcls}">${esc(hst)}</span></span></div>`;
    html+=`<div class="pretty-row"><span class="pretty-k">Version</span><span class="pretty-v">${esc(h.version||'?')}</span></div>`;
    html+=`<div class="pretty-row"><span class="pretty-k">Uptime</span><span class="pretty-v">${h.uptime_seconds?Math.round(h.uptime_seconds/60)+' min':'?'}</span></div>`;
    html+=`<div class="pretty-row"><span class="pretty-k">Spaces</span><span class="pretty-v">${h.spaces_count??'?'}</span></div>`;
    if(h.services){for(const [name,svc] of Object.entries(h.services)){
        const st=svc.status||'?',badge=st==='ok'?'green':st==='error'?'red':'orange';
        html+=`<div class="pretty-row"><span class="pretty-k">${esc(name)}</span><span class="pretty-v"><span class="badge ${badge}">${esc(st)}</span>${svc.latency_ms?' · '+svc.latency_ms+'ms':''}${svc.model?' · '+esc(svc.model):''}${svc.bucket?' · '+esc(svc.bucket):''}</span></div>`;
    }}
    html+=`</div>`;
    showModal('❤️ Health Details',html,'Close',()=>true);
}

// ═══════════════ SPACES ═══════════════
async function renderSpaces(){
    const c=document.getElementById('content');
    c.innerHTML='<div class="page"><div class="page-header"><h2 class="page-title">📂 Spaces</h2><button class="btn-action green" data-action="create-space">➕ Create Space</button></div><div id="spacesContent"><div class="page-loading">Loading…</div></div></div>';
    const spaces=await loadSpaces();
    const el=document.getElementById('spacesContent');if(!el)return;
    if(!spaces.length){el.innerHTML='<div class="empty">No spaces found.</div>';return;}
    el.innerHTML=`<table class="data-table"><thead><tr><th>Space ID</th><th>Description</th><th>Owner</th><th>Notes</th><th>Bank</th><th>Actions</th></tr></thead><tbody>${
        spaces.map(s=>{
            const sid=esc(s.space_id);
            return `<tr>
                <td><strong>${sid}</strong></td>
                <td class="text-muted">${esc(s.description||'')}</td>
                <td class="text-muted">${esc(s.owner||'—')}</td>
                <td>${s.live_notes_count??'—'}</td>
                <td>${s.bank_files_count??'—'}</td>
                <td class="actions-cell">
                    <button class="btn-sm" data-action="run" data-tool="space_info" data-args='{"space_id":"${sid}"}'>Info</button>
                    <button class="btn-sm" data-action="run" data-tool="space_rules" data-args='{"space_id":"${sid}"}'>Rules</button>
                    <button class="btn-sm blue" data-action="explore-space" data-space="${sid}">Explore</button>
                    <button class="btn-sm red" data-action="confirm" data-tool="space_delete" data-args='{"space_id":"${sid}","confirm":true}' data-msg="Delete space ${sid} and ALL its data?">Delete</button>
                </td></tr>`;
        }).join('')
    }</tbody></table>`;
}

function showCreateSpace(){
    showModal('➕ Create Space',`
        <div class="form-group"><label class="form-label">Space ID <span class="req">*</span></label><input class="form-input" data-1p-ignore id="m_space_id" placeholder="my-project"></div>
        <div class="form-group"><label class="form-label">Description <span class="req">*</span></label><input class="form-input" data-1p-ignore id="m_desc"></div>
        <div class="form-group"><label class="form-label">Owner</label><input class="form-input" data-1p-ignore id="m_owner"></div>
        <div class="form-group"><label class="form-label">Rules (Markdown)</label><textarea class="form-input" id="m_rules" rows="6" placeholder="Leave empty for default rules"></textarea></div>
    `,'Create Space',async()=>{
        const sid=gv('m_space_id'),desc=gv('m_desc');if(!sid||!desc)return false;
        const r=await callTool('space_create',{space_id:sid,description:desc,owner:gv('m_owner'),rules:gv('m_rules')});
        if(r.status==='created'){cache.spaces=[];renderSpaces();return true;}
        alert(r.message||'Error');return false;
    });
}

// ═══════════════ TOKENS ═══════════════
async function renderTokens(){
    const c=document.getElementById('content');
    c.innerHTML='<div class="page"><div class="page-header"><h2 class="page-title">🔑 Tokens</h2><button class="btn-action green" data-action="create-token">➕ Create Token</button></div><div id="tokensContent"><div class="page-loading">Loading…</div></div></div>';
    const tokens=await loadTokens();
    const el=document.getElementById('tokensContent');if(!el)return;
    if(!tokens.length){el.innerHTML='<div class="empty">No tokens found.</div>';return;}
    el.innerHTML=`<table class="data-table"><thead><tr><th>Name</th><th>Status</th><th>Permissions</th><th>Spaces</th><th>Email</th><th>Actions</th></tr></thead><tbody>${
        tokens.map(t=>{
            const h=esc(t.hash||''), perms=(t.permissions||[]).join(', '), sids=t.space_ids||[];
            const spTxt=sids.length?sids.join(', '):'<span class="text-muted">all</span>';
            const n=esc(t.name);
            return `<tr class="${t.revoked?'row-muted':''}">
                <td><strong>${n}</strong><br><span class="mono text-muted" style="font-size:.58rem">${h.substring(0,28)}…</span></td>
                <td><span class="badge ${t.revoked?'red':'green'}">${t.revoked?'revoked':'active'}</span></td>
                <td><span class="badge purple">${esc(perms)}</span></td>
                <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;font-size:.7rem">${spTxt}</td>
                <td class="text-muted">${esc(t.email||'—')}</td>
                <td class="actions-cell">${t.revoked?
                    `<button class="btn-sm red" data-action="confirm" data-tool="admin_delete_token" data-args='{"token_hash":"${h}"}' data-msg="Permanently delete token ${n}?">🗑️ Delete</button>`:
                    `<button class="btn-sm" data-action="update-token" data-hash="${h}" data-name="${n}">✏️ Update</button>
                     <button class="btn-sm orange" data-action="confirm" data-tool="admin_revoke_token" data-args='{"token_hash":"${h}"}' data-msg="Revoke token ${n}?">🚫 Revoke</button>`
                }</td></tr>`;
        }).join('')
    }</tbody></table>`;
}

function showCreateToken(){
    showModal('➕ Create Token',`
        <div class="form-group"><label class="form-label">Name <span class="req">*</span></label><input class="form-input" data-1p-ignore id="m_name" placeholder="agent-cline"></div>
        <div class="form-group"><label class="form-label">Permissions <span class="req">*</span></label><select class="form-input" id="m_perms"><option value="read">read</option><option value="read,write" selected>read,write</option><option value="read,write,manage">read,write,manage</option><option value="read,write,manage,admin">read,write,manage,admin</option></select></div>
        <div class="form-group"><label class="form-label">Space IDs</label><input class="form-input" data-1p-ignore id="m_sids" placeholder="CSV, or * for all current spaces"></div>
        <div class="form-group"><label class="form-label">Email</label><input class="form-input" data-1p-ignore id="m_email"></div>
        <div class="form-group"><label class="form-label">Expires in (days)</label><input class="form-input" data-1p-ignore type="number" id="m_exp" value="0" placeholder="0 = never"></div>
    `,'Create Token',async()=>{
        const name=gv('m_name'),perms=gv('m_perms');if(!name)return false;
        const args={name,permissions:perms,space_ids:gv('m_sids'),email:gv('m_email')};
        const exp=parseInt(gv('m_exp'));if(exp>0)args.expires_in_days=exp;
        const r=await callTool('admin_create_token',args);
        if(r.token){
            cache.tokens=[];closeModal();
            showModal('⚠️ Token Created — Save Now!',`
                <p style="color:var(--danger);font-weight:600;margin-bottom:1rem">This token will NOT be shown again!</p>
                <code style="display:block;padding:.8rem;background:rgba(0,0,0,.4);border-radius:6px;word-break:break-all;user-select:all;font-size:.9rem;color:#fff">${esc(r.token)}</code>
                <p style="margin-top:.8rem;color:#888;font-size:.8rem">Client: ${esc(r.client_name||name)} · Permissions: ${esc(perms)}</p>
            `,'I have saved it',()=>{renderTokens();return true;});
            return false;
        }
        alert(r.message||'Error');return false;
    });
}

function showUpdateToken(hash,name){
    // Find current token data to pre-check its spaces
    const tok = cache.tokens.find(t => t.hash === hash);
    const currentSpaces = new Set(tok?.space_ids || []);
    const allSpaces = cache.spaces.map(s => s.space_id);

    // Build checkbox grid for spaces
    const spacesHTML = allSpaces.length ? allSpaces.map(sid => {
        const checked = currentSpaces.has(sid) ? 'checked' : '';
        const id = `m_sp_${sid.replace(/[^a-zA-Z0-9]/g,'_')}`;
        return `<label class="space-chip ${checked?'active':''}" data-space="${esc(sid)}"><input type="checkbox" data-1p-ignore ${checked} id="${id}" data-sid="${esc(sid)}" class="space-cb"> ${esc(sid)}</label>`;
    }).join('') : '<span class="text-muted">No spaces available</span>';

    showModal(`✏️ Update: ${name}`,`
        <div class="form-group"><label class="form-label">Permissions</label><select class="form-input" id="m_perms"><option value="">— no change —</option><option value="read">read</option><option value="read,write">read,write</option><option value="read,write,manage">read,write,manage</option><option value="read,write,manage,admin">read,write,manage,admin</option></select></div>
        <div class="form-group"><label class="form-label">Spaces access</label><div class="form-hint">Toggle to add/remove. Green = has access.</div><div class="space-chips" id="m_spaces">${spacesHTML}</div></div>
        <div class="form-group"><label class="form-label">Email</label><input class="form-input" data-1p-ignore id="m_email"></div>
    `,'Update Token',async()=>{
        const args={token_hash:hash};
        const p=gv('m_perms');if(p)args.permissions=p;
        const e=gv('m_email');if(e)args.email=e;

        // Calculate delta from checkboxes
        const toAdd=[], toRemove=[];
        document.querySelectorAll('#m_spaces .space-cb').forEach(cb=>{
            const sid=cb.dataset.sid;
            if(cb.checked && !currentSpaces.has(sid)) toAdd.push(sid);
            if(!cb.checked && currentSpaces.has(sid)) toRemove.push(sid);
        });
        if(toAdd.length) args.space_ids_add=toAdd.join(',');
        if(toRemove.length) args.space_ids_remove=toRemove.join(',');

        const res=await callTool('admin_update_token',args);
        if(res.status==='ok'){cache.tokens=[];renderTokens();return true;}
        alert(res.message||'Error');return false;
    });

    // Add visual toggle for chips
    document.querySelectorAll('#m_spaces .space-cb').forEach(cb=>{
        cb.addEventListener('change',()=>{
            cb.closest('.space-chip').classList.toggle('active',cb.checked);
        });
    });
}

// ═══════════════ EXPLORER ═══════════════
async function renderExplorer(){
    const c=document.getElementById('content');
    c.innerHTML=`<div class="page"><div class="page-header"><h2 class="page-title">🔍 Explorer</h2><div>${spaceSelect('explorerSpace')}</div></div><div id="explorerContent"><div class="empty">Select a space to explore.</div></div></div>`;
    document.getElementById('explorerSpace').addEventListener('change',async function(){
        const sid=this.value,el=document.getElementById('explorerContent');
        if(!sid){el.innerHTML='<div class="empty">Select a space.</div>';return;}
        el.innerHTML='<div class="page-loading">Loading…</div>';
        const [notes,bank]=await Promise.all([callTool('live_read',{space_id:sid,limit:30}).catch(()=>({notes:[]})),callTool('bank_list',{space_id:sid}).catch(()=>({files:[]}))]);
        const nl=notes.notes||[],fl=bank.files||[];
        el.innerHTML=`<div class="explorer-grid">
            <div class="explorer-col"><h3>📝 Live Notes <span class="badge blue">${nl.length}</span></h3>
                ${nl.length?nl.map(n=>`<div class="note-card"><div class="note-meta"><span class="badge blue">${esc(n.category||'?')}</span> <strong>${esc(n.agent||'?')}</strong> <span class="text-muted">${fmtTime(n.timestamp)}</span></div><div class="note-text">${esc((n.content||'').substring(0,300))}${(n.content||'').length>300?'…':''}</div></div>`).join(''):'<div class="empty">No live notes.</div>'}
            </div>
            <div class="explorer-col"><h3>📘 Bank Files <span class="badge green">${fl.length}</span></h3>
                ${fl.length?`<table class="data-table compact"><thead><tr><th>File</th><th>Size</th><th></th></tr></thead><tbody>${fl.map(f=>`<tr><td><strong>${esc(f.filename)}</strong></td><td class="text-muted">${fmtSize(f.size)}</td><td><button class="btn-sm" data-action="read-bank" data-space="${esc(sid)}" data-file="${esc(f.filename)}">📖 Read</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No bank files.</div>'}
                <div id="bankFileContent"></div>
            </div></div>`;
    });
}

async function readBankFile(sid,filename){
    const el=document.getElementById('bankFileContent');if(!el)return;
    el.innerHTML='<div class="page-loading">Loading…</div>';
    const r=await callTool('bank_read',{space_id:sid,filename:filename});
    el.innerHTML=r.content?`<div class="file-preview"><div class="file-preview-header">${esc(filename)} (${fmtSize(r.size)})</div><pre>${esc(r.content)}</pre></div>`:`<div class="empty">${esc(r.message||'Error')}</div>`;
}

// ═══════════════ BACKUPS ═══════════════
async function renderBackups(){
    const c=document.getElementById('content');
    c.innerHTML=`<div class="page"><div class="page-header"><h2 class="page-title">💾 Backups</h2><div style="display:flex;gap:.5rem;align-items:center">${spaceSelect('backupSpace',true)}<button class="btn-action green" data-action="create-backup">➕ Create</button><button class="btn-action blue" data-action="backup-all">💾 Backup All</button></div></div><div id="backupsContent"><div class="page-loading">Loading…</div></div></div>`;
    const backups=await loadBackups('');
    renderBackupTable(backups);
}
function renderBackupTable(backups){
    const el=document.getElementById('backupsContent');if(!el)return;
    if(!backups.length){el.innerHTML='<div class="empty">No backups found.</div>';return;}
    // Build columns dynamically based on what the API actually provides
    const hasFiles = backups.some(b => b.files_count || b.files || b.total_files);
    const hasSize = backups.some(b => b.total_size || b.size);
    const hasDesc = backups.some(b => b.description);
    el.innerHTML=`<table class="data-table"><thead><tr><th>Space</th><th>Date</th>${hasFiles?'<th>Files</th>':''}${hasSize?'<th>Size</th>':''}${hasDesc?'<th>Description</th>':''}<th>Actions</th></tr></thead><tbody>${
        backups.map(b=>{
            const id=esc(b.backup_id||b.id||'?');
            const space = esc(b.space_id || id.split('/')[0] || '?');
            let rawTs = b.timestamp || b.created_at || '';
            if (!rawTs && id.includes('/')) rawTs = id.split('/').pop();
            const date = rawTs.replace(/T(\d{2})-(\d{2})-(\d{2})/, 'T$1:$2:$3');
            return `<tr>
                <td><strong>${space}</strong><br><span class="mono text-muted" style="font-size:.62rem">${id}</span></td>
                <td>${fmtDate(date)||esc(date)||'—'}</td>
                ${hasFiles?`<td>${b.files_count??b.files??b.total_files??'—'}</td>`:''}
                ${hasSize?`<td class="text-muted">${fmtSize(b.total_size||b.size)}</td>`:''}
                ${hasDesc?`<td class="text-muted">${esc(b.description||'')}</td>`:''}
                <td class="actions-cell">
                    <button class="btn-sm blue" data-action="confirm" data-tool="backup_restore" data-args='{"backup_id":"${id}","confirm":true}' data-msg="Restore ${id}? Space must not exist!">♻️ Restore</button>
                    <button class="btn-sm red" data-action="confirm" data-tool="backup_delete" data-args='{"backup_id":"${id}","confirm":true}' data-msg="Delete backup ${id}?">🗑️ Delete</button>
                </td></tr>`;
        }).join('')
    }</tbody></table>`;
}
async function backupAll(){
    if(!confirm('Backup ALL spaces? This may take a while.'))return;
    const desc=prompt('Description for all backups (optional):','');
    showModal('💾 Backup All','<div class="page-loading">Backing up all spaces…</div>',null,null);
    const r=await callTool('backup_create',{space_id:'',description:desc||''});
    closeModal();
    showModal('💾 Backup All',renderPretty('backup_create_all',r),'Close',()=>{renderBackups();return true;});
}
async function createBackup(){
    const sid=document.getElementById('backupSpace')?.value;if(!sid){alert('Select a space first');return;}
    const desc=prompt('Backup description (optional):','');
    const r=await callTool('backup_create',{space_id:sid,description:desc||''});
    if(r.status==='ok'||r.backup_id){cache.backups=[];const b=await loadBackups('');renderBackupTable(b);}else alert(r.message||'Error');
}

// ═══════════════ GRAPH ═══════════════
async function renderGraph(){
    const c=document.getElementById('content');
    c.innerHTML=`<div class="page"><div class="page-header"><h2 class="page-title">🌉 Graph Bridge</h2><div>${spaceSelect('graphSpace')}</div></div><div id="graphContent"><div class="empty">Select a space to check its Graph Memory connection.</div></div></div>`;
    document.getElementById('graphSpace').addEventListener('change',async function(){
        const sid=this.value,el=document.getElementById('graphContent');
        if(!sid){el.innerHTML='<div class="empty">Select a space.</div>';return;}
        el.innerHTML='<div class="page-loading">Loading…</div>';
        const r=await callTool('graph_status',{space_id:sid}).catch(()=>({status:'error',message:'Not connected'}));
        el.innerHTML=`<div class="result-card">${renderJSON(r)}</div>
            <div style="margin-top:1rem;display:flex;gap:.5rem">
                <button class="btn-action blue" data-action="graph-push" data-space="${esc(sid)}">📤 Push to Graph</button>
                <button class="btn-action orange" data-action="confirm" data-tool="graph_disconnect" data-args='{"space_id":"${esc(sid)}"}' data-msg="Disconnect ${esc(sid)} from Graph Memory?">🔌 Disconnect</button>
            </div>`;
    });
}
async function graphPush(sid){
    const el=document.getElementById('graphContent');
    el.innerHTML='<div class="page-loading">Pushing to Graph Memory… (may take a while)</div>';
    const r=await callTool('graph_push',{space_id:sid});
    el.innerHTML=`<div class="result-card">${renderJSON(r)}</div>`;
}

// ═══════════════ MAINTENANCE ═══════════════
async function renderMaintenance(){
    const c=document.getElementById('content');
    c.innerHTML=`<div class="page">
        <div class="page-header"><h2 class="page-title">🧹 Maintenance</h2><div>${spaceSelect('maint_space')}</div></div>
        <div class="maint-list">
            <div class="maint-row">
                <div class="maint-info"><span class="maint-icon">🧠</span><div><strong>Consolidate</strong><span class="text-muted">LLM consolidation of live notes → bank</span></div></div>
                <div class="maint-actions"><button class="btn-action" data-action="maint-consolidate">▶ Run</button></div>
            </div>
            <div class="maint-row">
                <div class="maint-info"><span class="maint-icon">📦</span><div><strong>Compact</strong><span class="text-muted">Shrink oversized bank files via LLM</span></div></div>
                <div class="maint-actions"><div class="form-check"><input type="checkbox" data-1p-ignore id="mp_dry" checked><label for="mp_dry">Dry run</label></div><button class="btn-action" data-action="maint-compact">▶ Run</button></div>
            </div>
            <div class="maint-row">
                <div class="maint-info"><span class="maint-icon">🔧</span><div><strong>Repair</strong><span class="text-muted">Fix Unicode, duplicates, broken paths</span></div></div>
                <div class="maint-actions"><div class="form-check"><input type="checkbox" data-1p-ignore id="mr_dry" checked><label for="mr_dry">Dry run</label></div><button class="btn-action" data-action="maint-repair">▶ Run</button></div>
            </div>
            <div class="maint-sep"></div>
            <div class="maint-row">
                <div class="maint-info"><span class="maint-icon">🗑️</span><div><strong>Garbage Collector</strong><span class="text-muted">Clean orphaned notes older than</span></div></div>
                <div class="maint-actions"><input class="form-input" data-1p-ignore type="number" id="mg_days" value="7" style="width:60px;text-align:center;padding:.3rem"> <span class="text-muted" style="font-size:.7rem">days</span> <div class="form-check"><input type="checkbox" data-1p-ignore id="mg_confirm"><label for="mg_confirm">Execute</label></div><button class="btn-action orange" data-action="maint-gc">▶ Run</button></div>
            </div>
            <div class="maint-sep"></div>
            <div class="maint-row">
                <div class="maint-info"><span class="maint-icon">🧹</span><div><strong>Purge Tokens</strong><span class="text-muted">Delete revoked tokens from registry</span></div></div>
                <div class="maint-actions"><div class="form-check"><input type="checkbox" data-1p-ignore id="mt_all"><label for="mt_all">ALL</label></div><button class="btn-action red" data-action="maint-purge">▶ Purge</button></div>
            </div>
        </div>
    </div>`;
}

function _ms(){const s=gv('maint_space');if(!s){alert('Select a space first');} return s;}
async function maintConsolidate(){const s=_ms();if(!s)return;showModal('🧠 Consolidating…','<div class="page-loading">Running LLM consolidation…</div>',null,null);const r=await callTool('bank_consolidate',{space_id:s});closeModal();showModal('🧠 Consolidation Result',renderPretty('bank_consolidate',r),'Close',()=>true);}
async function maintCompact(){const s=_ms();if(!s)return;const dry=document.getElementById('mp_dry').checked;showModal('📦 Compacting…','<div class="page-loading">'+(dry?'Scanning…':'Compacting via LLM…')+'</div>',null,null);const r=await callTool('bank_compact',{space_id:s,dry_run:dry});closeModal();showModal('📦 Compact Result',renderPretty('bank_compact',r),'Close',()=>true);}
async function maintRepair(){const s=_ms();if(!s)return;const dry=document.getElementById('mr_dry').checked;showModal('🔧 Repairing…','<div class="page-loading">'+(dry?'Scanning…':'Applying fixes…')+'</div>',null,null);const r=await callTool('bank_repair',{space_id:s,dry_run:dry});closeModal();showModal('🔧 Repair Result',renderPretty('bank_repair',r),'Close',()=>true);}
async function maintGc(){const s=gv('maint_space');showModal('🗑️ GC Running…','<div class="page-loading">Scanning orphaned notes…</div>',null,null);const r=await callTool('admin_gc_notes',{space_id:s,max_age_days:parseInt(gv('mg_days'))||7,confirm:document.getElementById('mg_confirm').checked});closeModal();showModal('🗑️ GC Result',renderPretty('admin_gc_notes',r),'Close',()=>true);}
async function maintPurge(){if(!confirm('Are you sure?'))return;showModal('🧹 Purging…','<div class="page-loading">Deleting tokens…</div>',null,null);const r=await callTool('admin_purge_tokens',{revoked_only:!document.getElementById('mt_all').checked});cache.tokens=[];closeModal();showModal('🧹 Purge Result',renderPretty('admin_purge_tokens',r),'Close',()=>true);}

// ═══════════════ UPLOAD RULES ═══════════════
function showUploadRules(spaceId){
    showModal('📤 Upload Rules — ' + spaceId,`
        <div class="form-group">
            <label class="form-label">Select a Markdown file (.md)</label>
            <input type="file" data-1p-ignore class="form-input" id="m_rules_file" accept=".md,.txt,.markdown" style="padding:.4rem">
        </div>
        <div class="form-group">
            <label class="form-label">Or paste rules content directly</label>
            <textarea class="form-input" id="m_rules_text" rows="10" placeholder="# Memory Bank Rules — …"></textarea>
        </div>
        <div class="form-hint" style="margin-top:.5rem">⚠️ Rules are normally immutable. This requires <strong>manage</strong> permission.</div>
    `,'Upload Rules',async()=>{
        let content = gv('m_rules_text');
        const fileInput = document.getElementById('m_rules_file');
        if(fileInput?.files?.length){
            content = await fileInput.files[0].text();
        }
        if(!content||!content.trim()){alert('No content provided.');return false;}
        const r=await callTool('space_update_rules',{space_id:spaceId,rules:content});
        if(r.status==='ok'||r.size){
            closeModal();
            showModal('✅ Rules Updated',`<div class="pretty-table">
                <div class="pretty-row"><span class="pretty-k">Space</span><span class="pretty-v"><strong>${esc(spaceId)}</strong></span></div>
                <div class="pretty-row"><span class="pretty-k">New Size</span><span class="pretty-v">${fmtSize(r.size)}</span></div>
            </div>`,'Close',()=>true);
            return false;
        }
        alert(r.message||'Error');return false;
    });
}

// ═══════════════ UTILITIES ═══════════════
function gv(id){const el=document.getElementById(id);return el?(el.value||'').trim():'';}

async function runAndShow(tool,args){
    showModal('Loading…','<div class="page-loading">Executing…</div>',null,null);
    const r=await callTool(tool,args);closeModal();
    const title = TOOL_TITLES[tool] || tool.replace(/_/g,' ');
    showModal(title, renderPretty(tool, r), 'Close', ()=>true);
}

const TOOL_TITLES = {
    space_info: '📂 Space Details',
    space_rules: '📜 Space Rules',
    space_summary: '📊 Space Summary',
    system_health: '❤️ Health Status',
    system_about: 'ℹ️ About',
    system_whoami: '👤 Identity',
};

function renderPretty(tool, data) {
    if (data.status === 'error') return `<div style="color:var(--danger);padding:1rem">❌ ${esc(data.message||'Error')}</div>`;

    // ── space_info ──
    if (tool === 'space_info') {
        const rows = [
            ['Space ID', `<strong>${esc(data.space_id||'')}</strong>`],
            ['Description', esc(data.description||'—')],
            ['Owner', esc(data.owner||'—')],
            ['Created', fmtDate(data.created_at)],
        ];
        if (data.live) rows.push(['Live Notes', `<span class="badge blue">${data.live.count??0}</span> · ${fmtSize(data.live.total_size)}`]);
        if (data.bank) rows.push(['Bank Files', `<span class="badge green">${data.bank.count??0}</span> · ${fmtSize(data.bank.total_size)}`]);
        if (data.consolidation) rows.push(['Last Consolidation', fmtDate(data.consolidation.last_at) || '—']);
        if (data.total_notes_processed != null) rows.push(['Total Notes Processed', data.total_notes_processed]);
        if (data.graph_memory) rows.push(['Graph Memory', `<span class="badge purple">connected</span> · ${esc(data.graph_memory.memory_id||'')}`]);
        return `<div class="pretty-table">${rows.map(([k,v])=>`<div class="pretty-row"><span class="pretty-k">${k}</span><span class="pretty-v">${v}</span></div>`).join('')}</div>`;
    }

    // ── space_rules ──
    if (tool === 'space_rules') {
        const sid = esc(data.space_id||'');
        return `<div class="pretty-section">
            <div class="pretty-label" style="display:flex;align-items:center;justify-content:space-between">
                <span>Space: <strong>${sid}</strong> · ${fmtSize(data.size)}</span>
                <button class="btn-sm blue" data-action="upload-rules" data-space="${sid}" style="text-transform:none;letter-spacing:0">📤 Upload New Rules</button>
            </div>
            <pre class="pretty-code">${esc(data.rules||data.content||'No rules')}</pre>
        </div>`;
    }

    // ── space_summary ──
    if (tool === 'space_summary') {
        let html = '';
        if (data.rules) html += `<div class="pretty-section"><div class="pretty-label">📜 Rules</div><pre class="pretty-code" style="max-height:200px">${esc(data.rules)}</pre></div>`;
        if (data.bank_files) {
            html += `<div class="pretty-section"><div class="pretty-label">📘 Bank Files (${data.bank_files.length})</div>`;
            for (const f of data.bank_files) {
                html += `<details class="pretty-file"><summary><strong>${esc(f.filename)}</strong> · ${fmtSize(f.size)}</summary><pre class="pretty-code">${esc(f.content||'')}</pre></details>`;
            }
            html += '</div>';
        }
        if (data.synthesis) html += `<div class="pretty-section"><div class="pretty-label">📝 Synthesis</div><pre class="pretty-code">${esc(data.synthesis)}</pre></div>`;
        return html || renderJSON(data);
    }

    // ── Default: formatted key/value ──
    const skip = new Set(['status']);
    let html = '<div class="pretty-table">';
    for (const [k, v] of Object.entries(data)) {
        if (skip.has(k) || v === null || v === undefined) continue;
        if (typeof v === 'object') continue;
        html += `<div class="pretty-row"><span class="pretty-k">${esc(k)}</span><span class="pretty-v">${esc(String(v))}</span></div>`;
    }
    html += '</div>';
    // Nested objects
    for (const [k, v] of Object.entries(data)) {
        if (skip.has(k) || v === null || typeof v !== 'object') continue;
        if (Array.isArray(v)) {
            if (!v.length) continue;
            html += `<div class="pretty-section"><div class="pretty-label">${esc(k)} (${v.length})</div><pre class="pretty-code">${esc(JSON.stringify(v, null, 2))}</pre></div>`;
        } else {
            html += `<div class="pretty-section"><div class="pretty-label">${esc(k)}</div><div class="pretty-table">`;
            for (const [sk,sv] of Object.entries(v)) html += `<div class="pretty-row"><span class="pretty-k">${esc(sk)}</span><span class="pretty-v">${esc(String(sv))}</span></div>`;
            html += '</div></div>';
        }
    }
    return html;
}

function renderJSON(obj){
    if(!obj)return'<span class="text-muted">No data</span>';
    return `<pre class="json-pretty">${JSON.stringify(obj,null,2).replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,m=>{
        let c='json-num';if(/^"/.test(m))c=/:$/.test(m)?'json-key':'json-str';else if(/true|false/.test(m))c='json-bool';else if(/null/.test(m))c='json-null';
        return '<span class="'+c+'">'+esc(m)+'</span>';
    })}</pre>`;
}

// ═══════════════ MODAL ═══════════════
function showModal(title,bodyHTML,btnLabel,onConfirm){
    let m=document.getElementById('adminModal');
    if(!m){m=document.createElement('div');m.id='adminModal';m.className='modal-overlay';document.body.appendChild(m);}
    m.innerHTML=`<div class="modal-card">
        <div class="modal-header"><h3>${title}</h3><button class="modal-close" data-action="close-modal">✕</button></div>
        <div class="modal-body">${bodyHTML}</div>
        ${btnLabel?`<div class="modal-footer"><button class="btn-action" id="modalConfirmBtn">${esc(btnLabel)}</button></div>`:''}
    </div>`;
    m.style.display='flex';
    if(btnLabel&&onConfirm){
        document.getElementById('modalConfirmBtn').addEventListener('click',async()=>{
            const b=document.getElementById('modalConfirmBtn');b.disabled=true;b.textContent='Working…';
            try{const ok=await onConfirm();if(ok)closeModal();}finally{if(b){b.disabled=false;b.textContent=btnLabel;}}
        });
    }
}
function closeModal(){const m=document.getElementById('adminModal');if(m)m.style.display='none';}

// ═══════════════ INIT ═══════════════
document.addEventListener('DOMContentLoaded',()=>{
    document.getElementById('loginBtn').addEventListener('click',doLogin);
    document.getElementById('loginToken').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});
    document.getElementById('logoutBtn').addEventListener('click',doLogout);
    adminHealth().then(h=>{const el=document.getElementById('headerVersion');if(el&&h.version)el.textContent='v'+h.version;});
    checkSession().then(async data=>{
        if(data){hideLogin();await Promise.all([loadSpaces(),loadTokens()]);buildSidebar();showCategory('dashboard');}else showLogin();
    });
});
