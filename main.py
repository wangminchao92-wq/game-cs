"""Game Customer Service Management System - FastAPI Backend"""
import datetime
import random
import string
import asyncio
import json
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, desc

from database import init_db, get_db, SessionLocal
from models import (
    Base, Agent, Player, Ticket, TicketMessage, KnowledgeArticle, ApiKey,
    TicketPriority, TicketStatus, TicketCategory,
)
from translation_service import (
    translate, detect_language, suggest_reply,
    get_language_name, get_language_flag, LANGUAGE_MAP,
)

app = FastAPI(title="Game CS Manager", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Helper ───────────────────────────────────────────────────────────

def gen_ticket_id():
    ts = datetime.datetime.utcnow().strftime("%Y%m%d")
    suf = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"CS-{ts}-{suf}"


# ─── WebSocket Connection Manager ─────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # ticket_id -> {player_ws, agent_ws[]}
        self.active_connections: dict[str, dict] = {}
        # ws -> ticket_id mapping
        self.ws_to_ticket: dict[WebSocket, str] = {}
        # ws -> role mapping
        self.ws_to_role: dict[WebSocket, str] = {}
    
    async def connect(self, ws: WebSocket, ticket_id: str, role: str):
        await ws.accept()
        if ticket_id not in self.active_connections:
            self.active_connections[ticket_id] = {"player": None, "agents": []}
        if role == "player":
            self.active_connections[ticket_id]["player"] = ws
        else:
            self.active_connections[ticket_id]["agents"].append(ws)
        self.ws_to_ticket[ws] = ticket_id
        self.ws_to_role[ws] = role
    
    async def disconnect(self, ws: WebSocket):
        ticket_id = self.ws_to_ticket.get(ws)
        if ticket_id and ticket_id in self.active_connections:
            conn = self.active_connections[ticket_id]
            if conn["player"] == ws:
                conn["player"] = None
            elif ws in conn["agents"]:
                conn["agents"].remove(ws)
            # Clean up empty connections
            if not conn["player"] and not conn["agents"]:
                del self.active_connections[ticket_id]
        self.ws_to_ticket.pop(ws, None)
        self.ws_to_role.pop(ws, None)
    
    async def send_to_ticket(self, ticket_id: str, message: dict):
        """Send message to all connections on this ticket."""
        conn = self.active_connections.get(ticket_id)
        if not conn:
            return
        msg_json = json.dumps(message)
        targets = []
        if conn["player"]:
            targets.append(conn["player"])
        targets.extend(conn["agents"])
        for ws in targets:
            try:
                await ws.send_text(msg_json)
            except:
                pass
    
    async def broadcast_to_agents(self, message: dict):
        """Broadcast a message to all connected agents (across all tickets)."""
        msg_json = json.dumps(message)
        for ws, role in list(self.ws_to_role.items()):
            if role == "agent":
                try:
                    await ws.send_text(msg_json)
                except:
                    pass
    
    def get_active_tickets(self) -> list[dict]:
        """Get list of tickets with active WebSocket connections."""
        result = []
        for ticket_id, conn in self.active_connections.items():
            has_player = conn["player"] is not None
            agent_count = len(conn["agents"])
            if has_player or agent_count > 0:
                result.append({
                    "ticket_id": ticket_id,
                    "has_player": has_player,
                    "agent_count": agent_count,
                })
        return result


manager = ConnectionManager()


# ─── Helper: AI suggestion generator (sync, for WebSocket use) ───


def _generate_suggestion_sync(ticket, player_language):
    """Synchronously generate AI suggestion for a ticket. Used by WebSocket."""
    from translation_service import suggest_reply
    
    # Build conversation history
    history = []
    for m in ticket.messages[:10]:
        lang = m.original_language or player_language
        history.append({
            "sender": m.sender_name,
            "content": m.content,
            "language": lang,
        })
    
    return suggest_reply(
        ticket_title=ticket.title,
        ticket_description=ticket.description,
        conversation_history=history,
        player_language=player_language,
        agent_language="zh-CN",
    )


# ─── Seed Data ────────────────────────────────────────────────────────

def seed_data():
    db = SessionLocal()
    try:
        if db.query(Agent).count() > 0:
            return

        agents = [
            Agent(name="张三", email="zhangsan@gamecs.com", role="supervisor", avatar="🦸"),
            Agent(name="李四", email="lisi@gamecs.com", role="agent", avatar="🧑‍💻"),
            Agent(name="王五", email="wangwu@gamecs.com", role="agent", avatar="👩‍💼"),
            Agent(name="赵六", email="zhaoliu@gamecs.com", role="agent", avatar="🧙"),
        ]
        db.add_all(agents)
        db.flush()

        players = [
            Player(player_id="10001", nickname="剑圣小白", server="S1", level=85, vip_level=8, total_recharge=5280.0, status="active", language="zh-CN"),
            Player(player_id="10002", nickname="法神无双", server="S2", level=92, vip_level=10, total_recharge=12800.0, status="active", language="zh-CN"),
            Player(player_id="10003", nickname="暗夜猎手", server="S1", level=45, vip_level=3, total_recharge=328.0, status="active", language="zh-CN"),
            Player(player_id="10004", nickname="JoãoSilva", server="S3", level=12, vip_level=1, total_recharge=128.0, status="active", language="pt-BR"),
            Player(player_id="10005", nickname="被封的勇士", server="S5", level=67, vip_level=5, total_recharge=1680.0, status="banned", language="zh-CN"),
            Player(player_id="10006", nickname="PedroGamer", server="S4", level=55, vip_level=4, total_recharge=880.0, status="active", language="pt-BR"),
        ]
        db.add_all(players)
        db.flush()

        tickets_data = [
            {"title": "充值未到账", "desc": "我充值了648元，但是游戏币没有到账，已经过去2小时了，请尽快处理！", "cat": TicketCategory.PAYMENT, "pri": TicketPriority.URGENT, "stat": TicketStatus.IN_PROGRESS, "pid": 4, "aid": 2},
            {"title": "账号被盗申诉", "desc": "我的账号被人盗了，装备被交易走了，请帮忙找回。账号ID: 10001", "cat": TicketCategory.ACCOUNT, "pri": TicketPriority.HIGH, "stat": TicketStatus.OPEN, "pid": 1, "aid": None},
            {"title": "游戏BUG反馈", "desc": "在副本'暗影迷窟'第三关，BOSS技能会穿透墙壁，导致无法躲避。请修复。", "cat": TicketCategory.BUG, "pri": TicketPriority.MEDIUM, "stat": TicketStatus.OPEN, "pid": 2, "aid": None},
            {"title": "举报玩家恶意PK", "desc": "玩家'屠夫007'在世界地图连续击杀小号，持续3天了，请处理。", "cat": TicketCategory.REPORT, "pri": TicketPriority.HIGH, "stat": TicketStatus.IN_PROGRESS, "pid": 3, "aid": 3},
            {"title": "充值优惠咨询", "desc": "请问下个月的充值返利活动什么时候开始？想提前规划一下。", "cat": TicketCategory.PAYMENT, "pri": TicketPriority.LOW, "stat": TicketStatus.RESOLVED, "pid": 1, "aid": 1},
            {"title": "技能无法升级", "desc": "我的法师技能'火焰风暴'已经满经验值，但无法升级到5级，提示等级不足。我等级已经85级了。", "cat": TicketCategory.GAMEPLAY, "pri": TicketPriority.MEDIUM, "stat": TicketStatus.OPEN, "pid": 2, "aid": None},
            {"title": "封号申诉", "desc": "我在S5的账号被永久封禁了，我没有使用外挂，请复查。账号ID: 10005", "cat": TicketCategory.ACCOUNT, "pri": TicketPriority.HIGH, "stat": TicketStatus.WAITING_PLAYER, "pid": 5, "aid": 4},
            {"title": "Não recebi meus itens", "desc": "Olá, comprei 500 moedas do jogo mas não recebi. Já esperei 3 horas. Meu ID é 10006. Por favor, me ajude!", "cat": TicketCategory.PAYMENT, "pri": TicketPriority.URGENT, "stat": TicketStatus.OPEN, "pid": 6, "aid": None},
        ]
        now = datetime.datetime.utcnow()
        for i, t in enumerate(tickets_data):
            ticket = Ticket(
                ticket_id=gen_ticket_id(),
                title=t["title"], description=t["desc"],
                category=t["cat"], priority=t["pri"], status=t["stat"],
                player_id=t["pid"], assigned_to=t["aid"],
                created_at=now - datetime.timedelta(hours=random.randint(1, 72)),
            )
            db.add(ticket)
            db.flush()
            # Add an initial message
            player_lang = players[t["pid"]-1].language if t["pid"] <= len(players) else "zh-CN"
            msg = TicketMessage(
                ticket_id=ticket.id,
                sender_type="player",
                sender_name=players[t["pid"]-1].nickname,
                content=t["desc"],
                original_language=player_lang,
                created_at=ticket.created_at,
            )
            db.add(msg)

        # Knowledge base
        articles = [
            KnowledgeArticle(title="充值未到账处理流程", content="""# 充值未到账处理流程

## 第一步：确认充值信息
- 询问玩家充值金额、充值方式（支付宝/微信/银行卡）
- 获取充值订单号或截图
- 确认充值时间

## 第二步：后台核查
1. 登录支付管理后台 → 订单查询
2. 输入订单号检索
3. 确认支付状态（成功/失败/处理中）

## 第三步：补发操作
- 如果支付成功但未到账 → 手动补发
- 如果支付失败 → 引导玩家联系支付平台
- 如果处理中 → 告知玩家等待15-30分钟

## 第四步：记录
- 在工单中详细记录补发操作
- 标记相关订单号以便后续核查""",
                category="payment", tags="充值,到账,补发,订单", helpful_count=45),
            KnowledgeArticle(title="账号被盗处理标准", content="""# 账号被盗处理标准

## 受理条件
- 玩家需提供注册邮箱/手机号验证
- 提供最后登录时间
- 说明疑似被盗时间

## 处理流程
1. 验证玩家身份（绑定手机/邮箱验证码）
2. 冻结账号，防止进一步损失
3. 查询登录IP记录，确认异常登录
4. 回滚被盗期间装备/道具交易记录
5. 重置密码并告知玩家
6. 建议开启二次验证

## 注意事项
- 回滚操作需supervisor审批
- 记录所有操作日志""",
                category="account", tags="被盗,申诉,回滚,安全", helpful_count=32),
            KnowledgeArticle(title="举报处理SOP", content="""# 玩家举报处理SOP

## 举报类型
1. 恶意PK / 骚扰
2. 使用外挂/脚本
3. 诈骗/虚假交易
4. 违规昵称/发言
5. 利用BUG获利

## 取证要求
- 截图/录屏作为证据
- 系统日志查询
- 交易记录核查

## 处罚标准
| 违规类型 | 首次 | 二次 | 三次 |
|---------|------|-----|-----|
| 恶意PK | 警告 | 封禁3天 | 封禁7天 |
| 外挂 | 封禁7天 | 封禁30天 | 永久 |
| 诈骗 | 封禁30天 | 永久 | - |
| 违规昵称 | 强制改名 | 封禁1天 | 封禁3天 |""",
                category="report", tags="举报,处理,处罚,外挂,PK", helpful_count=28),
            KnowledgeArticle(title="服务器状态维护公告模板", content="""# 维护公告模板

## 常规维护
标题：【维护】{服务器名称}停机维护公告
内容：
亲爱的玩家：
为了提供更好的游戏体验，{服务器名称}将于 {开始时间} - {预计结束时间} 进行停机维护。
维护内容：
1. {更新内容1}
2. {更新内容2}

维护期间无法登录游戏，感谢您的理解与支持！

## 紧急维护
标题：【紧急维护】{服务器名称}临时维护公告
内容：
亲爱的玩家：
由于{原因}，{服务器名称}将于 {开始时间} 进行紧急维护，预计时长 {预计时长}。
维护补偿：维护结束后将通过邮件发放{补偿内容}。""",
                category="general", tags="维护,公告,模板", helpful_count=56),
        ]
        db.add_all(articles)
        db.commit()
    finally:
        db.close()

# ─── API Routes ───────────────────────────────────────────────────────

# -- Dashboard --

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(days=7)

    total_tickets = db.query(Ticket).count()
    open_tickets = db.query(Ticket).filter(Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])).count()
    resolved_tickets = db.query(Ticket).filter(Ticket.status == TicketStatus.RESOLVED).count()
    urgent_tickets = db.query(Ticket).filter(
        Ticket.priority == TicketPriority.URGENT,
        Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]),
    ).count()

    # Tickets by status
    status_counts = db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all()

    # Tickets by category this week
    cat_counts = db.query(Ticket.category, func.count(Ticket.id)).filter(
        Ticket.created_at >= week_ago
    ).group_by(Ticket.category).all()

    # Recent tickets
    recent = db.query(Ticket).order_by(desc(Ticket.created_at)).limit(5).all()
    recent_data = []
    for t in recent:
        pname = t.player.nickname if t.player else "未知"
        aname = t.assigned_agent.name if t.assigned_agent else None
        recent_data.append({
            "id": t.ticket_id, "title": t.title, "status": t.status.value,
            "priority": t.priority.value, "player": pname, "agent": aname,
            "created": t.created_at.isoformat() if t.created_at else None,
        })

    # Avg resolution time (hours)
    resolved_list = db.query(Ticket).filter(
        Ticket.status == TicketStatus.RESOLVED,
        Ticket.resolved_at.isnot(None),
    ).all()
    avg_resolve_hours = 0
    if resolved_list:
        diffs = [(t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved_list]
        avg_resolve_hours = round(sum(diffs) / len(diffs), 1)

    # Agent workload
    agent_rows = db.query(
        Agent.id, Agent.name, Agent.avatar,
        func.count(Ticket.id).label("open_count"),
    ).outerjoin(Ticket, (Ticket.assigned_to == Agent.id) & Ticket.status.in_(
        [TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_PLAYER]
    )).group_by(Agent.id).all()

    agent_workload = [{
        "id": r[0], "name": r[1], "avatar": r[2], "open_count": r[3]
    } for r in agent_rows]

    return {
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "resolved_tickets": resolved_tickets,
        "urgent_tickets": urgent_tickets,
        "avg_resolve_hours": avg_resolve_hours,
        "status_counts": [{"status": s.value if hasattr(s, 'value') else s, "count": c} for s, c in status_counts],
        "category_counts": [{"category": c.value if hasattr(c, 'value') else c, "count": n} for c, n in cat_counts],
        "recent_tickets": recent_data,
        "agent_workload": agent_workload,
    }


# -- Tickets --

@app.get("/api/tickets")
def list_tickets(
    status: str = None, priority: str = None, category: str = None,
    agent_id: int = None, q: str = "",
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Ticket)
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if category:
        query = query.filter(Ticket.category == category)
    if agent_id:
        query = query.filter(Ticket.assigned_to == agent_id)
    if q:
        query = query.filter(
            Ticket.title.ilike(f"%{q}%") | Ticket.description.ilike(f"%{q}%") | Ticket.ticket_id.ilike(f"%{q}%")
        )

    total = query.count()
    tickets = query.order_by(desc(Ticket.priority), desc(Ticket.created_at)).offset((page-1)*per_page).limit(per_page).all()

    result = []
    for t in tickets:
        result.append({
            "id": t.id, "ticket_id": t.ticket_id, "title": t.title,
            "category": t.category.value if t.category else None,
            "priority": t.priority.value if t.priority else None,
            "status": t.status.value if t.status else None,
            "player_id": t.player.player_id if t.player else None,
            "player_name": t.player.nickname if t.player else "未知",
            "agent_name": t.assigned_agent.name if t.assigned_agent else None,
            "agent_avatar": t.assigned_agent.avatar if t.assigned_agent else None,
            "msg_count": len(t.messages),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"tickets": result, "total": total, "page": page, "per_page": per_page}


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    messages = []
    for m in ticket.messages:
        messages.append({
            "id": m.id, "sender_type": m.sender_type, "sender_name": m.sender_name,
            "content": m.content, "is_internal": m.is_internal,
            "original_language": m.original_language,
            "language_name": get_language_name(m.original_language),
            "language_flag": get_language_flag(m.original_language),
            "translated_content": m.translated_content,
            "is_ai_suggested": m.is_ai_suggested,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return {
        "id": ticket.id, "ticket_id": ticket.ticket_id, "title": ticket.title,
        "description": ticket.description,
        "category": ticket.category.value if ticket.category else None,
        "priority": ticket.priority.value if ticket.priority else None,
        "status": ticket.status.value if ticket.status else None,
        "ai_mode": ticket.ai_mode,
        "player": {
            "id": ticket.player.id, "player_id": ticket.player.player_id,
            "nickname": ticket.player.nickname, "server": ticket.player.server,
            "level": ticket.player.level, "vip_level": ticket.player.vip_level,
            "total_recharge": ticket.player.total_recharge, "status": ticket.player.status,
            "language": ticket.player.language,
            "language_name": get_language_name(ticket.player.language),
            "language_flag": get_language_flag(ticket.player.language),
            "last_login": ticket.player.last_login.isoformat() if ticket.player.last_login else None,
        } if ticket.player else None,
        "agent": {
            "id": ticket.assigned_agent.id, "name": ticket.assigned_agent.name,
            "avatar": ticket.assigned_agent.avatar, "role": ticket.assigned_agent.role,
        } if ticket.assigned_agent else None,
        "messages": messages,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


@app.post("/api/tickets")
def create_ticket(data: dict, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.player_id == data.get("player_id")).first()
    if not player:
        raise HTTPException(400, "玩家不存在")

    ticket = Ticket(
        ticket_id=gen_ticket_id(),
        title=data["title"],
        description=data.get("description", ""),
        category=data.get("category", TicketCategory.OTHER),
        priority=data.get("priority", TicketPriority.MEDIUM),
        status=TicketStatus.OPEN,
        player_id=player.id,
        assigned_to=data.get("assigned_to"),
    )
    db.add(ticket)
    db.flush()

    msg = TicketMessage(
        ticket_id=ticket.id, sender_type="player",
        sender_name=player.nickname, content=data.get("description", ""),
    )
    db.add(msg)
    db.commit()
    return {"ticket_id": ticket.ticket_id}


@app.put("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: str, data: dict, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    if "status" in data:
        ticket.status = data["status"]
        if data["status"] == TicketStatus.RESOLVED.value:
            ticket.resolved_at = datetime.datetime.utcnow()
    if "priority" in data:
        ticket.priority = data["priority"]
    if "category" in data:
        ticket.category = data["category"]
    if "assigned_to" in data:
        ticket.assigned_to = data["assigned_to"]
    if "title" in data:
        ticket.title = data["title"]
    if "ai_mode" in data:
        ticket.ai_mode = data["ai_mode"]

    ticket.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.post("/api/tickets/{ticket_id}/messages")
def add_message(ticket_id: str, data: dict, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    sender_type = data.get("sender_type", "agent")
    content = data["content"]
    is_internal = data.get("is_internal", False)
    is_ai_suggested = data.get("is_ai_suggested", False)

    # Default: agent messages are in Chinese
    original_language = data.get("original_language", "zh-CN" if sender_type == "agent" else "auto")

    # Auto-translate both directions
    translated_content = None
    if ticket.ai_mode and not is_internal and ticket.player:
        player_lang = ticket.player.language
        if sender_type == "agent" and player_lang != "zh-CN":
            # Agent Chinese → Player's language
            try:
                translated_content = translate(content, "zh-CN", player_lang)
            except Exception:
                pass
        elif sender_type == "player" and player_lang != "zh-CN":
            # Player's language → Chinese for agent
            try:
                translated_content = translate(content, player_lang, "zh-CN")
            except Exception:
                pass

    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_type=sender_type,
        sender_name=data.get("sender_name", "系统"),
        content=content,
        original_language=original_language,
        translated_content=translated_content,
        is_ai_suggested=is_ai_suggested,
        is_internal=is_internal,
    )
    db.add(msg)
    ticket.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True, "translated_content": translated_content}


# -- Players --

@app.get("/api/players")
def list_players(q: str = "", page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    query = db.query(Player)
    if q:
        query = query.filter(
            Player.player_id.ilike(f"%{q}%") | Player.nickname.ilike(f"%{q}%")
        )
    total = query.count()
    players = query.offset((page-1)*per_page).limit(per_page).all()

    result = []
    for p in players:
        ticket_count = db.query(Ticket).filter(Ticket.player_id == p.id).count()
        open_ticket_count = db.query(Ticket).filter(
            Ticket.player_id == p.id,
            Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]),
        ).count()
        result.append({
            "id": p.id, "player_id": p.player_id, "nickname": p.nickname,
            "server": p.server, "level": p.level, "vip_level": p.vip_level,
            "total_recharge": p.total_recharge, "status": p.status,
            "language": p.language,  # Multi-language support
            "language_name": get_language_name(p.language),
            "language_flag": get_language_flag(p.language),
            "register_date": p.register_date.isoformat() if p.register_date else None,
            "last_login": p.last_login.isoformat() if p.last_login else None,
            "ticket_count": ticket_count, "open_ticket_count": open_ticket_count,
        })

    return {"players": result, "total": total, "page": page, "per_page": per_page}


@app.get("/api/players/{player_id}")
def get_player(player_id: str, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if not player:
        raise HTTPException(404, "玩家不存在")

    tickets = db.query(Ticket).filter(Ticket.player_id == player.id).order_by(desc(Ticket.created_at)).all()
    ticket_data = [{
        "ticket_id": t.ticket_id, "title": t.title, "status": t.status.value,
        "priority": t.priority.value, "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in tickets]

    return {
        "id": player.id, "player_id": player.player_id, "nickname": player.nickname,
        "server": player.server, "level": player.level, "vip_level": player.vip_level,
        "total_recharge": player.total_recharge, "status": player.status,
        "language": player.language,
        "language_name": get_language_name(player.language),
        "language_flag": get_language_flag(player.language),
        "register_date": player.register_date.isoformat() if player.register_date else None,
        "last_login": player.last_login.isoformat() if player.last_login else None,
        "notes": player.notes,
        "tickets": ticket_data,
    }


# -- Agents --

@app.get("/api/agents")
def list_agents(db: Session = Depends(get_db)):
    agents = db.query(Agent).all()
    result = []
    for a in agents:
        open_count = db.query(Ticket).filter(
            Ticket.assigned_to == a.id,
            Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_PLAYER]),
        ).count()
        resolved_count = db.query(Ticket).filter(
            Ticket.assigned_to == a.id, Ticket.status == TicketStatus.RESOLVED,
        ).count()
        result.append({
            "id": a.id, "name": a.name, "email": a.email, "role": a.role,
            "avatar": a.avatar, "is_active": a.is_active,
            "open_tickets": open_count, "resolved_tickets": resolved_count,
        })
    return {"agents": result}


# -- Knowledge Base --

@app.get("/api/kb")
def list_knowledge(q: str = "", category: str = None, db: Session = Depends(get_db)):
    query = db.query(KnowledgeArticle)
    if q:
        query = query.filter(
            KnowledgeArticle.title.ilike(f"%{q}%") | KnowledgeArticle.content.ilike(f"%{q}%")
        )
    if category:
        query = query.filter(KnowledgeArticle.category == category)
    articles = query.order_by(desc(KnowledgeArticle.helpful_count)).all()
    return {"articles": [{
        "id": a.id, "title": a.title, "category": a.category,
        "tags": a.tags.split(",") if a.tags else [],
        "helpful_count": a.helpful_count,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    } for a in articles]}


@app.get("/api/kb/{article_id}")
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(404, "文章不存在")
    return {
        "id": article.id, "title": article.title, "content": article.content,
        "category": article.category, "tags": article.tags.split(",") if article.tags else [],
        "helpful_count": article.helpful_count,
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
    }


@app.post("/api/kb")
def create_article(data: dict, db: Session = Depends(get_db)):
    article = KnowledgeArticle(
        title=data["title"], content=data["content"],
        category=data.get("category", "general"),
        tags=data.get("tags", ""),
    )
    db.add(article)
    db.commit()
    return {"id": article.id}


@app.put("/api/kb/{article_id}")
def update_article(article_id: int, data: dict, db: Session = Depends(get_db)):
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(404, "文章不存在")
    for field in ["title", "content", "category", "tags"]:
        if field in data:
            setattr(article, field, data[field])
    db.commit()
    return {"ok": True}


@app.post("/api/kb/{article_id}/helpful")
def mark_helpful(article_id: int, db: Session = Depends(get_db)):
    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(404, "文章不存在")
    article.helpful_count += 1
    db.commit()
    return {"helpful_count": article.helpful_count}


# ─── Multi-Language & AI ─────────────────────────────────────────


@app.get("/api/languages")
def list_languages():
    """Get list of supported languages."""
    return {
        "languages": [
            {"code": code, "name": name, "flag": get_language_flag(code)}
            for code, name in LANGUAGE_MAP.items()
        ]
    }


@app.post("/api/translate")
def translate_text(data: dict):
    """Translate text between languages."""
    text = data.get("text", "")
    source = data.get("source_lang", "auto")
    target = data.get("target_lang", "zh-CN")
    if not text:
        raise HTTPException(400, "请提供需要翻译的文本")
    result = translate(text, source, target)
    return {"original": text, "translated": result, "source_lang": source, "target_lang": target}


@app.post("/api/language/detect")
def detect_text_language(data: dict):
    """Detect language of given text."""
    text = data.get("text", "")
    if not text:
        raise HTTPException(400, "请提供文本")
    code = detect_language(text)
    return {"code": code, "name": get_language_name(code), "flag": get_language_flag(code)}


@app.put("/api/players/{player_id}/language")
def update_player_language(player_id: str, data: dict, db: Session = Depends(get_db)):
    """Update player's language setting."""
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if not player:
        raise HTTPException(404, "玩家不存在")
    lang = data.get("language", "zh-CN")
    if lang not in LANGUAGE_MAP:
        raise HTTPException(400, f"不支持的语言: {lang}")
    player.language = lang
    db.commit()
    return {"ok": True, "language": lang, "language_name": get_language_name(lang)}


@app.put("/api/tickets/{ticket_id}/ai-mode")
def toggle_ai_mode(ticket_id: str, data: dict, db: Session = Depends(get_db)):
    """Toggle AI-assisted mode on/off for a ticket."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")
    ticket.ai_mode = data.get("ai_mode", True)
    db.commit()
    return {"ok": True, "ai_mode": ticket.ai_mode}


@app.post("/api/tickets/{ticket_id}/ai-suggest")
def ai_suggest_reply(ticket_id: str, db: Session = Depends(get_db)):
    """Generate AI-suggested reply for a ticket."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    # Build conversation history
    history = []
    for m in ticket.messages[:10]:  # Last 10 messages
        lang = m.original_language or (ticket.player.language if ticket.player else "zh-CN")
        history.append({
            "sender": m.sender_name,
            "content": m.content,
            "language": lang,
        })

    player_lang = ticket.player.language if ticket.player else "zh-CN"

    try:
        suggestion = suggest_reply(
            ticket_title=ticket.title,
            ticket_description=ticket.description,
            conversation_history=history,
            player_language=player_lang,
            agent_language="zh-CN",
        )
        return suggestion
    except Exception as e:
        raise HTTPException(500, f"AI建议生成失败: {str(e)}")


@app.post("/api/tickets/{ticket_id}/auto-reply")
def ai_auto_reply(ticket_id: str, data: dict, db: Session = Depends(get_db)):
    """AI auto-reply: generate suggestion + send as agent message with auto-translation."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    # First get suggestion
    history = []
    for m in ticket.messages[:10]:
        lang = m.original_language or (ticket.player.language if ticket.player else "zh-CN")
        history.append({
            "sender": m.sender_name,
            "content": m.content,
            "language": lang,
        })

    player_lang = ticket.player.language if ticket.player else "zh-CN"
    suggestion = suggest_reply(
        ticket_title=ticket.title,
        ticket_description=ticket.description,
        conversation_history=history,
        player_language=player_lang,
        agent_language="zh-CN",
    )

    reply_zh = suggestion.get("reply_zh", "")
    if not reply_zh:
        raise HTTPException(500, "AI未能生成回复")

    # Auto-translate the reply
    translated = None
    if player_lang != "zh-CN":
        translated = translate(reply_zh, "zh-CN", player_lang)

    # Save the message
    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_type="agent",
        sender_name="AI助手",
        content=reply_zh,
        original_language="zh-CN",
        translated_content=translated,
        is_ai_suggested=True,
        is_internal=data.get("is_internal", False),
    )
    db.add(msg)
    ticket.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "ok": True,
        "reply_zh": reply_zh,
        "reply_translated": translated,
    }


# -- Analytics --

@app.get("/api/analytics")
def analytics(period: str = "7d", db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    if period == "7d":
        start = now - datetime.timedelta(days=7)
    elif period == "30d":
        start = now - datetime.timedelta(days=30)
    else:
        start = now - datetime.timedelta(days=7)

    # Daily ticket creation
    days_data = db.query(
        extract('year', Ticket.created_at).label('year'),
        extract('month', Ticket.created_at).label('month'),
        extract('day', Ticket.created_at).label('day'),
        func.count(Ticket.id).label('count'),
    ).filter(Ticket.created_at >= start).group_by('year', 'month', 'day').order_by('year', 'month', 'day').all()

    daily = []
    for d in days_data:
        daily.append({"date": f"{int(d.year)}-{int(d.month):02d}-{int(d.day):02d}", "count": d.count})

    # Category distribution
    cat_data = db.query(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category).all()
    categories = [{"name": c.value if hasattr(c, 'value') else str(c), "count": n} for c, n in cat_data]

    # Agent performance
    agent_rows = db.query(
        Agent.id, Agent.name, Agent.avatar,
        func.count(Ticket.id).filter(Ticket.status == TicketStatus.RESOLVED).label('resolved'),
        func.count(Ticket.id).label('total'),
    ).outerjoin(Ticket, Ticket.assigned_to == Agent.id).group_by(Agent.id).all()

    performance = [{
        "name": r[1], "avatar": r[2],
        "resolved": r[3], "total": r[4],
        "resolve_rate": round(r[3] / r[4] * 100, 1) if r[4] > 0 else 0,
    } for r in agent_rows]

    # Priority distribution
    priority_data = db.query(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority).all()
    priorities = [{"name": p.value if hasattr(p, 'value') else str(p), "count": n} for p, n in priority_data]

    return {
        "daily_tickets": daily,
        "category_distribution": categories,
        "agent_performance": performance,
        "priority_distribution": priorities,
    }


# ─── API Key Management ───────────────────────────────────────────

import uuid


@app.post("/api/admin/api-keys")
def create_api_key(data: dict, db: Session = Depends(get_db)):
    """Create a new API Key."""
    name = data.get("name", "未命名")
    website_url = data.get("website_url", "")
    key_value = str(uuid.uuid4())
    api_key = ApiKey(key=key_value, name=name, website_url=website_url)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {
        "id": api_key.id,
        "key": api_key.key,
        "name": api_key.name,
        "website_url": api_key.website_url,
        "is_active": api_key.is_active,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
    }


@app.get("/api/admin/api-keys")
def list_api_keys(db: Session = Depends(get_db)):
    """List all API Keys."""
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return {"api_keys": [{
        "id": k.id,
        "key": k.key,
        "name": k.name,
        "website_url": k.website_url,
        "is_active": k.is_active,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    } for k in keys]}


@app.delete("/api/admin/api-keys/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db)):
    """Delete an API Key."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(404, "API Key 不存在")
    db.delete(key)
    db.commit()
    return {"ok": True}


# ─── External API (API Key Auth) ──────────────────────────────────

from fastapi import Header


def verify_api_key(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    """Verify the X-API-Key header."""
    key = db.query(ApiKey).filter(ApiKey.key == x_api_key, ApiKey.is_active == True).first()
    if not key:
        raise HTTPException(401, "无效的 API Key")
    return key


@app.post("/api/external/tickets")
def external_create_ticket(
    data: dict,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    """Create a new ticket via external API."""
    player_id = data.get("player_id", "")
    player_name = data.get("player_name", "未知玩家")
    server = data.get("server", "S1")
    language = data.get("language", "zh-CN")
    title = data.get("title", "")
    description = data.get("description", "")
    category = data.get("category", TicketCategory.OTHER)
    priority = data.get("priority", TicketPriority.MEDIUM)

    if not title:
        raise HTTPException(400, "title 不能为空")
    if not player_id:
        raise HTTPException(400, "player_id 不能为空")

    # Auto-create player if not exists
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if not player:
        player = Player(
            player_id=player_id,
            nickname=player_name,
            server=server,
            language=language,
            level=1,
            vip_level=0,
            status="active",
        )
        db.add(player)
        db.flush()

    ticket = Ticket(
        ticket_id=gen_ticket_id(),
        title=title,
        description=description,
        category=category,
        priority=priority,
        status=TicketStatus.OPEN,
        player_id=player.id,
    )
    db.add(ticket)
    db.flush()

    # Add initial message
    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_type="player",
        sender_name=player_name,
        content=description,
        original_language=language,
    )
    db.add(msg)
    db.commit()

    return {
        "ticket_id": ticket.ticket_id,
        "status": ticket.status.value,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
    }


@app.get("/api/external/tickets/{ticket_id}")
def external_get_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    """Get ticket details via external API."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    messages = []
    for m in ticket.messages:
        if not m.is_internal:
            messages.append({
                "id": m.id,
                "sender_type": m.sender_type,
                "sender_name": m.sender_name,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            })

    return {
        "ticket_id": ticket.ticket_id,
        "title": ticket.title,
        "status": ticket.status.value if ticket.status else None,
        "priority": ticket.priority.value if ticket.priority else None,
        "category": ticket.category.value if ticket.category else None,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "messages": messages,
    }


@app.post("/api/external/tickets/{ticket_id}/messages")
def external_add_message(
    ticket_id: str,
    data: dict,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    """Add a message to a ticket via external API."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")

    content = data.get("content", "")
    sender_name = data.get("sender_name", "玩家")
    if not content:
        raise HTTPException(400, "content 不能为空")

    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_type="player",
        sender_name=sender_name,
        content=content,
    )
    db.add(msg)
    ticket.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {"ok": True, "message_id": msg.id}


@app.get("/api/external/players/{player_id}")
def external_get_player(
    player_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    """Get player info via external API."""
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if not player:
        raise HTTPException(404, "玩家不存在")

    return {
        "player_id": player.player_id,
        "nickname": player.nickname,
        "server": player.server,
        "level": player.level,
        "vip_level": player.vip_level,
        "status": player.status,
    }


# ─── WebSocket Real-time Chat ─────────────────────────────────────


@app.websocket("/ws/chat/{ticket_id}")
async def websocket_chat(ws: WebSocket, ticket_id: str):
    """Real-time chat via WebSocket.
    
    Role is determined by whether a valid API Key is provided.
    - Player: connects without auth
    - Agent: connects with ?role=agent query param
    """
    import urllib.parse
    
    # Parse query params
    query = ws.url.query if hasattr(ws.url, 'query') else ""
    params = dict(urllib.parse.parse_qsl(query))
    role = params.get("role", "player")
    
    # Create a new DB session for this connection
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        # Verify ticket exists
        ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
        if not ticket:
            await ws.accept()
            await ws.send_text(json.dumps({"type": "error", "message": "工单不存在"}))
            await ws.close()
            return
        
        await manager.connect(ws, ticket_id, role)
        
        # Send connection confirmation
        player = ticket.player
        await ws.send_text(json.dumps({
            "type": "connected",
            "ticket_id": ticket_id,
            "role": role,
            "player_language": player.language if player else "zh-CN",
            "player_language_name": get_language_name(player.language) if player else "中文",
            "player_language_flag": get_language_flag(player.language) if player else "🇨🇳",
        }))
        
        # Send recent messages
        messages = db.query(TicketMessage).filter(
            TicketMessage.ticket_id == ticket.id,
            TicketMessage.is_internal == False,
        ).order_by(TicketMessage.created_at).limit(50).all()
        
        for m in messages:
            await ws.send_text(json.dumps({
                "type": "message",
                "id": m.id,
                "sender_type": m.sender_type,
                "sender_name": m.sender_name,
                "content": m.content,
                "translated_content": m.translated_content,
                "is_ai_suggested": m.is_ai_suggested,
                "timestamp": m.created_at.isoformat() if m.created_at else None,
            }))
        
        # Listen for incoming messages
        while True:
            data = await ws.receive_text()
            msg_data = json.loads(data)
            
            if msg_data.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue
            
            if msg_data.get("type") == "message":
                content = msg_data.get("content", "").strip()
                if not content:
                    continue
                
                sender_name = msg_data.get("sender_name", "玩家" if role == "player" else "客服")
                is_ai = msg_data.get("is_ai_suggested", False)
                
                # Save message to DB
                original_lang = "zh-CN"
                if role == "player" and player:
                    original_lang = player.language
                
                # ─── Auto-translate logic ─────────────────
                # Player → Agent: translate player's msg to Chinese for agent
                # Agent → Player: translate agent's Chinese reply to player's language
                translated = None
                
                if ticket.ai_mode and player:
                    if role == "player" and player.language != "zh-CN":
                        # Player sent non-Chinese → translate to Chinese for agent
                        try:
                            translated = translate(content, player.language, "zh-CN")
                        except Exception:
                            pass
                    elif role == "agent" and player.language != "zh-CN":
                        # Agent sent Chinese → translate to player's language
                        try:
                            translated = translate(content, "zh-CN", player.language)
                        except Exception:
                            pass
                
                msg = TicketMessage(
                    ticket_id=ticket.id,
                    sender_type=role,
                    sender_name=sender_name,
                    content=content,
                    original_language=original_lang,
                    translated_content=translated,
                    is_ai_suggested=is_ai,
                )
                db.add(msg)
                ticket.updated_at = datetime.datetime.utcnow()
                db.commit()
                db.refresh(msg)
                
                # Broadcast to all connections on this ticket
                # Agents see: content=original, translated=Chinese (for player msgs)
                # Players see: content=original, translated=translated reply (for agent msgs)
                broadcast_msg = {
                    "type": "message",
                    "id": msg.id,
                    "sender_type": role,
                    "sender_name": sender_name,
                    "content": content,
                    "translated_content": translated,
                    "is_ai_suggested": is_ai,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                }
                await manager.send_to_ticket(ticket_id, broadcast_msg)
                
                # ─── After player message: auto-generate AI suggestion ───
                if role == "player":
                    # Notify agents about new message
                    await manager.broadcast_to_agents({
                        "type": "new_chat",
                        "ticket_id": ticket_id,
                        "title": ticket.title,
                        "sender": sender_name,
                        "preview": content[:80],
                        "translated_preview": translated[:80] if translated else None,
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                    })
                    
                    # Auto-generate AI suggestion (background task)
                    if ticket.ai_mode and player:
                        try:
                            suggestion = _generate_suggestion_sync(ticket, player.language)
                            if suggestion and suggestion.get("reply_zh"):
                                # Broadcast AI suggestion to agents on this ticket
                                await manager.send_to_ticket(ticket_id, {
                                    "type": "ai_suggestion",
                                    "reply_zh": suggestion["reply_zh"],
                                    "reply_translated": suggestion.get("reply_translated", ""),
                                    "confidence": suggestion.get("confidence", 0),
                                    "suggested_action": suggestion.get("suggested_action", "send_message"),
                                })
                        except Exception:
                            pass
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket Error] {e}")
    finally:
        await manager.disconnect(ws)
        db.close()


# ─── Active Chats API ────────────────────────────────────────────


@app.get("/api/chat/active")
def get_active_chats(db: Session = Depends(get_db)):
    """Get tickets with active WebSocket connections (agent dashboard)."""
    active = manager.get_active_tickets()
    
    result = []
    for a in active:
        ticket = db.query(Ticket).filter(Ticket.ticket_id == a["ticket_id"]).first()
        if not ticket:
            continue
        player = ticket.player
        result.append({
            "ticket_id": ticket.ticket_id,
            "title": ticket.title,
            "player_name": player.nickname if player else "未知",
            "player_language": player.language if player else "zh-CN",
            "player_language_flag": get_language_flag(player.language) if player else "🌐",
            "has_player": a["has_player"],
            "agent_count": a["agent_count"],
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        })
    
    return {"active_chats": result}


@app.get("/api/chat/token/{ticket_id}")
def get_chat_token(ticket_id: str, db: Session = Depends(get_db)):
    """Get WebSocket connection info for a ticket (for embedding)."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "工单不存在")
    
    player = ticket.player
    return {
        "ticket_id": ticket_id,
        "ws_url": f"ws://127.0.0.1:8899/ws/chat/{ticket_id}",
        "player_language": player.language if player else "zh-CN",
        "ai_mode": ticket.ai_mode,
    }


# -- Serve Frontend --


@app.on_event("startup")
def startup():
    init_db()
    seed_data()


@app.get("/")
def serve_index():
    return FileResponse("static/index.html")


@app.get("/api-docs")
@app.get("/api-docs.html")
def serve_api_docs():
    return FileResponse("static/api-docs.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8899)
