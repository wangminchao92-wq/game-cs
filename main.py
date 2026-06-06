"""Game Customer Service Management System - FastAPI Backend"""
import datetime
import random
import string
import asyncio
import json
import os
import uuid
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, desc

from database import init_db, get_db, SessionLocal
from models import (
    Base, Agent, Player, User, SystemSetting, Ticket, TicketMessage, KnowledgeArticle, ApiKey,
    TicketPriority, TicketStatus, TicketCategory,
)
from translation_service import (
    translate, detect_language, suggest_reply,
    get_language_name, get_language_flag, LANGUAGE_MAP,
)
import facebook_news
import feishu_bot
from auth import (
    hash_password, verify_password, create_access_token, decode_token,
    get_current_user, require_super_admin, get_user_info,
)
from fastapi.responses import JSONResponse

app = FastAPI(title="Game CS Manager", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth Middleware ────────────────────────────────────────────────
# Protect all /api/ routes except auth, external, and public endpoints


@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    # Public endpoints: allow without auth
    public_prefixes = (
        "/api/auth/", "/api/external/",
        "/api/languages", "/api/translate", "/api/chat/token/",
    )
    if path.startswith("/api/") and not path.startswith(public_prefixes):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "请先登录"})
        try:
            token = auth.replace("Bearer ", "")
            decode_token(token)  # Will raise on invalid
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "无效的令牌"})
    return await call_next(request)

# ─── Helper ───────────────────────────────────────────────────────────

def gen_ticket_id():
    ts = datetime.datetime.utcnow().strftime("%Y%m%d")
    suf = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"CS-{ts}-{suf}"


# ─── Auto-Assign Logic ──────────────────────────────────────────────

MAX_OPEN_TICKETS = 5
AI_ASSIGN_ENABLED_SETTING = "auto_assign_enabled"


def _is_auto_assign_enabled(db: Session) -> bool:
    """检查自动分单开关是否打开"""
    return get_setting(db, AI_ASSIGN_ENABLED_SETTING, "true") == "true"


def _get_agent_open_counts(db: Session) -> list[dict]:
    """查询每个激活客服的未解决工单数量"""
    from sqlalchemy import func
    open_statuses = [TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_PLAYER]
    counts = db.query(
        Ticket.assigned_to, func.count(Ticket.id).label("cnt")
    ).filter(
        Ticket.status.in_(open_statuses),
        Ticket.assigned_to.isnot(None),
    ).group_by(Ticket.assigned_to).all()
    count_map = {r[0]: r[1] for r in counts}

    # 获取所有激活的客服
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    result = []
    for a in agents:
        result.append({
            "agent_id": a.id,
            "name": a.name,
            "open_count": count_map.get(a.id, 0),
        })
    return result


def auto_assign_ticket(db: Session, ticket_id: int) -> Optional[int]:
    """自动分单：分配给 open_tickets 最少的客服，若都 >=5 则不分配。
    返回分配的 agent_id，或 None。
    """
    if not _is_auto_assign_enabled(db):
        return None

    workloads = _get_agent_open_counts(db)
    if not workloads:
        return None

    # 按 open_count 升序排序
    workloads.sort(key=lambda w: w["open_count"])

    # 最少工单的客服
    best = workloads[0]
    if best["open_count"] >= MAX_OPEN_TICKETS:
        # 所有客服工单都 >= 5，暂不分配
        return None

    # 分配工单
    ticket_obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket_obj:
        ticket_obj.assigned_to = best["agent_id"]
        db.commit()
        return best["agent_id"]
    return None


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


def _generate_suggestion_sync(ticket, player_language, db: Session = None):
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
    
    # Build LLM config + KB context from DB (if available)
    api_config = _build_llm_api_config_from_db(db) if db else None
    kb_context = ""
    if db and get_setting(db, "llm_use_kb", "true") == "true":
        search_text = ticket.title + " " + ticket.description
        kb_context = _search_kb_for_context(db, search_text)
    
    return suggest_reply(
        ticket_title=ticket.title,
        ticket_description=ticket.description,
        conversation_history=history,
        player_language=player_language,
        agent_language="zh-CN",
        kb_context=kb_context,
        api_config=api_config,
    )


