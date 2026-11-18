# tools/web_search.py
"""Web araması (Tavily)."""
import os
from tools import register_tool, get_config

_client = None


def _get_api_key():
    # Öncelik sırası:
    # 1) config.json -> tools.tavily.api_key
    # 2) .env -> TAVILY_API_KEY veya TVLY_API
    cfg = get_config()
    key = (
        cfg.get("tools", {}).get("tavily", {}).get("api_key", "")
        or os.environ.get("TAVILY_API_KEY")
        or os.environ.get("TVLY_API")
        or ""
    )
    return key.strip()


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "Tavily API anahtarı yok. config.json -> tools.tavily.api_key "
            "veya .env -> TVLY_API"
        )
    from tavily import TavilyClient
    _client = TavilyClient(api_key=api_key)
    return _client


@register_tool(
    name="web_search",
    description=(
        "Güncel haber, son gelişmeler ve genel bilgi için internette arama yapar. "
        "Hava durumu için get_weather aracını kullan."
    ),
    parameters={"query": "string - arama sorgusu (en fazla 5 kelime)"},
)
def web_search(query, max_results=3):
    try:
        r = _get_client().search(
            query=query, search_depth="basic",
            max_results=max_results, include_answer=True,
        )
        parts = []
        if r.get("answer"):
            parts.append(f"Özet: {r['answer']}")
        for i, item in enumerate(r.get("results", []), 1):
            parts.append(f"{i}. {item['title']}\nURL: {item['url']}\n{item['content'][:400]}")
        return "\n\n".join(parts) if parts else "Sonuç bulunamadı."
    except Exception as e:
        return f"Arama hatası: {e}"