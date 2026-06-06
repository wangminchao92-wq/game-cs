"""Facebook Gaming News Fetcher
使用 Facebook Graph API 搜索游戏行业热门新闻和帖子。

注意：在国内网络环境下需要配置代理才能访问 graph.facebook.com。
"""

import json
import time
import hashlib
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Optional

logger = logging.getLogger(__name__)

# ── 缓存 ───────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 300  # 5 分钟


# ── 配置 ────────────────────────────────────────────────────────────

class FacebookConfig:
    """从 App ID + App Secret 获取长期 App Access Token。
    可以在 main.py 启动时设置：
        facebook_news.set_config(app_id='xxx', app_secret='xxx', proxy='http://127.0.0.1:7890')
    """
    app_id: str = ""
    app_secret: str = ""
    proxy: Optional[str] = None       # 例如 "http://127.0.0.1:7890"
    api_version: str = "v22.0"
    timeout: int = 15                  # 请求超时（秒）

_config = FacebookConfig()


def set_config(app_id: str = "", app_secret: str = "", proxy: Optional[str] = None):
    """在应用启动时调用，配置 Facebook API 凭据和代理。"""
    _config.app_id = app_id
    _config.app_secret = app_secret
    if proxy is not None:
        _config.proxy = proxy


def is_configured() -> bool:
    """检查是否已配置 Facebook App 凭据。"""
    return bool(_config.app_id and _config.app_secret)


# ── 低层 HTTP ──────────────────────────────────────────────────────

def _build_opener():
    """创建 urllib opener，支持代理。"""
    if _config.proxy:
        from urllib.request import ProxyHandler, build_opener
        handler = ProxyHandler({"http": _config.proxy, "https": _config.proxy})
        return build_opener(handler)
    return None


def _request(url: str) -> dict:
    """发送 GET 请求并返回 JSON 字典。"""
    req = Request(url, headers={"User-Agent": "GameCS/1.0"})
    opener = _build_opener()
    try:
        if opener:
            resp = opener.open(req, timeout=_config.timeout)
        else:
            resp = urlopen(req, timeout=_config.timeout)
        data = resp.read().decode("utf-8")
        return json.loads(data)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"Facebook API HTTP {e.code}: {body}")
        return {"error": {"message": f"HTTP {e.code}: {body}", "code": e.code}}
    except URLError as e:
        logger.error(f"Facebook API 网络错误: {e.reason}")
        return {"error": {"message": f"网络错误: {e.reason}", "code": 0}}
    except Exception as e:
        logger.error(f"Facebook API 请求异常: {e}")
        return {"error": {"message": str(e), "code": -1}}


def _get_access_token() -> Optional[str]:
    """获取 App Access Token（长期有效，不需要用户登录）。"""
    if not is_configured():
        return None
    url = (
        f"https://graph.facebook.com/{_config.api_version}/oauth/access_token"
        f"?client_id={_config.app_id}"
        f"&client_secret={_config.app_secret}"
        f"&grant_type=client_credentials"
    )
    result = _request(url)
    if "access_token" in result:
        return result["access_token"]
    logger.error(f"获取 Access Token 失败: {result.get('error', result)}")
    return None


# ── 核心 API ───────────────────────────────────────────────────────

def _cache_key(name: str, **params) -> str:
    raw = json.dumps(params, sort_keys=True)
    return f"{name}:{hashlib.md5(raw.encode()).hexdigest()}"


def _get_cached(key: str) -> Optional[list[dict]]:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _cache[key]
    return None


def _set_cache(key: str, data: list[dict]):
    _cache[key] = (time.time(), data)


# ── 搜游戏相关主页 ──────────────────────────────────────────────

GAMING_KEYWORDS = [
    "gaming news",
    "game",
    "esports",
    "PlayStation",
    "Xbox",
    "Nintendo",
    "PC gaming",
    "video game",
    "电竞",
]

# 已知知名游戏媒体 Facebook 主页 ID（作为保底数据源）
KNOWN_GAMING_PAGES = {
    "IGN": "18297014338",
    "GameSpot": "19741555751",
    "Kotaku": "10605336780",
    "Polygon": "132335062194570",
    "Eurogamer": "110982674431",
    "GameInformer": "14686773332",
    "PCGamer": "114089997761904",
    "Destructoid": "41782759088",
    "GamesRadar": "112852788127",
}


def search_gaming_pages(query: str = "gaming news", limit: int = 10) -> list[dict]:
    """搜索游戏相关的 Facebook 主页。"""
    token = _get_access_token()
    if not token:
        # 没有 Token 时返回已知页面列表
        return [{"id": pid, "name": name, "source": "known"} for name, pid in KNOWN_GAMING_PAGES.items()]

    ck = _cache_key("search_pages", query=query, limit=limit)
    cached = _get_cached(ck)
    if cached is not None:
        return cached

    url = (
        f"https://graph.facebook.com/{_config.api_version}/pages/search"
        f"?q={query.replace(' ', '+')}"
        f"&limit={limit}"
        f"&fields=name,description,link,picture"
        f"&access_token={token}"
    )
    result = _request(url)
    pages = result.get("data", [])
    _set_cache(ck, pages)
    return pages


