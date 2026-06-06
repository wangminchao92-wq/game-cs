/**
 * 🎮 Game CS - Embeddable Chat Widget
 * 
 * Third-party websites can embed this widget with:
 * 
 *   <script src="https://cs.example.com/static/chat-widget.js"
 *     data-api-key="YOUR_API_KEY"
 *     data-server="https://cs.example.com"
 *     data-player-id="USER_10001"
 *     data-player-name="PlayerName"
 *     data-language="pt-BR"
 *   ></script>
 * 
 * Or via a floating button that opens a chat form to create a ticket:
 * 
 *   <script src="https://cs.example.com/static/chat-widget.js"
 *     data-api-key="YOUR_API_KEY"
 *     data-server="https://cs.example.com"
 *     data-mode="ticket"  
 *   ></script>
 */

(function() {
  'use strict';

  // ─── Config ───────────────────────────────────────────────────
  
  const SCRIPT = document.currentScript;
  const API_KEY = SCRIPT.getAttribute('data-api-key') || '';
  const SERVER = SCRIPT.getAttribute('data-server') || window.location.origin;
  const PLAYER_ID = SCRIPT.getAttribute('data-player-id') || '';
  const PLAYER_NAME = SCRIPT.getAttribute('data-player-name') || 'Guest';
  const LANGUAGE = SCRIPT.getAttribute('data-language') || 'zh-CN';
  const MODE = SCRIPT.getAttribute('data-mode') || 'chat'; // 'chat' or 'ticket'
  const WS_BASE = SERVER.replace(/^http/, 'ws');
  
  // ─── State ────────────────────────────────────────────────────
  
  let ws = null;
  let ticketId = null;
  let isOpen = false;
  let messages = [];
  let reconnectTimer = null;
  
  // ─── Create UI ────────────────────────────────────────────────
  
  const COLORS = {
    primary: '#58a6ff',
    bg: '#161b22',
    card: '#1c2128',
    border: '#30363d',
    text: '#e6edf3',
    textSec: '#8b949e',
    accent: '#3fb950',
  };
  
  const styles = `
    #gamecs-widget-btn {
      position: fixed; bottom: 20px; right: 20px; z-index: 99999;
      width: 56px; height: 56px; border-radius: 50%;
      background: linear-gradient(135deg, #58a6ff, #bc8cff);
      color: #fff; border: none; cursor: pointer;
      font-size: 24px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);
      transition: transform 0.2s; display: flex;
      align-items: center; justify-content: center;
    }
    #gamecs-widget-btn:hover { transform: scale(1.1); }
    #gamecs-widget-btn .badge {
      position: absolute; top: -4px; right: -4px;
      background: #f85149; color: #fff;
      font-size: 11px; padding: 2px 6px; border-radius: 10px;
      min-width: 18px; text-align: center; display: none;
    }
    
    #gamecs-widget-panel {
      position: fixed; bottom: 90px; right: 20px; z-index: 99998;
      width: 360px; height: 520px;
      background: ${COLORS.bg}; border: 1px solid ${COLORS.border};
      border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.6);
      display: none; flex-direction: column;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
      color: ${COLORS.text}; font-size: 13px;
    }
    
    #gamecs-widget-header {
      padding: 14px 16px; border-bottom: 1px solid ${COLORS.border};
      display: flex; justify-content: space-between; align-items: center;
      background: ${COLORS.card}; border-radius: 12px 12px 0 0;
    }
    #gamecs-widget-header h3 { margin: 0; font-size: 15px; }
    #gamecs-widget-header .close-btn {
      cursor: pointer; font-size: 18px; color: ${COLORS.textSec};
      background: none; border: none; padding: 0;
    }
    #gamecs-widget-header .close-btn:hover { color: ${COLORS.text}; }
    
    #gamecs-widget-messages {
      flex: 1; overflow-y: auto; padding: 12px 16px;
    }
    .gamecs-msg {
      margin-bottom: 10px; max-width: 85%; padding: 8px 12px;
      border-radius: 10px; font-size: 13px; line-height: 1.5; 
      word-wrap: break-word;
    }
    .gamecs-msg.player {
      background: rgba(88,166,255,0.1);
      border: 1px solid rgba(88,166,255,0.2);
      margin-right: auto;
    }
    .gamecs-msg.agent {
      background: rgba(57,210,192,0.1);
      border: 1px solid rgba(57,210,192,0.2);
      margin-left: auto;
    }
    .gamecs-msg.system {
      background: ${COLORS.card};
      border: 1px solid ${COLORS.border};
      margin: 0 auto; text-align: center; font-size: 12px;
      color: ${COLORS.textSec}; max-width: 100%;
    }
    .gamecs-msg .sender {
      font-size: 11px; color: ${COLORS.textSec}; margin-bottom: 3px;
    }
    .gamecs-msg .translated {
      margin-top: 6px; padding-top: 6px;
      border-top: 1px dashed rgba(57,210,192,0.3);
      font-size: 12px; color: #39d2c0;
    }
    .gamecs-msg .time {
      font-size: 10px; color: ${COLORS.textSec}; margin-top: 3px;
    }
    
    #gamecs-widget-input-area {
      padding: 10px 16px; border-top: 1px solid ${COLORS.border};
      display: flex; gap: 8px; background: ${COLORS.card};
      border-radius: 0 0 12px 12px;
    }
    #gamecs-widget-input {
      flex: 1; background: ${COLORS.bg};
      border: 1px solid ${COLORS.border}; border-radius: 8px;
      padding: 8px 12px; color: ${COLORS.text}; font-size: 13px;
      outline: none; resize: none; height: 36px;
      font-family: inherit;
    }
    #gamecs-widget-input:focus { border-color: ${COLORS.primary}; }
    #gamecs-widget-send {
      background: ${COLORS.primary}; color: #fff; border: none;
      border-radius: 8px; padding: 8px 16px; cursor: pointer;
      font-size: 13px; font-weight: 600; white-space: nowrap;
    }
    #gamecs-widget-send:hover { filter: brightness(1.15); }
    #gamecs-widget-send:disabled { opacity: 0.5; cursor: not-allowed; }
    
    /* Ticket form */
    #gamecs-widget-form { flex: 1; padding: 16px; overflow-y: auto; }
    #gamecs-widget-form .form-group { margin-bottom: 12px; }
    #gamecs-widget-form label {
      display: block; font-size: 12px; color: ${COLORS.textSec};
      margin-bottom: 4px;
    }
    #gamecs-widget-form input, #gamecs-widget-form textarea, #gamecs-widget-form select {
      width: 100%; background: ${COLORS.bg};
      border: 1px solid ${COLORS.border}; border-radius: 6px;
      padding: 8px 10px; color: ${COLORS.text}; font-size: 13px;
      outline: none; font-family: inherit; box-sizing: border-box;
    }
    #gamecs-widget-form textarea { resize: vertical; min-height: 60px; }
    #gamecs-widget-form .submit-btn {
      background: linear-gradient(135deg, #58a6ff, #bc8cff);
      color: #fff; border: none; border-radius: 8px;
      padding: 10px 20px; cursor: pointer; font-size: 14px;
      width: 100%; font-weight: 600;
    }
    #gamecs-widget-form .submit-btn:hover { filter: brightness(1.15); }
    #gamecs-widget-form .submit-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    
    .gamecs-connecting {
      text-align: center; color: ${COLORS.textSec};
      padding: 20px; font-size: 13px;
    }
    .gamecs-typing {
      text-align: center; color: ${COLORS.textSec};
      font-size: 11px; margin-bottom: 8px;
    }
  `;
  
  // ─── Inject Styles ────────────────────────────────────────────
  
  const styleSheet = document.createElement('style');
  styleSheet.textContent = styles;
  document.head.appendChild(styleSheet);
  
  // ─── Widget HTML ──────────────────────────────────────────────
  
  const btn = document.createElement('button');
  btn.id = 'gamecs-widget-btn';
  btn.innerHTML = '💬<span class="badge" id="gamecs-badge">0</span>';
  document.body.appendChild(btn);
  
  const panel = document.createElement('div');
  panel.id = 'gamecs-widget-panel';
  panel.innerHTML = `
    <div id="gamecs-widget-header">
      <h3>🎮 游戏客服</h3>
      <button class="close-btn" id="gamecs-close">✕</button>
    </div>
    <div id="gamecs-widget-messages" style="display:none">
      <div class="gamecs-connecting">正在连接...</div>
    </div>
    <div id="gamecs-widget-form">
      <div class="form-group">
        <label>问题标题</label>
        <input type="text" id="gamecs-form-title" placeholder="请简要描述您的问题">
      </div>
      <div class="form-group">
        <label>问题描述</label>
        <textarea id="gamecs-form-desc" placeholder="请详细描述您遇到的问题..."></textarea>
      </div>
      <div class="form-group">
        <label>分类</label>
        <select id="gamecs-form-category">
          <option value="payment">充值问题</option>
          <option value="account">账号问题</option>
          <option value="gameplay">游戏问题</option>
          <option value="bug">BUG反馈</option>
          <option value="report">举报</option>
          <option value="other">其他</option>
        </select>
      </div>
      <button class="submit-btn" id="gamecs-submit">提交工单</button>
    </div>
    <div id="gamecs-widget-input-area" style="display:none">\n      <textarea id="gamecs-widget-input" placeholder="输入消息..." rows="1"></textarea>\n      <button id="gamecs-widget-send" disabled>发送</button>\n    </div>\n    <div style="padding:6px 16px;text-align:center;font-size:10px;color:var(--text-muted,#484f58);border-top:1px solid var(--border,#30363d);background:var(--bg-card,#1c2128)">\n      南京云霞飞信息技术有限公司\n    </div>
  `;
  document.body.appendChild(panel);
  
  // ─── DOM References ───────────────────────────────────────────
  
  const msgContainer = document.getElementById('gamecs-widget-messages');
  const formContainer = document.getElementById('gamecs-widget-form');
  const inputArea = document.getElementById('gamecs-widget-input-area');
  const input = document.getElementById('gamecs-widget-input');
  const sendBtn = document.getElementById('gamecs-widget-send');
  
  // ─── Helper Functions ─────────────────────────────────────────
  
  function timeAgo(iso) {
    if (!iso) return '';
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return '刚刚';
    if (mins < 60) return mins + '分钟前';
    return Math.floor(mins / 60) + '小时前';
  }
  
  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }
  
  function addMessage(msg) {
    const div = document.createElement('div');
    const type = msg.sender_type === 'player' ? 'player' : msg.sender_type === 'system' ? 'system' : 'agent';
    div.className = 'gamecs-msg ' + type;
    
    let html = '';
    if (type !== 'system') {
      html += `<div class="sender">${escapeHtml(msg.sender_name)}</div>`;
    }
    html += `<div>${escapeHtml(msg.content)}</div>`;
    if (msg.translated_content) {
      html += `<div class="translated">🌍 ${escapeHtml(msg.translated_content)}</div>`;
    }
    if (msg.timestamp) {
      html += `<div class="time">${timeAgo(msg.timestamp)}</div>`;
    }
    
    div.innerHTML = html;
    msgContainer.appendChild(div);
    msgContainer.scrollTop = msgContainer.scrollHeight;
  }
  
  // ─── WebSocket Connection ─────────────────────────────────────
  
  function connectWs(tId) {
    if (ws) ws.close();
    ticketId = tId;
    
    const url = WS_BASE + '/ws/chat/' + tId + '?role=player';
    ws = new WebSocket(url);
    
    ws.onopen = function() {
      msgContainer.innerHTML = '';
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    };
    
    ws.onmessage = function(event) {
      const data = JSON.parse(event.data);
      
      if (data.type === 'connected') {
        msgContainer.innerHTML = '';
        const sysMsg = document.createElement('div');
        sysMsg.className = 'gamecs-msg system';
        sysMsg.textContent = '🟢 已连接到客服 (' + (data.player_language_flag || '🌐') + ' ' + (data.player_language_name || '') + ')';
        msgContainer.appendChild(sysMsg);
        return;
      }
      
      if (data.type === 'message') {
        addMessage(data);
        return;
      }
    };
    
    ws.onclose = function() {
      input.disabled = true;
      sendBtn.disabled = true;
      // Auto reconnect
      reconnectTimer = setTimeout(function() {
        if (ticketId) connectWs(ticketId);
      }, 3000);
    };
    
    ws.onerror = function() {
      // Will trigger onclose
    };
  }
  
  function sendMessage() {
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    
    ws.send(JSON.stringify({
      type: 'message',
      content: text,
      sender_name: PLAYER_NAME,
    }));
    
    input.value = '';
    input.style.height = '36px';
  }
  
  // ─── Create Ticket via API ────────────────────────────────────
  
  async function createTicket() {
    const title = document.getElementById('gamecs-form-title').value.trim();
    const desc = document.getElementById('gamecs-form-desc').value.trim();
    const category = document.getElementById('gamecs-form-category').value;
    
    if (!title) { alert('请输入问题标题'); return; }
    
    const submitBtn = document.getElementById('gamecs-submit');
    submitBtn.disabled = true;
    submitBtn.textContent = '提交中...';
    
    try {
      const resp = await fetch(SERVER + '/api/external/tickets', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({
          player_id: PLAYER_ID || 'web_' + Date.now(),
          player_name: PLAYER_NAME,
          language: LANGUAGE,
          title: title,
          description: desc,
          category: category,
          priority: 'medium',
        }),
      });
      
      if (!resp.ok) throw new Error('创建失败');
      
      const data = await resp.json();
      
      // Switch to chat mode
      formContainer.style.display = 'none';
      msgContainer.style.display = 'block';
      inputArea.style.display = 'flex';
      
      connectWs(data.ticket_id);
      
    } catch (e) {
      alert('提交失败: ' + e.message);
      submitBtn.disabled = false;
      submitBtn.textContent = '提交工单';
    }
  }
  
  // ─── Toggle Panel ─────────────────────────────────────────────
  
  btn.onclick = function() {
    isOpen = !isOpen;
    panel.style.display = isOpen ? 'flex' : 'none';
    btn.innerHTML = isOpen ? '✕' : '💬';
    
    if (isOpen && PLAYER_ID && MODE === 'chat') {
      // Try to open existing ticket or create new one
      formContainer.style.display = 'block';
      msgContainer.style.display = 'none';
      inputArea.style.display = 'none';
    }
  };
  
  document.getElementById('gamecs-close').onclick = function() {
    isOpen = false;
    panel.style.display = 'none';
    btn.innerHTML = '💬';
  };
  
  // ─── Input Events ─────────────────────────────────────────────
  
  document.getElementById('gamecs-submit').onclick = createTicket;
  
  input.oninput = function() {
    sendBtn.disabled = !this.value.trim();
    this.style.height = '36px';
    this.style.height = Math.min(this.scrollHeight, 80) + 'px';
  };
  
  input.onkeydown = function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };
  
  sendBtn.onclick = sendMessage;
  
  // ─── Init ─────────────────────────────────────────────────────
  
  console.log('🎮 Game CS Chat Widget loaded. API Key: ' + (API_KEY ? '✓' : '✗'));
  
})();
