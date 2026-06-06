"""Game CS - AI Translation & Suggestion Service
Multi-language: Chinese <-> Portuguese, English, Spanish, Japanese, etc.
Uses MyMemory API (free, no key needed, works in China) for translation.
Uses DeepSeek API for AI reply suggestions (template fallback if unavailable).
"""

import os
import json
import hashlib
import threading
import re
from typing import Optional
from datetime import datetime, timedelta
from urllib.parse import quote

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# ─── Language Mapping ───────────────────────────────────────────────

LANGUAGE_MAP = {
    "zh-CN": "简体中文",
    "pt-BR": "葡萄牙语（巴西）",
    "pt-PT": "葡萄牙语（葡萄牙）",
    "en": "英语",
    "es": "西班牙语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "ru": "俄语",
    "th": "泰语",
    "vi": "越南语",
    "id": "印尼语",
    "ar": "阿拉伯语",
}

LANGUAGE_FLAGS = {
    "zh-CN": "🇨🇳",
    "pt-BR": "🇧🇷",
    "pt-PT": "🇵🇹",
    "en": "🇺🇸",
    "es": "🇪🇸",
    "ja": "🇯🇵",
    "ko": "🇰🇷",
    "fr": "🇫🇷",
    "de": "🇩🇪",
    "ru": "🇷🇺",
    "th": "🇹🇭",
    "vi": "🇻🇳",
    "id": "🇮🇩",
    "ar": "🇸🇦",
}

# MyMemory uses codes like zh-CN, pt-BR, en-GB
_MY_MEMORY_LANG = {
    "zh-CN": "zh-CN",
    "pt-BR": "pt-BR",
    "pt-PT": "pt-PT",
    "en": "en-US",
    "es": "es-ES",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "fr": "fr-FR",
    "de": "de-DE",
    "ru": "ru-RU",
    "th": "th-TH",
    "vi": "vi-VN",
    "id": "id-ID",
    "ar": "ar-SA",
}

# ─── Translation Cache ──────────────────────────────────────────────

class TranslationCache:
    def __init__(self, max_size=500, ttl_seconds=3600):
        self._cache = {}
        self._max_size = max_size
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = threading.Lock()

    def _make_key(self, text: str, source: str, target: str) -> str:
        raw = f"{text}|{source}|{target}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, text: str, source: str, target: str) -> Optional[str]:
        key = self._make_key(text, source, target)
        with self._lock:
            entry = self._cache.get(key)
            if entry and datetime.utcnow() - entry["time"] < self._ttl:
                return entry["result"]
        return None

    def set(self, text: str, source: str, target: str, result: str):
        key = self._make_key(text, source, target)
        with self._lock:
            if len(self._cache) >= self._max_size:
                oldest = min(self._cache.keys(), key=lambda k: self._cache[k]["time"])
                del self._cache[oldest]
            self._cache[key] = {"result": result, "time": datetime.utcnow()}


_cache = TranslationCache()
_MYMEMORY_URL = "https://api.mymemory.translated.net/get"


# ─── Translation Functions ──────────────────────────────────────────

def get_language_name(code: str) -> str:
    return LANGUAGE_MAP.get(code, code)


def get_language_flag(code: str) -> str:
    return LANGUAGE_FLAGS.get(code, "🌐")