# ─── Auth Routes ────────────────────────────────────────────────────


@app.post("/api/auth/login")
def login(data: dict, db: Session = Depends(get_db)):
    """用户登录，返回 JWT 令牌"""
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入用户名和密码")

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")

    token = create_access_token(user_id=user.id, role=user.role, username=user.username)
    return {
        "token": token,
        "user": get_user_info(user),
    }


@app.get("/api/auth/me")
def get_my_info(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return get_user_info(user)


# ─── User Management (super_admin only) ─────────────────────────────


@app.get("/api/admin/users")
def list_users(user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """列出所有系统账户（超级管理员专用）"""
    users = db.query(User).all()
    return {"users": [get_user_info(u) for u in users]}


@app.post("/api/admin/users")
def create_user(data: dict, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """创建新账户（超级管理员专用）"""
    username = data.get("username", "").strip()
    password = data.get("password", "")
    display_name = data.get("display_name", username)
    role = data.get("role", "agent")

    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少3个字符")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")
    if role not in ("agent", "super_admin"):
        raise HTTPException(status_code=400, detail="角色无效")

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    new_user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"status": "ok", "message": "账户创建成功", "user": get_user_info(new_user)}


@app.put("/api/admin/users/{user_id}")
def update_user(
    user_id: int, data: dict,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """修改账户信息（超级管理员专用）"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    if "display_name" in data:
        target.display_name = data["display_name"]
    if "password" in data and data["password"]:
        target.password_hash = hash_password(data["password"])
    if "role" in data:
        if data["role"] not in ("agent", "super_admin"):
            raise HTTPException(status_code=400, detail="角色无效")
        target.role = data["role"]
    if "is_active" in data:
        target.is_active = data["is_active"]

    db.commit()
    db.refresh(target)
    return {"status": "ok", "message": "账户已更新", "user": get_user_info(target)}


@app.delete("/api/admin/users/{user_id}")
def delete_user(
    user_id: int,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """删除账户（超级管理员专用，不能删除自己）"""
    if user.id == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    db.delete(target)
    db.commit()
    return {"status": "ok", "message": f"账户 '{target.username}' 已删除"}


# ─── Seed Data ────────────────────────────────────────────────────────

def _seed_users(db):
    """独立种子用户，不依赖其他数据是否已存在"""
    from auth import hash_password
    if db.query(User).count() > 0:
        return
    users = [
        User(username="admin", password_hash=hash_password("admin123"), display_name="超级管理员", role="super_admin"),
        User(username="zhangsan", password_hash=hash_password("123456"), display_name="张三", role="agent"),
        User(username="lisi", password_hash=hash_password("123456"), display_name="李四", role="agent"),
        User(username="wangwu", password_hash=hash_password("123456"), display_name="王五", role="agent"),
        User(username="zhaoliu", password_hash=hash_password("123456"), display_name="赵六", role="agent"),
    ]
    db.add_all(users)
    db.commit()
    print("[Seed] 已创建 5 个系统账户")


def seed_data():
    db = SessionLocal()
    try:
        if db.query(Agent).count() > 0:
            _seed_users(db)
            return

        agents = [
            Agent(name="张三", email="zhangsan@gamecs.com", role="supervisor", avatar="🦸"),
            Agent(name="李四", email="lisi@gamecs.com", role="agent", avatar="🧑‍💻"),
            Agent(name="王五", email="wangwu@gamecs.com", role="agent", avatar="👩‍💼"),
            Agent(name="赵六", email="zhaoliu@gamecs.com", role="agent", avatar="🧙"),
        ]
        db.add_all(agents)
        db.flush()

        _seed_users(db)

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
    # 自动分单
    assigned_agent_id = auto_assign_ticket(db, ticket.id)
    db.refresh(ticket)

    # 飞书新工单通知
    player_name = player.nickname
    feishu_bot.notify_new_ticket(
        db, ticket.ticket_id, ticket.title,
        player_name, ticket.priority.value if ticket.priority else "medium",
    )

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


@app.post("/api/tickets/reassign")
def reassign_tickets(db: Session = Depends(get_db)):
    """手动触发重新分单所有未指派的工单"""
    unassigned = db.query(Ticket).filter(
        Ticket.assigned_to.is_(None),
        Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_PLAYER]),
    ).all()

    assigned_count = 0
    for t in unassigned:
        result = auto_assign_ticket(db, t.id)
        if result is not None:
            assigned_count += 1

    return {"status": "ok", "assigned_count": assigned_count, "remaining": len(unassigned) - assigned_count}


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


@app.post("/api/agents")
def create_agent(data: dict, db: Session = Depends(get_db)):
    """新增客服人员，自动创建系统登录账号"""
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    role = data.get("role", "agent")
    avatar = data.get("avatar", "👤")
    password = data.get("password", "").strip()

    if not name or not email:
        raise HTTPException(status_code=400, detail="姓名和邮箱不能为空")
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")

    existing = db.query(Agent).filter(Agent.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已被使用")

    # 如果上传了头像图片，保存URL路径
    if avatar and (avatar.startswith("/uploads/") or avatar.startswith("http")):
        avatar_url = avatar
    else:
        avatar_url = avatar  # emoji

    agent = Agent(name=name, email=email, role=role, avatar=avatar_url)
    db.add(agent)
    db.flush()  # 获取 agent.id

    # 同时创建用户登录账号
    existing_user = db.query(User).filter(User.username == email).first()
    if not existing_user:
        user = User(
            username=email,
            password_hash=hash_password(password),
            display_name=name,
            role="agent",
            is_active=True,
        )
        db.add(user)

    db.commit()
    db.refresh(agent)
    return {"status": "ok", "message": f"客服 '{name}' 已添加（登录账号：{email}）", "agent": {
        "id": agent.id, "name": agent.name, "email": agent.email,
        "role": agent.role, "avatar": agent.avatar, "is_active": agent.is_active,
        "open_tickets": 0, "resolved_tickets": 0,
    }}


@app.post("/api/upload/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """上传客服头像图片"""
    ext = os.path.splitext(file.filename or "avatar.png")[1] or ".png"
    if ext.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/GIF/WebP 格式")
    filename = f"avatar_{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(AVATAR_DIR, filename)
    content = await file.read()
    # Limit to 2MB
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 2MB")
    with open(filepath, "wb") as f:
        f.write(content)
    return {"url": f"/uploads/avatars/{filename}"}


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    """删除客服人员（需先解除关联工单）"""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="客服不存在")

    # 解除该客服的工单指派
    db.query(Ticket).filter(Ticket.assigned_to == agent_id).update(
        {"assigned_to": None}
    )
    db.delete(agent)
    db.commit()
    return {"status": "ok", "message": f"客服 '{agent.name}' 已删除"}


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
        # Build LLM config + KB context
        api_config = _build_llm_api_config_from_db(db)
        kb_context = ""
        if get_setting(db, "llm_use_kb", "true") == "true":
            search_text = ticket.title + " " + ticket.description
            kb_context = _search_kb_for_context(db, search_text)
        
        suggestion = suggest_reply(
            ticket_title=ticket.title,
            ticket_description=ticket.description,
            conversation_history=history,
            player_language=player_lang,
            agent_language="zh-CN",
            kb_context=kb_context,
            api_config=api_config,
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
    # Build LLM config + KB context
    api_config = _build_llm_api_config_from_db(db)
    kb_context = ""
    if get_setting(db, "llm_use_kb", "true") == "true":
        search_text = ticket.title + " " + ticket.description
        kb_context = _search_kb_for_context(db, search_text)
    suggestion = suggest_reply(
        ticket_title=ticket.title,
        ticket_description=ticket.description,
        conversation_history=history,
        player_language=player_lang,
        agent_language="zh-CN",
        kb_context=kb_context,
        api_config=api_config,
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

    # 飞书 AI 回复通知
    feishu_bot.notify_ai_reply(db, ticket.ticket_id, ticket.title, reply_zh)

    return {
        "ok": True,
        "reply_zh": reply_zh,
        "reply_translated": translated,
    }


# ─── Auto-Reply Config & Automated Reply ──────────────────────────


def get_setting(db: Session, key: str, default: str = "") -> str:
    """获取系统设置值"""
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return s.value if s else default


def set_setting(db: Session, key: str, value: str):
    """设置系统设置值"""
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if s:
        s.value = value
    else:
        s = SystemSetting(key=key, value=value)
        db.add(s)
    db.commit()


def _is_within_auto_reply_hours(db: Session) -> bool:
    """检查当前时间是否在自动回复时段内"""
    enabled = get_setting(db, "auto_reply_enabled", "false")
    if enabled != "true":
        return False

    now = datetime.datetime.utcnow().hour
    start = int(get_setting(db, "auto_reply_start_hour", "22"))
    end = int(get_setting(db, "auto_reply_end_hour", "8"))

    if start <= end:
        # Same-day range, e.g. 9:00-18:00
        return start <= now < end
    else:
        # Cross-midnight range, e.g. 22:00-08:00
        return now >= start or now < end


@app.get("/api/settings/auto-reply")
def get_auto_reply_config(db: Session = Depends(get_db)):
    """获取自动回复配置"""
    return {
        "enabled": get_setting(db, "auto_reply_enabled", "false"),
        "start_hour": int(get_setting(db, "auto_reply_start_hour", "22")),
        "end_hour": int(get_setting(db, "auto_reply_end_hour", "8")),
        "now_hour": datetime.datetime.utcnow().hour,
        "in_window": _is_within_auto_reply_hours(db),
    }


@app.post("/api/settings/auto-reply")
def set_auto_reply_config(data: dict, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """设置自动回复配置（超级管理员）"""
    set_setting(db, "auto_reply_enabled", str(data.get("enabled", False)).lower())
    set_setting(db, "auto_reply_start_hour", str(int(data.get("start_hour", 22))))
    set_setting(db, "auto_reply_end_hour", str(int(data.get("end_hour", 8))))
    return {
        "status": "ok",
        "message": "自动回复配置已保存",
        "in_window": _is_within_auto_reply_hours(db),
    }


# ─── LLM Provider Configuration ─────────────────────────────────


@app.get("/api/settings/llm")
def get_llm_config(db: Session = Depends(get_db)):
    """获取 LLM 配置"""
    return {
        "provider": get_setting(db, "llm_provider", "deepseek_api"),
        "base_url": get_setting(db, "llm_base_url", "https://api.deepseek.com/v1"),
        "model": get_setting(db, "llm_model", "deepseek-chat"),
        "use_kb": get_setting(db, "llm_use_kb", "true"),
    }


@app.post("/api/settings/llm")
def set_llm_config(data: dict, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """设置 LLM 配置（超级管理员）"""
    provider = data.get("provider", "deepseek_api")
    valid_providers = ["deepseek_api", "local_deepseek", "openai", "custom"]
    if provider not in valid_providers:
        raise HTTPException(400, f"不支持的服务商，可选: {', '.join(valid_providers)}")

    set_setting(db, "llm_provider", provider)
    set_setting(db, "llm_base_url", data.get("base_url", ""))
    set_setting(db, "llm_model", data.get("model", ""))

    # Only update API key if provided (don't overwrite with empty)
    api_key = data.get("api_key", "")
    if api_key:
        set_setting(db, "llm_api_key", api_key)

    # KB RAG setting
    set_setting(db, "llm_use_kb", str(data.get("use_kb", True)).lower())

    # Show masked key in response
    stored_key = get_setting(db, "llm_api_key", "")
    masked_key = stored_key[:4] + "****" + stored_key[-4:] if len(stored_key) > 8 else "****"

    return {
        "status": "ok",
        "message": "AI 模型配置已保存",
        "api_key_masked": masked_key,
    }


# ─── Auto-Assign Settings ──────────────────────────────────────────


@app.get("/api/settings/auto-assign")
def get_auto_assign_config(db: Session = Depends(get_db)):
    """获取自动分单配置"""
    return {
        "enabled": get_setting(db, AI_ASSIGN_ENABLED_SETTING, "true"),
        "max_open": MAX_OPEN_TICKETS,
    }


@app.post("/api/settings/auto-assign")
def set_auto_assign_config(data: dict, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """设置自动分单配置（超级管理员）"""
    set_setting(db, AI_ASSIGN_ENABLED_SETTING, str(data.get("enabled", True)).lower())
    return {"status": "ok", "message": "自动分单配置已保存"}


# ─── Feishu Bot Settings ────────────────────────────────────────────


@app.get("/api/settings/feishu")
def get_feishu_config(db: Session = Depends(get_db)):
    """获取飞书配置"""
    return {
        "webhook_url": get_setting(db, feishu_bot.FEISHU_WEBHOOK_URL_SETTING, ""),
        "notify_new_ticket": get_setting(db, feishu_bot.FEISHU_NOTIFY_NEW_TICKET_SETTING, "true"),
        "notify_ai_reply": get_setting(db, feishu_bot.FEISHU_NOTIFY_AI_REPLY_SETTING, "true"),
    }


@app.post("/api/settings/feishu")
def set_feishu_config(data: dict, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """设置飞书配置（超级管理员）"""
    if "webhook_url" in data:
        set_setting(db, feishu_bot.FEISHU_WEBHOOK_URL_SETTING, data["webhook_url"])
    if "notify_new_ticket" in data:
        set_setting(db, feishu_bot.FEISHU_NOTIFY_NEW_TICKET_SETTING, str(data["notify_new_ticket"]).lower())
    if "notify_ai_reply" in data:
        set_setting(db, feishu_bot.FEISHU_NOTIFY_AI_REPLY_SETTING, str(data["notify_ai_reply"]).lower())
    return {"status": "ok", "message": "飞书通知配置已保存"}


# ─── KB Utility for AI RAG ───────────────────────────────────────


def _build_llm_api_config_from_db(db: Session) -> dict:
    """从系统设置中读取 LLM 配置，返回 api_config 字典"""
    from translation_service import PROVIDER_DEEPSEEK_API
    return {
        "provider": get_setting(db, "llm_provider", PROVIDER_DEEPSEEK_API),
        "base_url": get_setting(db, "llm_base_url", ""),
        "model": get_setting(db, "llm_model", ""),
        "api_key": get_setting(db, "llm_api_key", ""),
    }


def _search_kb_for_context(db: Session, text: str, max_results: int = 3) -> str:
    """搜索知识库相关文章，返回格式化上下文"""
    query = db.query(KnowledgeArticle)
    # Simple keyword matching on title + content
    keywords = [w.strip() for w in text.replace(",", " ").replace("，", " ").split() if len(w.strip()) > 1]
    if not keywords:
        return ""
    from sqlalchemy import or_
    filters = []
    for kw in keywords[:10]:  # limit to 10 keywords
        filters.append(KnowledgeArticle.title.ilike(f"%{kw}%"))
        filters.append(KnowledgeArticle.content.ilike(f"%{kw}%"))
    articles = query.filter(or_(*filters)).order_by(desc(KnowledgeArticle.helpful_count)).limit(max_results).all()
    if not articles:
        return ""
    parts = ["## 相关知识库文章（请参考）"]
    for a in articles:
        content_preview = a.content[:300].replace("\n", " ")
        parts.append(f"- [{a.title}]({a.category}): {content_preview}...")
    return "\n".join(parts)


def _reply_to_ticket(ticket: Ticket, player_lang: str, db: Session) -> Optional[dict]:
    """生成 AI 回复并发送到工单（不依赖 WebSocket）"""
    history = []
    for m in ticket.messages[:10]:
        lang = m.original_language or player_lang
        history.append({"sender": m.sender_name, "content": m.content, "language": lang})

    suggestion = suggest_reply(
        ticket_title=ticket.title,
        ticket_description=ticket.description,
        conversation_history=history,
        player_language=player_lang,
        agent_language="zh-CN",
        kb_context=_search_kb_for_context(db, ticket.title + " " + ticket.description) if get_setting(db, "llm_use_kb", "true") == "true" else "",
        api_config=_build_llm_api_config_from_db(db),
    )
    reply_zh = suggestion.get("reply_zh", "")
    if not reply_zh:
        return None

    translated = None
    if player_lang != "zh-CN":
        translated = translate(reply_zh, "zh-CN", player_lang)

    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_type="agent",
        sender_name="AI自动回复",
        content=reply_zh,
        original_language="zh-CN",
        translated_content=translated,
        is_ai_suggested=True,
    )
    db.add(msg)
    ticket.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "reply_zh": reply_zh,
        "reply_translated": translated,
        "player_lang": player_lang,
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

    # 自动分单（外部API创建的工单）
    auto_assign_ticket(db, ticket.id)
    db.refresh(ticket)

    # 飞书新工单通知（外部API）
    feishu_bot.notify_new_ticket(
        db, ticket.ticket_id, title,
        player_name, priority.value if hasattr(priority, 'value') else str(priority),
    )

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
                            suggestion = _generate_suggestion_sync(ticket, player.language, db)
                            if suggestion and suggestion.get("reply_zh"):
                                # Broadcast AI suggestion to agents on this ticket
                                await manager.send_to_ticket(ticket_id, {
                                    "type": "ai_suggestion",
                                    "reply_zh": suggestion["reply_zh"],
                                    "reply_translated": suggestion.get("reply_translated", ""),
                                    "confidence": suggestion.get("confidence", 0),
                                    "suggested_action": suggestion.get("suggested_action", "send_message"),
                                })

                                # ─── Auto-reply during off-hours ───
                                if _is_within_auto_reply_hours(db):
                                    reply_zh = suggestion["reply_zh"]
                                    translated_auto = suggestion.get("reply_translated")

                                    # Save the auto-reply message
                                    auto_msg = TicketMessage(
                                        ticket_id=ticket.id,
                                        sender_type="agent",
                                        sender_name="AI自动回复",
                                        content=reply_zh,
                                        original_language="zh-CN",
                                        translated_content=translated_auto,
                                        is_ai_suggested=True,
                                    )
                                    db.add(auto_msg)
                                    ticket.updated_at = datetime.datetime.utcnow()
                                    db.commit()
                                    db.refresh(auto_msg)

                                    # Broadcast auto-reply to all
                                    await manager.send_to_ticket(ticket_id, {
                                        "type": "message",
                                        "id": auto_msg.id,
                                        "sender_type": "agent",
                                        "sender_name": "AI自动回复",
                                        "content": reply_zh,
                                        "translated_content": translated_auto,
                                        "is_ai_suggested": True,
                                        "timestamp": auto_msg.created_at.isoformat() if auto_msg.created_at else None,
                                        "auto_reply": True,
                                    })

                                    # Notify agents
                                    await manager.broadcast_to_agents({
                                        "type": "auto_reply_sent",
                                        "ticket_id": ticket_id,
                                        "title": ticket.title,
                                        "preview": reply_zh[:80],
                                        "timestamp": auto_msg.created_at.isoformat() if auto_msg.created_at else None,
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


# ─── Facebook Gaming News API ───────────────────────────────────────


@app.get("/api/facebook/config")
def get_facebook_config():
    """获取 Facebook API 配置状态。"""
    return {
        "configured": facebook_news.is_configured(),
        "proxy": facebook_news._config.proxy,
    }


@app.post("/api/facebook/config")
def set_facebook_config(data: dict):
    """配置 Facebook App 凭据和代理。
    {
        "app_id": "xxx",
        "app_secret": "xxx",
        "proxy": "http://127.0.0.1:7890"
    }
    """
    app_id = data.get("app_id", "")
    app_secret = data.get("app_secret", "")
    proxy = data.get("proxy")
    facebook_news.set_config(app_id=app_id, app_secret=app_secret, proxy=proxy)
    return {"status": "ok", "message": "Facebook 配置已更新"}


@app.get("/api/facebook/news")
def get_facebook_gaming_news():
    """获取游戏行业 Facebook 热点新闻。"""
    result = facebook_news.get_gaming_hot_news()
    return result


@app.get("/api/facebook/news/search")
def search_facebook_gaming_news(q: str = "gaming news", limit: int = 5):
    """搜索游戏相关 Facebook 主页。"""
    pages = facebook_news.search_gaming_pages(query=q, limit=limit)
    return {"pages": pages}


@app.post("/api/facebook/test")
def test_facebook_connection(data: dict):
    """测试 Facebook API 连接。"""
    proxy = data.get("proxy")
    result = facebook_news.test_connection(proxy=proxy)
    return result


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


app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8899)
