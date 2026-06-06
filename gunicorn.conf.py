"""Gunicorn configuration for Game CS
支持多 Worker 并发，需配合 Redis 使用 WebSocket。

启动方式：
    gunicorn -c gunicorn.conf.py main:app

优雅重启：
    kill -HUP <master_pid>
"""
import os

# 绑定地址
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8899")

# Worker 数量（建议 = CPU 核心数 * 2 + 1）
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))

# 使用 Uvicorn Worker（支持 ASGI）
worker_class = "uvicorn.workers.UvicornWorker"

# 超时设置
timeout = 120
keepalive = 5

# 日志
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# 优雅重启
graceful_timeout = 30
max_requests = 10000
max_requests_jitter = 1000

# 预加载应用（加速启动）
preload_app = True
