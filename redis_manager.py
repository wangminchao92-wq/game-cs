"""Redis Connection Manager for Game CS
支持多 Worker 跨进程 WebSocket 消息广播。
如果没有 REDIS_URL 环境变量，自动降级到内存模式。
"""
import os
import json
import logging
from typing import Optional

logger = logging.getLogger("gamecs.redis")

REDIS_URL = os.environ.get("REDIS_URL", "")

_pool = None
_client = None


def get_redis():
    """获取 Redis 客户端（单例），返回 None 表示降级模式"""
    global _client
    if _client is not None:
        return _client
    if not REDIS_URL:
        _client = None
        return None
    try:
        import redis.asyncio as aioredis
        _client = aioredis.from_url(REDIS_URL, decode_responses=True)
        logger.info(f"Redis connected: {REDIS_URL}")
        return _client
    except Exception as e:
        logger.warning(f"Redis unavailable, falling back to in-memory: {e}")
        _client = None
        return None


def publish_ticket_message(ticket_id: str, message: dict):
    """发布消息到 Redis 频道，所有 Worker 都会收到"""
    client = get_redis()
    if client is None:
        return  # 降级模式，不做任何事
    try:
        channel = f"ticket:{ticket_id}"
        client.publish(channel, json.dumps(message, ensure_ascii=False))
    except Exception as e:
        logger.error(f"Redis publish error: {e}")


async def subscribe_ticket(ticket_id: str):
    """订阅工单频道，返回异步生成器"""
    client = get_redis()
    if client is None:
        return None
    try:
        pubsub = client.pubsub()
        channel = f"ticket:{ticket_id}"
        await pubsub.subscribe(channel)
        return pubsub
    except Exception as e:
        logger.error(f"Redis subscribe error: {e}")
        return None


def is_redis_available() -> bool:
    """检查 Redis 是否可用"""
    return get_redis() is not None
