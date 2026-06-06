# Week 2: Redis + 多Worker WebSocket

> **执行方式:** 使用 delegate_task 子代理逐任务执行

**目标:** 引入 Redis 作为 WebSocket 消息总线，支持多进程/多 Worker 部署

---

## Task 1: 安装 Redis + Python 依赖

```bash
brew install redis
brew services start redis
pip3 install redis aioredis channels
```

**验证:** `redis-cli ping` → PONG

---

## Task 2: 创建 Redis 连接管理模块

**改动文件:**
- Create: `redis_manager.py` — Redis 连接池 + pub/sub 封装

**功能:**
- Redis 连接池（单例）
- Ticket 消息发布（publish）
- Ticket 消息订阅（subscribe / pubsub listener）
- 可选：连接失败时优雅降级到内存模式

---

## Task 3: 重构 WebSocket Manager — 支持 Redis 跨进程

**改动文件:**
- `main.py` — 重构 ConnectionManager

**核心逻辑:**
- 本地内存保留：当前进程连接的 ws 连接
- Redis pub/sub：跨进程广播消息
- 玩家发消息 → publish 到 Redis channel
- 所有 Worker 收到 → 查找自己是否持有该 ticket 的 ws → 推送

**关键设计:**
```
Player WS → Worker A (本地)
Worker A publish → Redis channel "ticket:{id}"
Worker A + Worker B + Worker C 都收到
只有持有该 ticket ws 的 Worker 才推送
```

---

## Task 4: 添加 Gunicorn 支持多 Worker

**改动文件:**
- `requirements.txt` — 添加 gunicorn
- 创建 `gunicorn.conf.py`

**配置:**
```python
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
bind = "127.0.0.1:8899"
```

---

## Task 5: 配置优雅重启

**目标:** 支持零宕机重启 Worker

**步骤:**
```bash
# 启动
gunicorn -c gunicorn.conf.py main:app

# 优雅重启
kill -HUP <master_pid>
```
