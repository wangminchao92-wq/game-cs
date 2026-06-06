/* ═══════════════════════════════════════════════
   🎮 Game Customer Service - Frontend App
   ═══════════════════════════════════════════════ */

const API = '';
let currentView = 'dashboard';

// ─── Navigation ───

function switchView(view) {
    currentView = view;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById('view-' + view)?.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector(`[data-view="${view}"]`)?.classList.add('active');

    const titles = {
        dashboard: '📊 工作台', tickets: '🎫 工单管理', players: '👥 玩家查询',
        knowledge: '📚 知识库', analytics: '📈 数据分析', team: '👨‍👩‍👧‍👦 团队管理',
    };
    document.getElementById('view-title').textContent = titles[view] || view;

    // Lazy load
    if (view === 'dashboard') loadDashboard();
    else if (view === 'tickets') loadTickets();
    else if (view === 'players') loadPlayers();
    else if (view === 'knowledge') loadKB();
    else if (view === 'analytics') loadAnalytics();
    else if (view === 'team') loadTeam();
}

// ─── Navigation ───

// ─── Auth ───
let currentUser = null;

function getToken() { return localStorage.getItem('gcs_token'); }
function setToken(t) { localStorage.setItem('gcs_token', t); }
function clearToken() { localStorage.removeItem('gcs_token'); currentUser = null; }