def get_page_posts(page_id: str, limit: int = 10) -> list[dict]:
    """获取指定主页的最新帖子。"""
    token = _get_access_token()
    if not token:
        return []

    ck = _cache_key("page_posts", page_id=page_id, limit=limit)
    cached = _get_cached(ck)
    if cached is not None:
        return cached

    url = (
        f"https://graph.facebook.com/{_config.api_version}/{page_id}/posts"
        f"?limit={limit}"
        f"&fields=message,story,created_time,permalink_url,full_picture,likes.summary(true),shares,comments.summary(true)"
        f"&access_token={token}"
    )
    result = _request(url)
    posts = result.get("data", [])
    _set_cache(ck, posts)
    return posts


# ── 获取游戏热点新闻（整合） ───────────────────────────────────

def get_gaming_hot_news(
    keywords: Optional[list[str]] = None,
    posts_per_page: int = 5,
    max_pages: int = 5,
) -> dict:
    """获取游戏行业热门新闻。

    返回结构：
    {
        "status": "ok" | "error",
        "message": str,
        "pages": [...],          # 搜索到的主页
        "news": [...],           # 聚合的新闻帖子
        "source": "facebook" | "known",
        "total_news": int,
        "cached": bool,
    }
    """
    if not is_configured():
        # 没有 App 凭据，返回已知页面的示例数据
        return _get_offline_result()

    if keywords is None:
        keywords = GAMING_KEYWORDS[:3]

    token = _get_access_token()
    if not token:
        return {
            "status": "error",
            "message": "无法获取 Facebook Access Token，请检查 App ID 和 App Secret",
            "pages": [],
            "news": [],
            "source": "none",
            "total_news": 0,
            "cached": False,
        }

    # 搜索游戏相关主页
    all_pages = {}
    for kw in keywords[:3]:
        pages = search_gaming_pages(kw, limit=5)
        for p in pages:
            if "id" in p:
                all_pages[p["id"]] = p

    # 限制主页数量
    page_list = list(all_pages.values())[:max_pages]

    # 获取每个主页的最新帖子
    all_news = []
    for page in page_list:
        posts = get_page_posts(page["id"], limit=posts_per_page)
        for post in posts:
            all_news.append({
                "page_name": page.get("name", "Unknown"),
                "page_id": page.get("id", ""),
                "page_link": page.get("link", ""),
                "post_id": post.get("id", ""),
                "message": post.get("message", post.get("story", "")),
                "story": post.get("story", ""),
                "created_time": post.get("created_time", ""),
                "url": post.get("permalink_url", ""),
                "image": post.get("full_picture", ""),
                "likes": post.get("likes", {}).get("summary", {}).get("total_count", 0),
                "shares": post.get("shares", {}).get("count", 0),
                "comments": post.get("comments", {}).get("summary", {}).get("total_count", 0),
            })

    # 按时间排序（最新的在前）
    all_news.sort(key=lambda x: x.get("created_time", ""), reverse=True)

    return {
        "status": "ok",
        "message": f"成功获取 {len(all_news)} 条游戏热点新闻",
        "pages": page_list,
        "news": all_news,
        "source": "facebook",
        "total_news": len(all_news),
        "cached": False,
    }


# ── 离线/无 Token 时的回退数据 ──────────────────────────────────

def _get_offline_result() -> dict:
    """当没有配置 API Key 时，返回已知游戏媒体的公开信息。"""
    news = []
    for name, pid in KNOWN_GAMING_PAGES.items():
        news.append({
            "page_name": name,
            "page_id": pid,
            "post_id": "",
            "message": f"{name} — 全球知名游戏媒体，最新游戏资讯、评测和视频。",
            "story": "游戏媒体",
            "created_time": "",
            "url": f"https://www.facebook.com/{pid}",
            "image": "",
            "likes": 0,
            "shares": 0,
            "comments": 0,
            "is_placeholder": True,
        })

    return {
        "status": "ok",
        "message": "未配置 Facebook App 凭据，显示游戏媒体列表。请在后台设置 App ID 和 App Secret 以获取实时数据。",
        "pages": [{"id": pid, "name": name, "source": "known"} for name, pid in KNOWN_GAMING_PAGES.items()],
        "news": news,
        "source": "known",
        "total_news": len(news),
        "cached": False,
        "needs_config": True,
    }


# ── 通过代理测试连接 ────────────────────────────────────────────

def test_connection(proxy: Optional[str] = None) -> dict:
    """测试 Facebook API 的可达性。"""
    if proxy:
        old_proxy = _config.proxy
        _config.proxy = proxy

    try:
        token = _get_access_token()
        if token:
            return {"status": "ok", "message": f"连接成功，已获取 Access Token", "token_prefix": token[:10] + "..."}
        else:
            # 即使没 Token，能连通 API 也算成功
            test_url = f"https://graph.facebook.com/{_config.api_version}/"
            result = _request(test_url)
            if "error" in result and result["error"].get("code") != 0:
                return {"status": "ok", "message": "Facebook API 可达（未配置凭据）"}
            return {"status": "error", "message": f"无法连接: {result}"}
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {e}"}
    finally:
        if proxy:
            _config.proxy = old_proxy
