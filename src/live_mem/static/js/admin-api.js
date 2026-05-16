/**
 * Live Memory Admin — API layer (cookie HttpOnly auth, same as /live)
 */

async function adminLogin(token) {
    const r = await fetch('/api/login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
    });
    if (r.status === 401) return { status: 'error', message: 'Invalid token' };
    try { return await r.json(); } catch { return { status: 'error', message: 'Bad response' }; }
}

async function adminLogout() {
    try { await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }); } catch {}
}

async function adminHealth() {
    try { const r = await fetch('/health'); return await r.json(); } catch { return {}; }
}

/**
 * Call an MCP tool via POST /api/tool.
 * Auth cookie is attached automatically by the browser.
 */
async function callTool(toolName, args = {}) {
    const r = await fetch('/api/tool', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: toolName, arguments: args }),
    });
    if (r.status === 401) {
        showLogin('Session expired.');
        throw new Error('Unauthorized');
    }
    try {
        const text = await r.text();
        if (!text) return { status: 'error', message: 'Empty response' };
        return JSON.parse(text);
    } catch (e) {
        return { status: 'error', message: 'Invalid JSON: ' + e.message };
    }
}

/**
 * Check if current session is valid (cookie present & working).
 */
async function checkSession() {
    try {
        const r = await fetch('/api/spaces', { credentials: 'same-origin' });
        if (r.status === 401) return null;
        const data = await r.json();
        return data.status === 'ok' ? data : null;
    } catch { return null; }
}
