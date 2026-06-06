# Week 3: Docker Compose 一键部署

> **执行方式:** 使用 delegate_task 子代理逐任务执行

**目标:** 使用 Docker Compose 将整个系统打包，一行命令即可在任何服务器上部署

---

## Task 1: 编写后端 Dockerfile

**改动文件:**
- Create: `Dockerfile`

**内容:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8899

CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
```

---

## Task 2: 编写 Nginx Dockerfile

**改动文件:**
- Create: `nginx/Dockerfile`
- Create: `nginx/nginx.conf.template`（含环境变量占位符）

**内容:**
- 基于 nginx:alpine
- 复制 nginx 配置
- 使用 envsubst 注入 DOMAIN 环境变量

---

## Task 3: 编写 docker-compose.yml

**改动文件:**
- Create: `docker-compose.yml`

**服务:**
```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes: postgres_data:/var/lib/postgresql/data
    environment: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

  redis:
    image: redis:7-alpine

  backend:
    build: .
    depends_on: [postgres, redis]
    environment: DATABASE_URL, REDIS_URL, JWT_SECRET, etc.

  nginx:
    build: ./nginx
    ports: ["80:80", "443:443"]
    depends_on: [backend]
    volumes:
      - ./uploads:/app/uploads
      - certbot_data:/etc/letsencrypt

volumes:
  postgres_data:
  certbot_data:
```

---

## Task 4: Let's Encrypt 自动证书脚本

**改动文件:**
- Create: `scripts/init-ssl.sh`
- Create: `scripts/renew-ssl.sh`（cron job）

---

## Task 5: 创建 .env.production 模板 + 部署脚本

**改动文件:**
- Create: `.env.production.example`
- Create: `scripts/deploy.sh`

**deploy.sh 功能:**
1. 拉取最新代码
2. docker compose build
3. docker compose up -d
4. 健康检查
5. 旧版本回滚
