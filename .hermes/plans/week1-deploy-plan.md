# Week 1: PostgreSQL 迁移 + Nginx 部署 + HTTPS

> **执行方式:** 使用 delegate_task 子代理逐任务执行

**目标:** 将 game-cs 从 SQLite 迁移到 PostgreSQL，配置 Nginx 反向代理 + HTTPS

---

## Task 1: 安装 PostgreSQL 和依赖

**目标:** 在本地安装 PostgreSQL 和相关 Python 包

**步骤:**
```bash
# 安装 PostgreSQL
brew install postgresql@16

# 启动 PostgreSQL
brew services start postgresql@16

# 创建数据库和用户
createuser -s gamecs
createdb gamecs -O gamecs

# 安装 Python 依赖
pip3 install asyncpg psycopg2-binary sqlalchemy[asyncio] aiosqlite
```

**验证:** `psql -U gamecs -d gamecs -c "\l"` 显示 gamecs 数据库

---

## Task 2: 修改 database.py — 支持 PostgreSQL/SQLite 双模式

**目标:** 使数据库配置可通过环境变量切换，开发环境用 SQLite，生产用 PostgreSQL

**改动文件:**
- `database.py` — 添加 Postgres 连接支持，DATABASE_URL 环境变量

**核心逻辑:**
- 环境变量 `DATABASE_URL` 为空时使用 SQLite（当前行为）
- 设置了 `DATABASE_URL` 时使用 PostgreSQL
- 自动创建表（兼容两种引擎）

---

## Task 3: 修改 main.py — 适配 PostgreSQL

**目标:** 确保所有 SQL 查询在 PostgreSQL 下兼容

**常见不兼容问题:**
- SQLite `extract('year', col)` → PostgreSQL `EXTRACT(YEAR FROM col)` — SQLAlchemy 会自动处理
- SQLite 的 `ilike` → PostgreSQL 的 `ILIKE` — SQLAlchemy 自动处理
- SQLite 的自动递增行为 → PostgreSQL 的 SERIAL — 需检查模型定义

**验证:** 启动服务后能正常创建表、插入种子数据、执行查询

---

## Task 4: 创建 .env 配置模板

**目标:** 将所有敏感配置移入 .env 文件

**改动文件:**
- 创建 `.env.example` 模板
- 创建 `.env` （gitignored）

**配置项:**
```
DATABASE_URL=postgresql://gamecs@localhost:5432/gamecs
JWT_SECRET=your-secret-key-here
LLM_API_KEY=
LLM_PROVIDER=deepseek_api
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

---

## Task 5: 修改 auth.py — 从环境变量读取 JWT_SECRET

**目标:** JWT_SECRET 优先从 `.env` 读取，而非写死在代码里

**改动文件:**
- `auth.py` — 添加 `python-dotenv` 加载，优先读取环境变量

---

## Task 6: 安装配置 Nginx

**目标:** Nginx 反向代理 + HTTPS

**步骤:**
```bash
# 安装 Nginx
brew install nginx

# 配置 Nginx 反向代理
# 参考下面 nginx.conf 配置
```

**Nginx 配置要点:**
- 反向代理到 `127.0.0.1:8899`
- 代理 /static/ 和 /uploads/ 静态文件直接由 Nginx 托管
- 代理 WebSocket 连接（/ws）
- 配置 SSL 证书（Let's Encrypt 生产环境，本地用自签名）