def translate(text: str, source_lang: str = "auto", target_lang: str = "zh-CN") -> str:
    """Translate text using MyMemory API (free, no key needed).

    Args:
        text: Text to translate.
        source_lang: Source language code. "auto" for auto-detect.
        target_lang: Target language code.

    Returns:
        Translated text.
    """
    if not text or not text.strip():
        return text

    # Check cache
    cached = _cache.get(text, source_lang, target_lang)
    if cached is not None:
        return cached

    if not _HAS_REQUESTS:
        return f"[翻译服务未安装] {text}"

    # Map language codes
    if source_lang == "auto":
        detected = detect_language(text)
        source = _MY_MEMORY_LANG.get(detected, "en")
    else:
        source = _MY_MEMORY_LANG.get(source_lang, source_lang)

    target = _MY_MEMORY_LANG.get(target_lang, target_lang)

    # MyMemory uses | separator: source|target
    langpair = f"{source}|{target}"

    try:
        resp = requests.get(
            _MYMEMORY_URL,
            params={"q": text, "langpair": langpair, "de": "gamecs@gamecs.com"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("responseData", {}).get("translatedText", "")

        if not result:
            return f"[翻译失败] {text}"

        # Clean up HTML entities
        result = result.replace("&#39;", "'").replace("&quot;", '"')

        # Cache result
        _cache.set(text, source_lang, target_lang, result)
        return result

    except requests.exceptions.Timeout:
        return f"[翻译超时] {text}"
    except Exception as e:
        print(f"[Translation Error] {e}")
        return f"[翻译失败] {text}"


def detect_language(text: str) -> str:
    """Detect language - uses simple heuristics for common languages."""
    if not text or not text.strip():
        return "zh-CN"

    # Count character types
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    japanese_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    korean_chars = len(re.findall(r'[\uac00-\ud7af]', text))
    arabic_chars = len(re.findall(r'[\u0600-\u06ff]', text))
    thai_chars = len(re.findall(r'[\u0e00-\u0e7f]', text))
    cyrillic_chars = len(re.findall(r'[а-яА-Я]', text))

    total = len(text.strip())

    if chinese_chars > total * 0.3:
        return "zh-CN"
    if japanese_chars > total * 0.3:
        return "ja"
    if korean_chars > total * 0.2:
        return "ko"
    if arabic_chars > total * 0.3:
        return "ar"
    if thai_chars > total * 0.3:
        return "th"
    if cyrillic_chars > total * 0.3:
        return "ru"

    # Latin-based: check for common Portuguese/Spanish patterns
    if latin_chars > 0:
        lower = text.lower()
        # Portuguese indicators
        if any(w in lower for w in ["ão", "çã", "não", "você", "obrigado", "por favor", "olá", "tudo bem", "sim", "como"]):
            return "pt-BR"
        # Spanish indicators
        if any(w in lower for w in ["hola", "gracias", "por favor", "cómo", "está", "muchas", "señor"]):
            return "es"
        # Default to English for other Latin text
        return "en"

    return "zh-CN"


# ─── AI Reply Suggestion ──────────────────────────────────────────

def _get_deepseek_api_key() -> str:
    """Try to find DeepSeek API key."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY=") and "***" not in line:
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        return val
    except (FileNotFoundError, IOError):
        pass
    return ""


def suggest_reply(
    ticket_title: str,
    ticket_description: str,
    conversation_history: list,
    player_language: str = "pt-BR",
    agent_language: str = "zh-CN",
) -> dict:
    """Generate AI-suggested reply (DeepSeek API with template fallback)."""
    api_key = _get_deepseek_api_key()

    if api_key and _HAS_REQUESTS:
        try:
            return _suggest_via_deepseek(
                ticket_title, ticket_description, conversation_history,
                player_language, agent_language, api_key,
            )
        except Exception as e:
            print(f"[AI Suggestion API Error] {e}")

    return _suggest_fallback(
        ticket_title, ticket_description, conversation_history,
        player_language, agent_language,
    )


def _suggest_via_deepseek(title, desc, history, player_lang, agent_lang, api_key):
    """Generate suggestion using DeepSeek API."""
    player_lang_name = get_language_name(player_lang)

    context_parts = [f"## 工单标题\n{title}", f"## 工单描述\n{desc}"]
    if history:
        context_parts.append("## 对话记录")
        for msg in history[-10:]:
            flag = get_language_flag(msg.get("language", "zh-CN"))
            context_parts.append(f"- {msg['sender']} ({flag}): {msg['content']}")
    context = "\n\n".join(context_parts)

    system_prompt = (
        "你是一个专业的游戏客服AI助手。请根据工单信息用中文写一段客服回复。\n"
        f"玩家的语言是：{player_lang_name}\n"
        "回复要专业、友好、有同理心。\n\n"
        '请仅输出JSON格式：\n'
        '{"reply_zh": "中文回复","suggested_action": "send_message","confidence": 0.9}'
    )

    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ],
            "temperature": 0.3,
            "max_tokens": 1500,
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = json.loads(resp.json()["choices"][0]["message"]["content"])

    reply_zh = result.get("reply_zh", "")
    reply_translated = ""
    if reply_zh and player_lang != agent_lang:
        reply_translated = translate(reply_zh, "zh-CN", player_lang)

    return {
        "reply_zh": reply_zh,
        "reply_translated": reply_translated,
        "suggested_action": result.get("suggested_action", "send_message"),
        "confidence": result.get("confidence", 0.8),
    }


def _suggest_fallback(title, desc, history, player_lang, agent_lang):
    """Fallback: template-based suggestions."""
    text = (title + " " + desc[:300]).lower()

    if any(w in text for w in ["pagamento", "payment", "充值", "moeda", "coin", "item", "recebi", "comprou"]):
        reply_zh = "您好，非常抱歉给您带来不便。我们已收到您的充值问题反馈，正在为您核查充值记录。请提供您的订单号或充值截图，我们会尽快为您处理。感谢您的耐心等待！"
    elif any(w in text for w in ["bug", "erro", "problema", "故障", "穿透", "无法"]):
        reply_zh = "您好，感谢您反馈游戏问题。我们已经记录了您描述的BUG情况，会提交给技术团队核查修复。请您提供更多信息（如设备型号、截图等）以帮助我们更快定位问题。感谢您的支持！"
    elif any(w in text for w in ["conta", "account", "hack", "roubo", "盗", "安全", "senha"]):
        reply_zh = "您好，关于账号安全问题，我们非常重视。请提供您的注册邮箱/手机号，我们将进行身份验证后为您处理。在此期间建议您先修改密码并开启二次验证。"
    elif any(w in text for w in ["report", "举报", "denúncia", "matou", "pk"]):
        reply_zh = "您好，我们已经收到您的举报，会安排专员核查相关情况。处理进度会通过工单更新，请耐心等待。感谢您为维护游戏环境做出的贡献！"
    else:
        reply_zh = "您好，感谢您的反馈！我们已收到您的问题，正在安排客服专员为您处理。请您保持关注工单动态，我们会尽快回复您。感谢您的理解与支持！"

    reply_translated = ""
    if player_lang != agent_lang:
        reply_translated = translate(reply_zh, "zh-CN", player_lang)

    return {
        "reply_zh": reply_zh,
        "reply_translated": reply_translated,
        "suggested_action": "send_message",
        "confidence": 0.6,
    }