async function apiGet(url) {
    const h = {'Content-Type': 'application/json'};
    const t = getToken(); if (t) h['Authorization'] = 'Bearer ' + t;
    const r = await fetch(API + url, {headers: h});
    if (r.status === 401) { clearToken(); showLogin(); throw new Error('请先登录'); }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function apiPost(url, data) {
    const h = {'Content-Type': 'application/json'};
    const t = getToken(); if (t) h['Authorization'] = 'Bearer ' + t;
    const r = await fetch(API + url, {method: 'POST', headers: h, body: JSON.stringify(data)});
    if (r.status === 401) { clearToken(); showLogin(); throw new Error('请先登录'); }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function apiPut(url, data) {
    const h = {'Content-Type': 'application/json'};
    const t = getToken(); if (t) h['Authorization'] = 'Bearer ' + t;
    const r = await fetch(API + url, {method: 'PUT', headers: h, body: JSON.stringify(data)});
    if (r.status === 401) { clearToken(); showLogin(); throw new Error('请先登录'); }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

async function apiDelete(url) {
    const h = {};
    const t = getToken(); if (t) h['Authorization'] = 'Bearer ' + t;
    const r = await fetch(API + url, {method: 'DELETE', headers: h});
    if (r.status === 401) { clearToken(); showLogin(); throw new Error('请先登录'); }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
}

function showLogin() {
    document.getElementById('login-overlay').classList.remove('hidden');
    document.getElementById('login-error').textContent = '';
}

async function doLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    if (!username || !password) { errEl.textContent = '请输入用户名和密码'; return; }
    errEl.textContent = '登录中...';
    try {
        const r = await fetch(API + '/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password}),
        });
        const data = await r.json();
        if (!r.ok) { errEl.textContent = data.detail || '登录失败'; return; }
        setToken(data.token);
        currentUser = data.user;
        document.getElementById('login-overlay').classList.add('hidden');
        document.getElementById('login-password').value = '';
        onAuthSuccess();
        loadDashboard();
    } catch (e) {
        errEl.textContent = '网络错误: ' + e.message;
    }
}

function doLogout() {
    if (!confirm('确认退出登录？')) return;
    clearToken();
    showLogin();
}

function onAuthSuccess() {
    // Show/hide super_admin nav items
    const navUsers = document.getElementById('nav-users');
    if (navUsers) navUsers.style.display = currentUser && currentUser.role === 'super_admin' ? '' : 'none';
    const navSettings = document.getElementById('nav-settings');
    if (navSettings) navSettings.style.display = currentUser && currentUser.role === 'super_admin' ? '' : 'none';
    // Add logout button to topbar if not exists
    if (!document.getElementById('logout-btn')) {
        const right = document.querySelector('.topbar-right');
        if (right) {
            const btn = document.createElement('button');
            btn.id = 'logout-btn';
            btn.className = 'btn btn-sm';
            btn.style.cssText = 'border-color:var(--accent-red);color:var(--accent-red);margin-left:8px';
            btn.textContent = '🚪 ' + (currentUser ? currentUser.display_name : '');
            btn.onclick = doLogout;
            right.appendChild(btn);
        }
    } else {
        document.getElementById('logout-btn').textContent = '🚪 ' + (currentUser ? currentUser.display_name : '');
    }
}

async function initAuth() {
    const token = getToken();
    if (!token) { showLogin(); return; }
    try {
        const user = await apiGet('/api/auth/me');
        currentUser = user;
        document.getElementById('login-overlay').classList.add('hidden');
        onAuthSuccess();
    } catch (e) {
        // Token invalid or expired
        clearToken();
        showLogin();
    }
}

function statusTag(s) {
    const map = {
        open: '待处理', in_progress: '处理中', waiting_player: '等待玩家',
        resolved: '已解决', closed: '已关闭',
        urgent: '紧急', high: '高', medium: '中', low: '低',
        account: '账号', payment: '充值', gameplay: '游戏', bug: 'BUG',
        report: '举报', other: '其他',
    };
    return `<span class="tag tag-${s}">${map[s] || s}</span>`;
}

function timeAgo(iso) {
    if (!iso) return '-';
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return '刚刚';
    if (mins < 60) return mins + '分钟前';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + '小时前';
    const days = Math.floor(hrs / 24);
    return days + '天前';
}

function localTime(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

function renderMd(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    html = html.replace(/###### (.+)/g, '<h6>$1</h6>');
    html = html.replace(/##### (.+)/g, '<h5>$1</h5>');
    html = html.replace(/#### (.+)/g, '<h4>$1</h4>');
    html = html.replace(/### (.+)/g, '<h3>$1</h3>');
    html = html.replace(/## (.+)/g, '<h2>$1</h2>');
    html = html.replace(/# (.+)/g, '<h1>$1</h1>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/`(.+?)`/g, '<code>$1</code>');
    html = html.replace(/^- (.+)/gm, '<li>$1</li>');
    html = html.replace(/\|(.+?)\|/g, (m) => {
        if (m.includes('---')) return '';
        return m.replace(/\|/g, '').trim();
    });
    // Tables
    const lines = html.split('\n');
    let inTable = false, tableHtml = '';
    const result = [];
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line.startsWith('|') && line.endsWith('|')) {
            if (!inTable) { inTable = true; tableHtml = '<table><thead>'; }
            const cells = line.split('|').filter(c => c.trim());
            if (line.includes('---')) continue;
            tableHtml += '<tr>' + cells.map(c => '<td>' + c.trim() + '</td>').join('') + '</tr>';
        } else {
            if (inTable) {
                tableHtml += '</tbody></table>';
                result.push(tableHtml);
                inTable = false;
            }
            result.push(line);
        }
    }
    if (inTable) { tableHtml += '</tbody></table>'; result.push(tableHtml); }
    html = result.join('\n');
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    return '<p>' + html + '</p>';
}

// ─── Global Search ───

function globalSearch() {
    const q = document.getElementById('global-search').value.trim();
    if (!q) return;
    switchView('tickets');
    document.getElementById('ticket-search').value = q;
    loadTickets();
}

// ══════════════════════════════════════════════════
//  DASHBOARD
// ══════════════════════════════════════════════════

async function loadDashboard() {
    try {
        const data = await apiGet('/api/dashboard');
        document.getElementById('stat-total').textContent = data.total_tickets;
        document.getElementById('stat-open').textContent = data.open_tickets;
        document.getElementById('stat-resolved').textContent = data.resolved_tickets;
        document.getElementById('stat-urgent').textContent = data.urgent_tickets;
        document.getElementById('stat-avg').textContent = data.avg_resolve_hours + 'h';
        document.getElementById('ticket-badge').textContent = data.open_tickets;

        // Agent list
        const ag = document.getElementById('agent-list');
        ag.innerHTML = data.agent_workload.map(a =>
            `<div class="agent-mini">
                <span class="avatar">${a.avatar}</span>
                <div class="info"><div class="name">${a.name}</div></div>
                <span style="color:${a.open_count > 0 ? 'var(--accent-orange)' : 'var(--accent-green)'}">
                    ${a.open_count} 待处理
                </span>
            </div>`
        ).join('');

        // Recent tickets
        const tb = document.querySelector('#recent-tickets-table tbody');
        tb.innerHTML = data.recent_tickets.map(t =>
            `<tr onclick="openTicket('${t.id}')" style="cursor:pointer">
                <td>${t.id}</td>
                <td>${escapeHtml(t.title)}</td>
                <td>${escapeHtml(t.player)}</td>
                <td>${statusTag(t.status)}</td>
                <td>${statusTag(t.priority)}</td>
            </tr>`
        ).join('');
    } catch (e) {
        console.error('Dashboard error:', e);
    }
}

// ══════════════════════════════════════════════════
//  TICKETS
// ══════════════════════════════════════════════════

let ticketPage = 1;

async function loadTickets() {
    const status = document.getElementById('filter-status').value;
    const priority = document.getElementById('filter-priority').value;
    const category = document.getElementById('filter-category').value;
    const q = document.getElementById('ticket-search').value;
    const params = new URLSearchParams({page: ticketPage, per_page: 20});
    if (status) params.set('status', status);
    if (priority) params.set('priority', priority);
    if (category) params.set('category', category);
    if (q) params.set('q', q);

    try {
        const data = await apiGet('/api/tickets?' + params);
        const tb = document.querySelector('#tickets-table tbody');
        tb.innerHTML = data.tickets.map(t => {
            const ago = timeAgo(t.created_at);
            return `<tr>
                <td>${t.ticket_id}</td>
                <td>${escapeHtml(t.title)}</td>
                <td>${statusTag(t.category)}</td>
                <td>${escapeHtml(t.player_name)}</td>
                <td>${t.agent_name ? t.agent_avatar + ' ' + t.agent_name : '<span class="tag" style="background:rgba(139,148,158,0.2);color:var(--text-muted)">未分配</span>'}</td>
                <td>${statusTag(t.priority)}</td>
                <td>${statusTag(t.status)}</td>
                <td style="font-size:12px;color:var(--text-secondary)">${ago}</td>
                <td>
                    <div class="action-row">
                        <button class="btn btn-sm" onclick="event.stopPropagation();openTicket('${t.ticket_id}')">查看</button>
                        ${t.status === 'open' || t.status === 'in_progress' ? `<button class="btn btn-sm btn-primary" onclick="event.stopPropagation();assignMe('${t.ticket_id}', ${t.id})">接单</button>` : ''}
                    </div>
                </td>
            </tr>`;
        }).join('');

        // Pagination
        const totalPages = Math.ceil(data.total / data.per_page);
        let pg = '';
        for (let i = 1; i <= totalPages && i <= 10; i++) {
            pg += `<button class="${i === data.page ? 'active' : ''}" onclick="ticketPage=${i};loadTickets()">${i}</button>`;
        }
        document.getElementById('tickets-pagination').innerHTML = pg;
    } catch (e) {
        console.error('Tickets error:', e);
    }
}

async function assignMe(ticketId, ticketDbId) {
    try {
        // Assign to agent 1 (Zhang San) as default
        await apiPut(`/api/tickets/${ticketId}`, {assigned_to: 1, status: 'in_progress'});
        loadTickets();
    } catch (e) {
        console.error('Assign error:', e);
    }
}

async function openTicket(ticketId) {
    try {
        const t = await apiGet(`/api/tickets/${ticketId}`);
        const modal = document.getElementById('ticket-modal');
        const playerLang = t.player ? t.player.language : 'zh-CN';
        const playerLangFlag = t.player ? (t.player.language_flag || '🌐') : '🌐';
        const playerLangName = t.player ? (t.player.language_name || playerLang) : '中文';
        const isForeignLang = playerLang !== 'zh-CN';

        document.getElementById('ticket-detail-title').textContent = `🎫 ${t.ticket_id} - ${escapeHtml(t.title)}`;

        let html = `
        <div class="ticket-info-row">
            <div class="ticket-info-item"><strong>类别</strong> ${statusTag(t.category)}</div>
            <div class="ticket-info-item"><strong>优先级</strong> ${statusTag(t.priority)}</div>
            <div class="ticket-info-item"><strong>状态</strong> ${statusTag(t.status)}</div>
            <div class="ticket-info-item"><strong>创建</strong> ${localTime(t.created_at)}</div>
        </div>
        <div class="ticket-info-row">
            <div class="ticket-info-item"><strong>玩家</strong> ${t.player ? escapeHtml(t.player.nickname) + ' (' + t.player.player_id + ')' : '未知'}</div>
            <div class="ticket-info-item"><strong>客服</strong> ${t.agent ? t.agent.avatar + ' ' + t.agent.name : '未分配'}</div>
            <div class="ticket-info-item"><strong>语言</strong> <span class="lang-badge">${playerLangFlag} ${escapeHtml(playerLangName)}</span></div>
            <div class="ticket-info-item"><strong>AI模式</strong> <label class="toggle-switch"><input type="checkbox" ${t.ai_mode ? 'checked' : ''} onchange="toggleAIMode('${t.ticket_id}', this.checked)"><span class="toggle-slider"></span></label> <span style="font-size:12px;color:${t.ai_mode ? 'var(--accent-green)' : 'var(--text-muted)'}">${t.ai_mode ? '已开启' : '已关闭'}</span></div>
        </div>
        <hr style="border-color:var(--border);margin:12px 0">
        <h4 style="margin-bottom:10px;font-size:14px;color:var(--text-secondary)">对话记录</h4>
        <div class="ticket-messages" id="ticket-messages">`;

        t.messages.forEach(m => {
            const cls = m.sender_type === 'player' ? 'msg-player' : m.sender_type === 'system' ? 'msg-system' : 'msg-agent';
            const langBadge = m.language_flag && m.language_name && m.original_language !== 'zh-CN'
                ? `<span class="msg-lang-badge">${m.language_flag}</span>` : '';
            const aiBadge = m.is_ai_suggested ? `<span class="msg-ai-badge">🤖 AI</span>` : '';
            const translatedHtml = m.translated_content
                ? `<div class="msg-translated">🌍 ${escapeHtml(m.translated_content)}</div>` : '';
            html += `<div class="msg-bubble ${cls}">
                <div class="msg-header">
                    ${aiBadge}
                    <span>${escapeHtml(m.sender_name)}</span>
                    ${langBadge}
                    <span>${localTime(m.created_at)}</span>
                </div>
                <div>${escapeHtml(m.content)}</div>
                ${translatedHtml}
            </div>`;
        });

        html += `</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">`;

        // AI suggestion button
        if (t.status !== 'resolved' && t.status !== 'closed' && isForeignLang) {
            html += `<button class="btn btn-sm" id="ai-suggest-btn" style="border-color:var(--accent-blue);color:var(--accent-blue)" onclick="suggestReply('${t.ticket_id}')">🤖 AI建议回复</button>`;
        }

        // Status actions
        if (t.status === 'open') {
            html += `<button class="btn btn-primary btn-sm" onclick="updateTicketStatus('${t.ticket_id}','in_progress')">开始处理</button>`;
        }
        if (t.status === 'in_progress') {
            html += `<button class="btn btn-sm" onclick="updateTicketStatus('${t.ticket_id}','waiting_player')">等待玩家</button>`;
            html += `<button class="btn" style="border-color:var(--accent-green);color:var(--accent-green)" onclick="updateTicketStatus('${t.ticket_id}','resolved')">✅ 标记解决</button>`;
        }
        if (t.status === 'waiting_player') {
            html += `<button class="btn btn-primary btn-sm" onclick="updateTicketStatus('${t.ticket_id}','in_progress')">继续处理</button>`;
        }
        html += `<button class="btn btn-sm" onclick="updateTicketStatus('${t.ticket_id}','closed')">关闭</button>`;

        if (t.agent) {
            html += `<button class="btn btn-sm" onclick="updateTicketStatus('${t.ticket_id}','open');updateTicketAssign('${t.ticket_id}',null)">释放工单</button>`;
        }

        html += `</div>
        <div class="reply-area">
            <textarea id="reply-text" placeholder="输入回复..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendReply('${t.ticket_id}')}"></textarea>
            <button class="btn btn-primary" onclick="sendReply('${t.ticket_id}')">发送</button>
            <button class="btn btn-sm" onclick="sendReply('${t.ticket_id}',true)" title="内部备注">📝 备注</button>
        </div>`;

        document.getElementById('ticket-detail-main').innerHTML = html;
        modal.style.display = 'flex';
    } catch (e) {
        console.error('Open ticket error:', e);
    }
}

function closeTicketModal() {
    document.getElementById('ticket-modal').style.display = 'none';
}

async function updateTicketStatus(ticketId, status) {
    await apiPut(`/api/tickets/${ticketId}`, {status});
    openTicket(ticketId);
}

async function updateTicketAssign(ticketId, agentId) {
    await apiPut(`/api/tickets/${ticketId}`, {assigned_to: agentId});
}

async function sendReply(ticketId, isInternal = false, isAiSuggested = false) {
    const textarea = document.getElementById('reply-text');
    const content = textarea.value.trim();
    if (!content) return;
    try {
        const result = await apiPost(`/api/tickets/${ticketId}/messages`, {
            sender_type: 'agent', sender_name: '张三', is_ai_suggested: isAiSuggested,
            content, is_internal: isInternal,
        });
        textarea.value = '';
        // Show translation toast
        if (result.translated_content) {
            showToast('✅ 已自动翻译并发送', 'success');
        }
        openTicket(ticketId);
    } catch (e) {
        console.error('Send reply error:', e);
    }
}

// ─── New Ticket ───

function openNewTicket() {
    document.getElementById('new-ticket-modal').style.display = 'flex';
}

function closeNewTicketModal() {
    document.getElementById('new-ticket-modal').style.display = 'none';
}

async function submitNewTicket() {
    const playerId = document.getElementById('new-ticket-player').value.trim();
    const title = document.getElementById('new-ticket-title').value.trim();
    const category = document.getElementById('new-ticket-category').value;
    const priority = document.getElementById('new-ticket-priority').value;
    const desc = document.getElementById('new-ticket-desc').value.trim();
    if (!playerId || !title) { alert('请填写玩家ID和标题'); return; }
    try {
        await apiPost('/api/tickets', {player_id: playerId, title, category, priority, description: desc});
        closeNewTicketModal();
        document.getElementById('new-ticket-player').value = '';
        document.getElementById('new-ticket-title').value = '';
        document.getElementById('new-ticket-desc').value = '';
        loadTickets();
        switchView('tickets');
    } catch (e) {
        alert('创建失败: ' + e.message);
    }
}

// ══════════════════════════════════════════════════
//  PLAYERS
// ══════════════════════════════════════════════════

let playerPage = 1;

async function loadPlayers() {
    const q = document.getElementById('player-search').value;
    const params = new URLSearchParams({page: playerPage, per_page: 20});
    if (q) params.set('q', q);
    try {
        const data = await apiGet('/api/players?' + params);
        const tb = document.querySelector('#players-table tbody');
        tb.innerHTML = data.players.map(p =>
            `<tr>
                <td>${p.player_id}</td>
                <td>${escapeHtml(p.nickname)}</td>
                <td><span class="lang-badge">${p.language_flag || '🌐'} ${escapeHtml(p.language_name || p.language)}</span></td>
                <td>S${escapeHtml(p.server)}</td>
                <td>${p.level}</td>
                <td>${p.vip_level > 0 ? '<span class="vip-badge">VIP' + p.vip_level + '</span>' : '-'}</td>
                <td>¥${p.total_recharge.toFixed(0)}</td>
                <td><span class="status-${p.status}">${p.status === 'active' ? '● 正常' : p.status === 'banned' ? '● 封禁' : '● 冻结'}</span></td>
                <td>${p.open_ticket_count > 0 ? `<span style="color:var(--accent-orange)">${p.open_ticket_count}</span>/` : ''}${p.ticket_count}</td>
                <td><button class="btn btn-sm" onclick="openPlayer('${p.player_id}')">查看</button></td>
            </tr>`
        ).join('');

        const totalPages = Math.ceil(data.total / data.per_page);
        let pg = '';
        for (let i = 1; i <= totalPages && i <= 5; i++) {
            pg += `<button class="${i === data.page ? 'active' : ''}" onclick="playerPage=${i};loadPlayers()">${i}</button>`;
        }
        document.getElementById('players-pagination').innerHTML = pg;
    } catch (e) {
        console.error('Players error:', e);
    }
}

async function openPlayer(playerId) {
    try {
        const p = await apiGet(`/api/players/${playerId}`);
        const modal = document.getElementById('player-modal');
        document.getElementById('player-detail-title').textContent = `👤 ${escapeHtml(p.nickname)} (${p.player_id})`;

        let html = `
        <div class="player-stat-grid">
            <div class="player-stat"><div class="val">${p.level}</div><div class="lbl">等级</div></div>
            <div class="player-stat"><div class="val">${p.vip_level > 0 ? 'VIP ' + p.vip_level : '-'}</div><div class="lbl">VIP</div></div>
            <div class="player-stat"><div class="val" style="color:var(--accent-orange)">¥${p.total_recharge.toFixed(0)}</div><div class="lbl">累计充值</div></div>
            <div class="player-stat"><div class="val">S${p.server}</div><div class="lbl">服务器</div></div>
            <div class="player-stat"><div class="val">${p.language_flag || '🌐'} ${escapeHtml(p.language_name || p.language)}</div><div class="lbl">语言</div></div>
            <div class="player-stat"><div class="val" style="font-size:16px">${localTime(p.last_login)}</div><div class="lbl">最后登录</div></div>
        </div>`;
        html += `
        <h4 style="margin-bottom:8px;font-size:14px;color:var(--text-secondary)">工单记录 (${p.tickets.length})</h4>
        <table>
            <thead><tr><th>编号</th><th>标题</th><th>状态</th><th>优先级</th><th>时间</th></tr></thead>
            <tbody>
                ${p.tickets.map(t => `<tr style="cursor:pointer" onclick="closePlayerModal();openTicket('${t.ticket_id}')">
                    <td>${t.ticket_id}</td>
                    <td>${escapeHtml(t.title)}</td>
                    <td>${statusTag(t.status)}</td>
                    <td>${statusTag(t.priority)}</td>
                    <td style="font-size:12px;color:var(--text-secondary)">${localTime(t.created_at)}</td>
                </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">暂无工单</td></tr>'}
            </tbody>
        </table>`;

        document.getElementById('player-detail-body').innerHTML = html;
        modal.style.display = 'flex';

        // Populate language dropdown
        populateLanguageSelect('player-lang-select', p.language);
    } catch (e) {
        console.error('Player detail error:', e);
    }
}

function closePlayerModal() {
    document.getElementById('player-modal').style.display = 'none';
}

// ══════════════════════════════════════════════════
//  MULTI-LANGUAGE & AI
// ══════════════════════════════════════════════════

let supportedLanguages = [];

async function loadLanguages() {
    try {
        const data = await apiGet('/api/languages');
        supportedLanguages = data.languages;
    } catch (e) {
        console.error('Load languages error:', e);
    }
}

function populateLanguageSelect(selectId, currentLang) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = supportedLanguages.map(l =>
        `<option value="${l.code}" ${l.code === currentLang ? 'selected' : ''}>${l.flag} ${l.name}</option>`
    ).join('');
}

async function updatePlayerLanguage() {
    const sel = document.getElementById('player-lang-select');
    if (!sel) return;
    const playerId = document.getElementById('player-detail-title').textContent.match(/\((\d+)\)/);
    if (!playerId) return;
    const lang = sel.value;
    try {
        await apiPut(`/api/players/${playerId[1]}/language`, {language: lang});
        // Refresh player detail
        openPlayer(playerId[1]);
    } catch (e) {
        console.error('Update language error:', e);
    }
}

async function suggestReply(ticketId) {
    const btn = document.getElementById('ai-suggest-btn');
    if (btn) { btn.textContent = '🤔 AI思考中...'; btn.disabled = true; }
    try {
        const data = await apiPost(`/api/tickets/${ticketId}/ai-suggest`, {});
        showSuggestion(ticketId, data);
    } catch (e) {
        console.error('AI suggest error:', e);
        alert('AI建议生成失败: ' + e.message);
    } finally {
        if (btn) { btn.textContent = '🤖 AI建议回复'; btn.disabled = false; }
    }
}

function showSuggestion(ticketId, data) {
    // Remove existing suggestion box
    const existing = document.getElementById('ai-suggestion-box');
    if (existing) existing.remove();

    const replyArea = document.querySelector('.reply-area');
    if (!replyArea) return;

    const box = document.createElement('div');
    box.id = 'ai-suggestion-box';
    box.style.cssText = 'margin-bottom:12px;padding:12px;background:rgba(88,166,255,0.08);border:1px solid rgba(88,166,255,0.3);border-radius:var(--radius-sm);';
    box.innerHTML = `
        <div style="font-size:12px;color:var(--accent-blue);margin-bottom:6px;display:flex;align-items:center;gap:6px">
            🤖 AI建议回复 <span style="font-size:11px;color:var(--text-muted)">(置信度: ${Math.round(data.confidence * 100)}%)</span>
            <span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${data.suggested_action === 'send_message' ? '建议发送回复' : '建议转人工'}</span>
        </div>
        <div style="margin-bottom:8px;padding:8px;background:var(--bg-card);border-radius:4px">
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">🇨🇳 中文回复:</div>
            <div style="font-size:13px;color:var(--text-primary)">${escapeHtml(data.reply_zh)}</div>
        </div>
        ${data.reply_translated ? `
        <div style="margin-bottom:8px;padding:8px;background:var(--bg-card);border-radius:4px">
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">翻译到玩家语言:</div>
            <div style="font-size:13px;color:var(--accent-green)">${escapeHtml(data.reply_translated)}</div>
        </div>` : ''}
        <div style="display:flex;gap:8px">
            <button class="btn btn-sm btn-primary" onclick="useSuggestion('${ticketId}')">📨 使用并发送</button>
            <button class="btn btn-sm" onclick="fillSuggestion()">📝 填入编辑框</button>
            <button class="btn btn-sm" onclick="this.parentElement.parentElement.remove()">✕ 关闭</button>
        </div>
    `;
    replyArea.parentNode.insertBefore(box, replyArea);
}

function fillSuggestion() {
    const box = document.getElementById('ai-suggestion-box');
    if (!box) return;
    const zhDiv = box.querySelectorAll('div[style*="background:var(--bg-card)"]')[0];
    if (zhDiv) {
        const text = zhDiv.lastElementChild.textContent;
        document.getElementById('reply-text').value = text;
    }
    box.remove();
}

async function useSuggestion(ticketId) {
    const box = document.getElementById('ai-suggestion-box');
    if (!box) return;
    const zhDiv = box.querySelectorAll('div[style*="background:var(--bg-card)"]')[0];
    if (!zhDiv) return;
    const text = zhDiv.lastElementChild.textContent;
    box.remove();

    // Send as AI-suggested reply
    document.getElementById('reply-text').value = text;
    await sendReply(ticketId, false, true);
}

async function toggleAIMode(ticketId, enabled) {
    try {
        await apiPut(`/api/tickets/${ticketId}`, {ai_mode: enabled});
        // Refresh ticket detail
        openTicket(ticketId);
    } catch (e) {
        console.error('Toggle AI mode error:', e);
    }
}

// ══════════════════════════════════════════════════
//  KNOWLEDGE BASE
// ══════════════════════════════════════════════════

async function loadKB() {
    const q = document.getElementById('kb-search').value;
    const cat = document.getElementById('kb-category').value;
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (cat) params.set('category', cat);
    try {
        const data = await apiGet('/api/kb?' + params);
        const list = document.getElementById('kb-list');
        list.innerHTML = data.articles.map(a =>
            `<div class="kb-card" onclick="openArticle(${a.id})">
                <h4>📄 ${escapeHtml(a.title)}</h4>
                <div class="meta">${statusTag(a.category)} · 👍 ${a.helpful_count} 次有帮助 · ${localTime(a.updated_at)}</div>
                <div class="tags">${a.tags.map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div>
            </div>`
        ).join('');
    } catch (e) {
        console.error('KB error:', e);
    }
}

async function openArticle(id) {
    try {
        const a = await apiGet(`/api/kb/${id}`);
        const modal = document.getElementById('article-modal');
        document.getElementById('article-title').textContent = `📄 ${a.title}`;
        document.getElementById('article-body').innerHTML = `
            <div style="margin-bottom:12px;font-size:12px;color:var(--text-secondary)">
                ${statusTag(a.category)} · ${a.tags.join(', ')}
            </div>
            <div class="article-content">${renderMd(a.content)}</div>
            <div style="margin-top:16px;display:flex;gap:8px">
                <button class="btn btn-sm" onclick="markHelpful(${a.id})">👍 有帮助 (${a.helpful_count})</button>
            </div>
        `;
        modal.style.display = 'flex';
    } catch (e) {
        console.error('Article error:', e);
    }
}

function closeArticleModal() {
    document.getElementById('article-modal').style.display = 'none';
}

async function markHelpful(id) {
    const data = await apiPost(`/api/kb/${id}/helpful`, {});
    // Update the button text
    const btn = document.querySelector('#article-body .btn');
    if (btn) btn.textContent = `👍 有帮助 (${data.helpful_count})`;
}

function openNewArticle() {
    document.getElementById('new-article-modal').style.display = 'flex';
}

function closeNewArticleModal() {
    document.getElementById('new-article-modal').style.display = 'none';
}

async function submitNewArticle() {
    const title = document.getElementById('new-article-title').value.trim();
    const category = document.getElementById('new-article-category').value;
    const tags = document.getElementById('new-article-tags').value.trim();
    const content = document.getElementById('new-article-content').value.trim();
    if (!title || !content) { alert('请填写标题和内容'); return; }
    await apiPost('/api/kb', {title, category, tags, content});
    closeNewArticleModal();
    document.getElementById('new-article-title').value = '';
    document.getElementById('new-article-tags').value = '';
    document.getElementById('new-article-content').value = '';
    loadKB();
}

// ══════════════════════════════════════════════════
//  ANALYTICS
// ══════════════════════════════════════════════════

async function loadAnalytics() {
    const period = document.getElementById('analytics-period').value;
    try {
        const data = await apiGet('/api/analytics?period=' + period);

        // Daily chart
        const dailyEl = document.getElementById('chart-daily');
        if (data.daily_tickets.length === 0) {
            dailyEl.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:30px">暂无数据</div>';
        } else {
            const maxVal = Math.max(...data.daily_tickets.map(d => d.count), 1);
            dailyEl.innerHTML = data.daily_tickets.map(d => {
                const h = Math.max(20, (d.count / maxVal) * 120);
                return `<div class="chart-bar" style="height:${h}px;">
                    <div class="bar-value">${d.count}</div>
                    <div class="bar-label">${d.date.slice(5)}</div>
                </div>`;
            }).join('');
        }

        // Category chart
        const catEl = document.getElementById('chart-categories');
        if (data.category_distribution.length === 0) {
            catEl.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:30px">暂无数据</div>';
        } else {
            const maxCat = Math.max(...data.category_distribution.map(d => d.count), 1);
            const colors = ['#58a6ff', '#d29922', '#3fb950', '#bc8cff', '#f85149', '#39d2c0'];
            catEl.innerHTML = data.category_distribution.map((d, i) => {
                const h = Math.max(20, (d.count / maxCat) * 120);
                return `<div class="chart-bar" style="height:${h}px;background:${colors[i % colors.length]}">
                    <div class="bar-value">${d.count}</div>
                    <div class="bar-label">${d.name}</div>
                </div>`;
            }).join('');
        }

        // Priority donut
        const priEl = document.getElementById('chart-priority');
        if (data.priority_distribution.length === 0) {
            priEl.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:30px">暂无数据</div>';
        } else {
            const totalPri = data.priority_distribution.reduce((s, d) => s + d.count, 0) || 1;
            const priColors = {urgent: '#f85149', high: '#d29922', medium: '#58a6ff', low: '#8b949e'};
            priEl.innerHTML = data.priority_distribution.map(d => {
                const pct = (d.count / totalPri * 100);
                return `<div class="donut-item">
                    <span class="donut-label">${statusTag(d.name)}</span>
                    <div class="donut-bar">
                        <div class="donut-fill" style="width:${pct}%;background:${priColors[d.name] || '#58a6ff'}"></div>
                    </div>
                    <span class="donut-count">${d.count}</span>
                    <span style="font-size:12px;color:var(--text-muted);min-width:35px">${pct.toFixed(0)}%</span>
                </div>`;
            }).join('');
        }

        // Agent performance
        const agEl = document.getElementById('chart-agents');
        if (data.agent_performance.length === 0) {
            agEl.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:30px">暂无数据</div>';
        } else {
            const maxRes = Math.max(...data.agent_performance.map(a => a.resolved), 1);
            agEl.innerHTML = data.agent_performance.map(a => {
                const h = Math.max(20, (a.resolved / maxRes) * 120);
                return `<div class="chart-bar" style="height:${h}px;background:var(--accent-green)">
                    <div class="bar-value">${a.resolved}/${a.total}</div>
                    <div class="bar-label">${a.avatar} ${a.name}</div>
                </div>`;
            }).join('');
        }
    } catch (e) {
        console.error('Analytics error:', e);
    }
}

// ══════════════════════════════════════════════════
//  TEAM
// ══════════════════════════════════════════════════

async function loadTeam() {
    try {
        const data = await apiGet('/api/agents');
        const list = document.getElementById('team-list');
        const isSuperAdmin = currentUser && currentUser.role === 'super_admin';
        list.innerHTML = data.agents.map(a =>
            `<div class="team-card" style="position:relative">
                ${isSuperAdmin ? `<button onclick="deleteAgent(${a.id},'${escapeHtml(a.name)}')" style="position:absolute;top:8px;right:8px;background:none;border:1px solid var(--accent-red);color:var(--accent-red);border-radius:4px;cursor:pointer;font-size:12px;padding:2px 8px;opacity:0.6;transition:opacity 0.2s" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.6">✕ 删除</button>` : ''}
                <div class="avatar">${a.avatar}</div>
                <div class="name">${escapeHtml(a.name)}</div>
                <div class="role">
                    ${a.role === 'supervisor' ? '🛡️ 主管' : a.role === 'admin' ? '⚙️ 管理员' : '💼 客服'}
                </div>
                <div class="stats">
                    待处理: ${a.open_tickets} · 已解决: ${a.resolved_tickets}
                </div>
                <div style="margin-top:6px">
                    ${a.is_active ? '<span style="font-size:11px;color:var(--accent-green)">● 在线</span>' : '<span style="font-size:11px;color:var(--text-muted)">○ 离线</span>'}
                </div>
            </div>`
        ).join('');
    } catch (e) {
        console.error('Team error:', e);
    }
}

// ─── Agent CRUD ───

let selectedAgentAvatar = '👤';
let uploadedAvatarUrl = null;

function showAddAgentForm() {
    document.getElementById('add-agent-modal').style.display = 'flex';
    document.getElementById('new-agent-name').value = '';
    document.getElementById('new-agent-email').value = '';
    document.getElementById('new-agent-role').value = 'agent';
    document.getElementById('new-agent-password').value = '';
    // Reset avatar selection
    document.querySelectorAll('#avatar-picker .avatar-option').forEach(el => el.classList.remove('selected'));
    document.querySelector('#avatar-picker .avatar-option:first-child').classList.add('selected');
    selectedAgentAvatar = '👤';
    uploadedAvatarUrl = null;
    document.getElementById('avatar-upload-preview').style.display = 'none';
    document.getElementById('avatar-preview-img').src = '';
    document.getElementById('agent-avatar-upload').value = '';
}

function closeAddAgentModal() {
    document.getElementById('add-agent-modal').style.display = 'none';
}

function selectAgentAvatar(el) {
    document.querySelectorAll('#avatar-picker .avatar-option').forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');
    selectedAgentAvatar = el.textContent;
    // Clear uploaded avatar if user picks an emoji
    uploadedAvatarUrl = null;
    document.getElementById('avatar-upload-preview').style.display = 'none';
}

async function handleAvatarUpload(input) {
    const file = input.files[0];
    if (!file) return;

    // Preview locally
    const reader = new FileReader();
    reader.onload = function(e) {
        document.getElementById('avatar-preview-img').src = e.target.result;
        document.getElementById('avatar-upload-preview').style.display = 'block';
    };
    reader.readAsDataURL(file);

    // Upload to server
    try {
        const formData = new FormData();
        formData.append('file', file);
        const token = getToken();
        const r = await fetch('/api/upload/avatar', {
            method: 'POST',
            headers: token ? { 'Authorization': 'Bearer ' + token } : {},
            body: formData,
        });
        if (!r.ok) throw new Error((await r.json()).detail || '上传失败');
        const data = await r.json();
        uploadedAvatarUrl = data.url;
        // Deselect emoji selection
        document.querySelectorAll('#avatar-picker .avatar-option').forEach(e => e.classList.remove('selected'));
        showToast('✅ 头像已上传', 'success');
    } catch (e) {
        showToast('❌ 头像上传失败: ' + e.message, 'error');
    }
}

function clearAvatarUpload() {
    uploadedAvatarUrl = null;
    document.getElementById('avatar-upload-preview').style.display = 'none';
    document.getElementById('agent-avatar-upload').value = '';
    // Re-select default emoji
    document.querySelectorAll('#avatar-picker .avatar-option').forEach(e => e.classList.remove('selected'));
    document.querySelector('#avatar-picker .avatar-option:first-child').classList.add('selected');
    selectedAgentAvatar = '👤';
}

async function submitNewAgent() {
    const name = document.getElementById('new-agent-name').value.trim();
    const email = document.getElementById('new-agent-email').value.trim();
    const role = document.getElementById('new-agent-role').value;
    const password = document.getElementById('new-agent-password').value.trim();

    if (!name) { showToast('请输入姓名', 'error'); return; }
    if (!email) { showToast('请输入邮箱', 'error'); return; }
    if (!password || password.length < 6) { showToast('密码不能为空且至少6位', 'error'); return; }

    const avatar = uploadedAvatarUrl || selectedAgentAvatar;

    try {
        const data = await apiPost('/api/agents', {
            name, email, role, password, avatar,
        });
        showToast('✅ ' + data.message, 'success');
        closeAddAgentModal();
        loadTeam();
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        showToast('❌ ' + msg, 'error');
    }
}

async function deleteAgent(id, name) {
    if (!confirm(`确认删除客服 "${name}"？\n该客服负责的工单将解除指派，登录账号也将被禁用。`)) return;
    try {
        const data = await apiDelete('/api/agents/' + id);
        showToast('✅ ' + data.message, 'success');
        loadTeam();
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        showToast('❌ ' + msg, 'error');
    }
}

// ══════════════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    loadLanguages();
});

// ─── Toast Notifications ───

function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast-notification');
    if (existing) existing.remove();

    const colors = {
        info: 'var(--accent-blue)',
        success: 'var(--accent-green)',
        error: 'var(--accent-red)',
        warning: 'var(--accent-orange)',
    };

    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    toast.style.cssText = `
        position: fixed; top: 20px; right: 20px; z-index: 9999;
        padding: 12px 20px; border-radius: var(--radius-sm);
        background: var(--bg-card); border: 1px solid ${colors[type] || colors.info};
        color: var(--text-primary); font-size: 13px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        animation: slideIn 0.3s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 2500);
}

// ══════════════════════════════════════════════════
//  LIVE CHAT (Agent WebSocket Client)
// ══════════════════════════════════════════════════

let liveChatWs = null;
let currentChatTicketId = null;
let activeChats = [];
let chatPollTimer = null;

function switchView(view) {
    currentView = view;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const el = document.getElementById('view-' + view);
    if (el) el.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector(`[data-view="${view}"]`)?.classList.add('active');

    const titles = {
        dashboard: '📊 工作台', tickets: '🎫 工单管理', players: '👥 玩家查询',
        knowledge: '📚 知识库', analytics: '📈 数据分析', team: '👨‍👩‍👧‍👦 团队管理',
        livechat: '💬 实时聊天', facebook: '📰 Facebook热点',
        users: '👥 用户管理',
        settings: '⚙️ 系统设置',
    };
    document.getElementById('view-title').textContent = titles[view] || view;

    if (view === 'dashboard') loadDashboard();
    else if (view === 'tickets') loadTickets();
    else if (view === 'players') loadPlayers();
    else if (view === 'knowledge') loadKB();
    else if (view === 'analytics') loadAnalytics();
    else if (view === 'team') loadTeam();
    else if (view === 'livechat') initLiveChat();
    else if (view === 'facebook') initFbNews();
    else if (view === 'users') loadUsers();
    else if (view === 'settings') loadSettings();
}

async function initLiveChat() {
    document.getElementById('livechat-status').textContent = '🟢 在线';
    
    // Disconnect old WebSocket if any
    if (window.chatMonitorWs) {
        window.chatMonitorWs.close();
        window.chatMonitorWs = null;
    }
    
    if (chatPollTimer) clearInterval(chatPollTimer);
    await loadActiveChats();
    chatPollTimer = setInterval(loadActiveChats, 3000);
}

async function loadActiveChats() {
    try {
        const data = await apiGet('/api/chat/active');
        activeChats = data.active_chats || [];
        
        const list = document.getElementById('active-chats-list');
        const badge = document.getElementById('livechat-badge');
        
        if (activeChats.length === 0) {
            list.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);font-size:13px">暂无活跃聊天</div>';
            badge.style.display = 'none';
            return;
        }
        
        badge.style.display = 'inline-block';
        badge.textContent = activeChats.length;
        
        list.innerHTML = activeChats.map(c => {
            const isActive = c.ticket_id === currentChatTicketId;
            return `<div class="chat-item ${isActive ? 'active' : ''}" onclick="selectLiveChat('${c.ticket_id}')">
                <div class="chat-title">${escapeHtml(c.title)}</div>
                <div class="chat-meta">
                    <span class="online-dot ${c.has_player ? 'online' : 'offline'}"></span>
                    ${escapeHtml(c.player_name)} ${c.player_language_flag || '🌐'}
                    <span style="margin-left:auto">${c.agent_count > 0 ? '👨‍💼' + c.agent_count : ''}</span>
                </div>
            </div>`;
        }).join('');
        
    } catch (e) {
        console.error('Load active chats error:', e);
    }
}

async function selectLiveChat(ticketId) {
    currentChatTicketId = ticketId;
    
    // Close old chat WebSocket
    if (window.chatWs) {
        window.chatWs.close();
        window.chatWs = null;
    }
    
    // Remove AI suggestion panel
    const existingSuggestion = document.getElementById('livechat-suggestion');
    if (existingSuggestion) existingSuggestion.remove();
    
    // Highlight in sidebar
    document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
    const items = document.getElementById('active-chats-list').children;
    for (let item of items) {
        if (item.textContent.includes(ticketId)) {
            item.classList.add('active');
        }
    }
    
    try {
        const t = await apiGet(`/api/tickets/${ticketId}`);
        const chat = activeChats.find(c => c.ticket_id === ticketId);
        const isForeign = t.player && t.player.language !== 'zh-CN';
        const langFlag = t.player ? (t.player.language_flag || '🌐') : '🌐';
        const langName = t.player ? (t.player.language_name || t.player.language) : '中文';
        
        document.getElementById('livechat-title').innerHTML = 
            `🎫 ${ticketId} — ${escapeHtml(t.title)} ${isForeign ? `<span class="lang-badge">${langFlag} ${langName}</span>` : ''}`;
        document.getElementById('livechat-actions').style.display = 'flex';
        document.getElementById('livechat-input-area').style.display = 'flex';
        document.getElementById('livechat-input').disabled = false;
        document.getElementById('livechat-input').placeholder = isForeign ? '输入中文回复... (自动翻译)' : '输入回复...';
        
        // Show messages
        const msgContainer = document.getElementById('livechat-messages');
        msgContainer.innerHTML = '';
        
        // Show language info banner
        if (isForeign) {
            const info = document.createElement('div');
            info.className = 'msg-bubble msg-system';
            info.style.maxWidth = '100%';
            info.style.textAlign = 'left';
            info.innerHTML = `<strong>🌍 多语言模式</strong><br>
                🗣️ 玩家语言: ${langFlag} ${langName}<br>
                🤖 AI模式: ${t.ai_mode ? '✅ 开启 (自动翻译+AI建议)' : '❌ 关闭'}<br>
                📝 操作流程: 玩家消息→自动译中文→AI建议→审核→自动译回${langFlag}`;
            msgContainer.appendChild(info);
        }
        
        // Show existing messages
        t.messages.forEach(m => {
            addLiveChatMessage(m);
        });
        
        msgContainer.scrollTop = msgContainer.scrollHeight;
        
        // Connect WebSocket for real-time updates
        connectChatWs(ticketId);
        
    } catch (e) {
        console.error('Select chat error:', e);
    }
}

function connectChatWs(ticketId) {
    if (window.chatWs) window.chatWs.close();
    
    const wsUrl = `ws://127.0.0.1:8899/ws/chat/${ticketId}?role=agent`;
    window.chatWs = new WebSocket(wsUrl);
    
    window.chatWs.onopen = function() {
        document.getElementById('livechat-status').textContent = '🟢 实时连接';
    };
    
    window.chatWs.onmessage = function(event) {
        const data = JSON.parse(event.data);
        
        if (data.type === 'message') {
            // New message arrived in real-time
            addLiveChatMessage(data);
            const container = document.getElementById('livechat-messages');
            container.scrollTop = container.scrollHeight;
            
            // Play notification sound
            if (data.sender_type === 'player') {
                playNotifSound();
            }
        }
        
        if (data.type === 'ai_suggestion') {
            // AI auto-generated suggestion - show for review
            showAISuggestionPanel(data);
            playNotifSound();
        }
    };
    
    window.chatWs.onclose = function() {
        document.getElementById('livechat-status').textContent = '🟡 已断开 (轮询模式)';
        // Auto-reconnect
        setTimeout(() => {
            if (currentChatTicketId) connectChatWs(currentChatTicketId);
        }, 3000);
    };
    
    window.chatWs.onerror = function() {
        document.getElementById('livechat-status').textContent = '🔴 连接失败';
    };
}

function addLiveChatMessage(data) {
    const container = document.getElementById('livechat-messages');
    if (!container) return;
    
    if (data.is_internal) return;
    
    const cls = data.sender_type === 'player' ? 'msg-player' : data.sender_type === 'system' ? 'msg-system' : 'msg-agent';
    const aiBadge = data.is_ai_suggested ? '<span class="msg-ai-badge">🤖 AI</span>' : '';
    
    const div = document.createElement('div');
    div.className = `msg-bubble ${cls}`;
    
    let mainContent = escapeHtml(data.content);
    let translationHtml = '';
    
    // For player messages with translation: show both original and Chinese
    if (data.sender_type === 'player' && data.translated_content) {
        mainContent = `<div style="color:var(--accent-cyan);font-size:12px;margin-bottom:4px">🌍 原始消息 (${data.language_name || data.original_language || ''}):</div>
            <div>${escapeHtml(data.content)}</div>
            <div class="msg-translated">🇨🇳 中文翻译: ${escapeHtml(data.translated_content)}</div>`;
    }
    // For agent messages with translation: show Chinese and translated version
    else if (data.sender_type === 'agent' && data.translated_content) {
        mainContent = `<div>🇨🇳 ${escapeHtml(data.content)}</div>
            <div class="msg-translated">🌍 ${escapeHtml(data.translated_content)}</div>`;
    }
    
    div.innerHTML = `
        <div class="msg-header">
            ${aiBadge}
            <span>${escapeHtml(data.sender_name)}</span>
            <span>${data.timestamp ? localTime(data.timestamp) : '刚刚'}</span>
        </div>
        ${mainContent}
    `;
    container.appendChild(div);
}

function showAISuggestionPanel(data) {
    // Remove existing suggestion
    const existing = document.getElementById('livechat-suggestion');
    if (existing) existing.remove();
    
    const msgContainer = document.getElementById('livechat-messages');
    if (!msgContainer) return;
    
    const panel = document.createElement('div');
    panel.id = 'livechat-suggestion';
    panel.style.cssText = 'margin:12px 0;padding:12px;background:rgba(88,166,255,0.08);border:1px solid rgba(88,166,255,0.3);border-radius:var(--radius-sm);animation:fadeIn 0.3s ease';
    
    const confidence = Math.round((data.confidence || 0) * 100);
    panel.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
            <span class="msg-ai-badge">🤖 AI建议回复</span>
            <span style="font-size:11px;color:var(--text-muted)">置信度: ${confidence}%</span>
            <span style="margin-left:auto;font-size:11px;color:var(--text-muted)">
                ${data.suggested_action === 'send_message' ? '✅ 建议发送' : '⚠️ 建议转人工'}
            </span>
        </div>
        <div style="padding:8px;background:var(--bg-card);border-radius:4px;margin-bottom:8px">
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">🇨🇳 中文回复 (请审核):</div>
            <div style="font-size:13px;line-height:1.5" id="suggestion-zh">${escapeHtml(data.reply_zh)}</div>
        </div>
        ${data.reply_translated ? `
        <div style="padding:8px;background:var(--bg-card);border-radius:4px;margin-bottom:8px">
            <div style="font-size:12px;color:var(--accent-cyan);margin-bottom:4px">🌍 自动翻译后:</div>
            <div style="font-size:13px;color:var(--accent-cyan);line-height:1.5">${escapeHtml(data.reply_translated)}</div>
        </div>` : ''}
        <div style="display:flex;gap:8px;align-items:center">
            <button class="btn btn-sm btn-primary" onclick="approveAndSendSuggestion()">✅ 审核通过并发送</button>
            <button class="btn btn-sm" onclick="editSuggestion()">📝 编辑</button>
            <button class="btn btn-sm" onclick="dismissSuggestion()">✕ 忽略</button>
        </div>
    `;
    
    msgContainer.appendChild(panel);
    msgContainer.scrollTop = msgContainer.scrollHeight;
    
    // Update badge
    const badge = document.getElementById('livechat-badge');
    if (badge) {
        badge.style.display = 'inline-block';
        badge.textContent = '💡';
    }
}

function approveAndSendSuggestion() {
    const panel = document.getElementById('livechat-suggestion');
    if (!panel) return;
    
    const zhText = document.getElementById('suggestion-zh');
    if (!zhText) return;
    
    const content = zhText.textContent.trim();
    if (!content) return;
    
    // Send as agent message
    document.getElementById('livechat-input').value = content;
    panel.remove();
    sendLiveChatMsg();
    
    // Clear badge
    const badge = document.getElementById('livechat-badge');
    if (badge) badge.style.display = 'none';
}

function editSuggestion() {
    const zhText = document.getElementById('suggestion-zh');
    if (!zhText) return;
    
    document.getElementById('livechat-input').value = zhText.textContent.trim();
    document.getElementById('livechat-input').focus();
    
    const panel = document.getElementById('livechat-suggestion');
    if (panel) {
        // Change to edit mode
        panel.innerHTML = `
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
                <span class="msg-ai-badge">✏️ 编辑中</span>
                <span style="font-size:11px;color:var(--text-muted)">请修改后发送</span>
            </div>
            <div style="display:flex;gap:8px">
                <button class="btn btn-sm btn-primary" onclick="editDone()">✅ 编辑完成，发送</button>
                <button class="btn btn-sm" onclick="dismissSuggestion()">✕ 取消</button>
            </div>
        `;
    }
}

function editDone() {
    const content = document.getElementById('livechat-input').value.trim();
    if (!content) return;
    
    const panel = document.getElementById('livechat-suggestion');
    if (panel) panel.remove();
    
    sendLiveChatMsg();
}

function dismissSuggestion() {
    const panel = document.getElementById('livechat-suggestion');
    if (panel) panel.remove();
    
    const badge = document.getElementById('livechat-badge');
    if (badge) badge.style.display = 'none';
}

function playNotifSound() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 800;
        osc.type = 'sine';
        gain.gain.value = 0.1;
        osc.start();
        osc.stop(ctx.currentTime + 0.15);
    } catch (e) {
        // Silent fail if audio not supported
    }
}

async function sendLiveChatMsg() {
    const input = document.getElementById('livechat-input');
    const content = input.value.trim();
    if (!content || !currentChatTicketId) return;
    
    try {
        const result = await apiPost(`/api/tickets/${currentChatTicketId}/messages`, {
            sender_type: 'agent',
            sender_name: '张三',
            content: content,
            is_internal: false,
        });
        
        input.value = '';
        
        // Add message to UI immediately
        addLiveChatMessage({
            sender_type: 'agent',
            sender_name: '张三',
            content: content,
            translated_content: result.translated_content,
            timestamp: new Date().toISOString(),
        });
        
        const container = document.getElementById('livechat-messages');
        container.scrollTop = container.scrollHeight;
        
        // Show toast for translation
        if (result.translated_content) {
            showToast('✅ 已自动翻译并发送', 'success');
        }
        
        // Clear suggestion badge
        const badge = document.getElementById('livechat-badge');
        if (badge) badge.style.display = 'none';
        
    } catch (e) {
        console.error('Send live chat error:', e);
        alert('发送失败: ' + e.message);
    }
}

// Patch: add livechat to switchView titles

// ═══ FACEBOOK NEWS ═══════════════════════════════════════════════════

async function initFbNews() {
    await loadFbConfig();
    await refreshFbNews();
}

async function loadFbConfig() {
    try {
        const data = await apiGet('/api/facebook/config');
        if (data.configured) {
            document.getElementById('fb-config-status').textContent =
                '✅ 已配置 Facebook App，代理: ' + (data.proxy || '无');
        } else {
            document.getElementById('fb-config-status').textContent =
                '⚠️ 未配置，请输入 Facebook App ID 和 App Secret';
        }
    } catch (e) {
        console.error('Load FB config error:', e);
    }
}

async function saveFbConfig() {
    const appId = document.getElementById('fb-app-id').value.trim();
    const appSecret = document.getElementById('fb-app-secret').value.trim();
    const proxy = document.getElementById('fb-proxy').value.trim() || null;
    
    if (!appId || !appSecret) {
        showToast('⚠️ 请填写 App ID 和 App Secret', 'error');
        return;
    }
    
    try {
        const r = await fetch(API + '/api/facebook/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({app_id: appId, app_secret: appSecret, proxy: proxy}),
        });
        const data = await r.json();
        showToast('✅ ' + data.message, 'success');
        document.getElementById('fb-config-status').textContent =
            '✅ 已保存，代理: ' + (proxy || '无');
    } catch (e) {
        showToast('❌ 保存失败: ' + e.message, 'error');
    }
}

async function testFbConnection() {
    const proxy = document.getElementById('fb-proxy').value.trim() || null;
    const status = document.getElementById('fb-config-status');
    status.textContent = '🔄 测试连接中...';
    
    try {
        const r = await fetch(API + '/api/facebook/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({proxy: proxy}),
        });
        const data = await r.json();
        status.textContent = data.status === 'ok' ? '✅ ' + data.message : '❌ ' + data.message;
        showToast(data.status === 'ok' ? '✅ 连接成功' : '❌ 连接失败', data.status === 'ok' ? 'success' : 'error');
    } catch (e) {
        status.textContent = '❌ 测试失败: ' + e.message;
    }
}

async function refreshFbNews() {
    const list = document.getElementById('fb-news-list');
    list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">🔄 加载中...</div>';
    
    try {
        const data = await apiGet('/api/facebook/news');
        
        if (data.needs_config) {
            document.getElementById('fb-config-status').textContent =
                '⚠️ ' + data.message;
        }
        
        document.getElementById('fb-news-count').textContent = data.total_news + ' 条';
        renderFbNews(data);
    } catch (e) {
        list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--color-error)">❌ 加载失败: ' + e.message + '</div>';
    }
}

function renderFbNews(data) {
    const list = document.getElementById('fb-news-list');
    
    if (!data.news || data.news.length === 0) {
        list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">暂无数据</div>';
        return;
    }
    
    let html = '';
    for (const item of data.news) {
        const isPlaceholder = item.is_placeholder;
        const avatar = item.image
            ? `<img src="${item.image}" style="width:48px;height:48px;border-radius:8px;object-fit:cover;flex-shrink:0">`
            : `<div style="width:48px;height:48px;border-radius:8px;background:var(--bg-input);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0">📰</div>`;
        
        const time = item.created_time
            ? new Date(item.created_time).toLocaleString('zh-CN')
            : '';
        
        const url = item.url || `https://www.facebook.com/${item.page_id}`;
        
        let stats = '';
        if (!isPlaceholder) {
            const parts = [];
            if (item.likes > 0) parts.push(`❤️ ${item.likes}`);
            if (item.comments > 0) parts.push(`💬 ${item.comments}`);
            if (item.shares > 0) parts.push(`🔄 ${item.shares}`);
            if (parts.length) stats = '<div style="font-size:11px;color:var(--text-muted);margin-top:4px">' + parts.join(' · ') + '</div>';
        }
        
        html += `
            <div style="display:flex;gap:12px;padding:12px;border-bottom:1px solid var(--border);transition:background 0.2s" 
                 onmouseover="this.style.background='var(--bg-hover)'" onmouseout="this.style.background=''">
                ${avatar}
                <div style="flex:1;min-width:0">
                    <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                        <span style="font-size:12px;color:var(--accent-blue);font-weight:600">${item.page_name}</span>
                        ${isPlaceholder ? '<span style="font-size:10px;background:var(--accent-yellow);color:#000;padding:1px 6px;border-radius:4px">媒体列表</span>' : ''}
                    </div>
                    <div style="font-size:13px;color:var(--text-primary);line-height:1.5;${item.message.length > 200 ? 'max-height:60px;overflow:hidden' : ''}">
                        ${escapeHtml(item.message || item.story || '（无内容）')}
                    </div>
                    ${stats}
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px">
                        <span style="font-size:11px;color:var(--text-muted)">${time}</span>
                        <a href="${url}" target="_blank" style="font-size:11px;color:var(--accent-blue);text-decoration:none">查看原文 →</a>
                    </div>
                </div>
            </div>
        `;
    }
    
    list.innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ═══ USER MANAGEMENT ═══════════════════════════════════════════════

async function loadUsers() {
    const tbody = document.querySelector('#users-table tbody');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-muted)">加载中...</td></tr>';
    try {
        const data = await apiGet('/api/admin/users');
        if (!data.users || data.users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-muted)">暂无用户</td></tr>';
            return;
        }
        let html = '';
        for (const u of data.users) {
            const isSelf = currentUser && currentUser.id === u.id;
            const roleBadge = u.role === 'super_admin'
                ? '<span class="tag tag-urgent">超级管理员</span>'
                : '<span class="tag tag-medium">客服人员</span>';
            const statusBadge = u.is_active
                ? '<span style="color:var(--accent-green)">● 启用</span>'
                : '<span style="color:var(--accent-red)">● 禁用</span>';
            const delBtn = isSelf
                ? '<span style="color:var(--text-muted);font-size:12px">当前账户</span>'
                : `<button class="btn btn-sm" style="border-color:var(--accent-red);color:var(--accent-red)" onclick="deleteUser(${u.id},'${u.username}')">删除</button>`;
            html += `<tr>
                <td>${u.id}</td>
                <td><strong>${escapeHtml(u.username)}</strong></td>
                <td>${escapeHtml(u.display_name)}</td>
                <td>${roleBadge}</td>
                <td>${statusBadge}</td>
                <td>${u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '-'}</td>
                <td style="display:flex;gap:6px">${delBtn}</td>
            </tr>`;
        }
        tbody.innerHTML = html;
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--accent-red)">加载失败: ' + e.message + '</td></tr>';
    }
}

function showAddUserForm() {
    document.getElementById('add-user-modal').style.display = 'flex';
    document.getElementById('new-user-username').value = '';
    document.getElementById('new-user-display').value = '';
    document.getElementById('new-user-password').value = '';
    document.getElementById('new-user-role').value = 'agent';
}

function closeAddUserModal() {
    document.getElementById('add-user-modal').style.display = 'none';
}

async function submitNewUser() {
    const username = document.getElementById('new-user-username').value.trim();
    const display_name = document.getElementById('new-user-display').value.trim() || username;
    const password = document.getElementById('new-user-password').value;
    const role = document.getElementById('new-user-role').value;

    if (username.length < 3) { showToast('用户名至少3个字符', 'error'); return; }
    if (password.length < 6) { showToast('密码至少6个字符', 'error'); return; }

    try {
        const data = await apiPost('/api/admin/users', {username, display_name, password, role});
        showToast('✅ ' + data.message, 'success');
        closeAddUserModal();
        loadUsers();
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        showToast('❌ ' + msg, 'error');
    }
}

async function deleteUser(id, username) {
    if (!confirm(`确认删除账户 "${username}"？此操作不可撤销！`)) return;
    try {
        const data = await apiDelete('/api/admin/users/' + id);
        showToast('✅ ' + data.message, 'success');
        loadUsers();
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        showToast('❌ ' + msg, 'error');
    }
}

// ═══ SETTINGS — Auto Reply ═══════════════════════════════════════

async function loadAutoReplyConfig() {
    try {
        const data = await apiGet('/api/settings/auto-reply');
        document.getElementById('auto-reply-toggle').checked = data.enabled === 'true';
        document.getElementById('auto-reply-start').value = String(data.start_hour);
        document.getElementById('auto-reply-end').value = String(data.end_hour);
        updateAutoReplyStatus(data);
    } catch (e) {
        console.error('Load auto-reply config error:', e);
    }
}

function loadSettings() {
    loadAutoReplyConfig();
    loadLlmConfig();
}

function updateAutoReplyStatus(data) {
    const badge = document.getElementById('auto-reply-window-badge');
    if (data.enabled === 'true' && data.in_window) {
        badge.style.display = 'block';
        badge.style.background = 'rgba(63,185,80,0.15)';
        badge.style.border = '1px solid var(--accent-green)';
        badge.style.color = 'var(--accent-green)';
        badge.textContent = '🟢 当前在自动回复时段内，AI将自动回复玩家消息';
    } else if (data.enabled === 'true') {
        badge.style.display = 'block';
        badge.style.background = 'rgba(210,153,34,0.15)';
        badge.style.border = '1px solid var(--accent-orange)';
        badge.style.color = 'var(--accent-orange)';
        badge.textContent = '🟡 自动回复已启用，但当前不在设定时段内';
    } else {
        badge.style.display = 'none';
    }
    document.getElementById('auto-reply-status').textContent = '';
}

function onAutoReplyToggle() {
    const enabled = document.getElementById('auto-reply-toggle').checked;
    document.getElementById('auto-reply-status').textContent = enabled ? '开关已切换，点击保存生效' : '';
}

async function saveAutoReplyConfig() {
    const enabled = document.getElementById('auto-reply-toggle').checked;
    const startHour = parseInt(document.getElementById('auto-reply-start').value);
    const endHour = parseInt(document.getElementById('auto-reply-end').value);
    const statusEl = document.getElementById('auto-reply-status');
    statusEl.textContent = '保存中...';

    try {
        const data = await apiPost('/api/settings/auto-reply', {
            enabled: enabled,
            start_hour: startHour,
            end_hour: endHour,
        });
        showToast('✅ ' + data.message, 'success');
        updateAutoReplyStatus({
            enabled: String(enabled),
            in_window: data.in_window,
        });
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        showToast('❌ ' + msg, 'error');
        statusEl.textContent = '保存失败';
    }
}

const LLM_PROVIDER_DEFAULTS = {
    deepseek_api: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
    local_deepseek: { base_url: '', model: 'deepseek-chat' },
    openai: { base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
    custom: { base_url: '', model: '' },
};

function loadLlmConfig() {
    apiGet('/api/settings/llm').then(data => {
        document.getElementById('llm-provider').value = data.provider;
        document.getElementById('llm-base-url').value = data.base_url || '';
        document.getElementById('llm-model').value = data.model || '';
        document.getElementById('llm-use-kb').checked = data.use_kb === 'true';
        onLlmProviderChange();
    }).catch(e => {
        console.error('Load LLM config error:', e);
    });
}

function onLlmProviderChange() {
    const provider = document.getElementById('llm-provider').value;
    const defaults = LLM_PROVIDER_DEFAULTS[provider] || {};
    const baseUrlEl = document.getElementById('llm-base-url');
    const modelEl = document.getElementById('llm-model');
    // Only auto-fill if current values are empty or match a previous default
    if (!baseUrlEl.value.trim() || Object.values(LLM_PROVIDER_DEFAULTS).some(d => d.base_url === baseUrlEl.value.trim())) {
        baseUrlEl.placeholder = defaults.base_url || '输入 API 地址';
        if (defaults.base_url) baseUrlEl.value = defaults.base_url;
    }
    if (!modelEl.value.trim() || Object.values(LLM_PROVIDER_DEFAULTS).some(d => d.model === modelEl.value.trim())) {
        modelEl.placeholder = defaults.model || '输入模型名称';
        if (defaults.model) modelEl.value = defaults.model;
    }
}

function toggleLlmKeyVisibility() {
    const el = document.getElementById('llm-api-key');
    el.type = el.type === 'password' ? 'text' : 'password';
}

async function saveLlmConfig() {
    const provider = document.getElementById('llm-provider').value;
    const baseUrl = document.getElementById('llm-base-url').value.trim();
    const model = document.getElementById('llm-model').value.trim();
    const apiKey = document.getElementById('llm-api-key').value.trim();
    const useKb = document.getElementById('llm-use-kb').checked;
    const statusEl = document.getElementById('llm-config-status');

    statusEl.textContent = '保存中...';

    try {
        const body = { provider, base_url: baseUrl, model, use_kb: useKb };
        if (apiKey) body.api_key = apiKey;

        const data = await apiPost('/api/settings/llm', body);
        showToast('✅ ' + data.message, 'success');
        statusEl.textContent = '已保存' + (data.api_key_masked ? ' (Key: ' + data.api_key_masked + ')' : '');
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        showToast('❌ ' + msg, 'error');
        statusEl.textContent = '保存失败';
    }
}

async function testLlmConfig() {
    const resultEl = document.getElementById('llm-test-result');
    resultEl.style.display = 'block';
    resultEl.style.background = 'rgba(88,166,255,0.1)';
    resultEl.style.border = '1px solid var(--accent-blue)';
    resultEl.textContent = '⏳ 正在测试连接 ...';

    try {
        const data = await apiPost('/api/translate', {
            text: 'Hello, this is a test message.',
            target_lang: 'zh-CN',
        });
        resultEl.style.background = 'rgba(67,181,129,0.15)';
        resultEl.style.border = '1px solid var(--accent-green)';
        resultEl.innerHTML = '<strong>✅ 翻译服务正常</strong><br><br>' +
            '原文: ' + escapeHtml(data.original) + '<br>' +
            '翻译: ' + escapeHtml(data.translated);
    } catch (e) {
        let msg = e.message;
        try { const j = JSON.parse(e.message); msg = j.detail || msg; } catch(_){}
        resultEl.style.background = 'rgba(239,83,80,0.15)';
        resultEl.style.border = '1px solid var(--accent-red)';
        resultEl.textContent = '❌ 连接失败: ' + msg;
    }
}

// ═══ INIT ══════════════════════════════════════════════════════════

// Override window.onload to add auth check
window.addEventListener('DOMContentLoaded', () => {
    initAuth();
});
