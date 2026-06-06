"""飞书机器人通知模块"""
import os
import json
import requests
import logging
from typing import Optional

logger = logging.getLogger("gamecs.feishu")

FEISHU_WEBHOOK_URL_SETTING = "feishu_webhook_url"
FEISHU_NOTIFY_NEW_TICKET_SETTING = "feishu_notify_new_ticket"
FEISHU_NOTIFY_AI_REPLY_SETTING = "feishu_notify_ai_reply"


def send_feishu_message(webhook_url: str, title: str, content: str, color: str = "blue") -> bool:
    """发送飞书消息卡片到群"""
    if not webhook_url:
        return False
    try:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": color,
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                    {"tag": "hr"},
                    {"tag": "note", "elements": [{"tag": "plain_text", "content": f"Game CS · {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"}]},
                ],
            },
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.ok
    except Exception as e:
        logger.error(f"飞书消息发送失败: {e}")
        return False


def notify_new_ticket(db, ticket_id: str, title: str, player_name: str, priority: str) -> bool:
    """发送新工单通知"""
    from main import get_setting
    webhook = get_setting(db, FEISHU_WEBHOOK_URL_SETTING, "")
    enabled = get_setting(db, FEISHU_NOTIFY_NEW_TICKET_SETTING, "true")
    if not webhook or enabled != "true":
        return False
    priority_emoji = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    emoji = priority_emoji.get(priority, "🟡")
    content = f"**工单编号：** {ticket_id}\n**标题：** {title}\n**玩家：** {player_name}\n**优先级：** {emoji} {priority}"
    return send_feishu_message(webhook, f"🎫 新工单通知", content, "red" if priority in ("urgent", "high") else "blue")


def notify_ai_reply(db, ticket_id: str, title: str, reply_preview: str) -> bool:
    """发送 AI 自动回复通知"""
    from main import get_setting
    webhook = get_setting(db, FEISHU_WEBHOOK_URL_SETTING, "")
    enabled = get_setting(db, FEISHU_NOTIFY_AI_REPLY_SETTING, "true")
    if not webhook or enabled != "true":
        return False
    content = f"**工单编号：** {ticket_id}\n**标题：** {title}\n**AI 回复：** {reply_preview[:200]}"
    return send_feishu_message(webhook, f"🤖 AI 自动回复", content, "blue")
