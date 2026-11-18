# tools/web_search.py
"""Web araması (Tavily)."""
import os
from dotenv import load_dotenv
from tools import register_tool, get_config

load_dotenv()   # modül bağımsız çalışsın diye burada da çağırıyoruz

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    # Her iki isim de kabul edilir + config.json fallback
    api_key = (
        os.environ.get("TAVILY_API_KEY")
        or os.environ.get("TVLY_API")
        or get_config().get("tavily", {}).get("api_key", "")
    )
    if not api_key:
        raise RuntimeError("TVLY_API / TAVILY_API_KEY tanımlı değil (.env veya config.json)")
    from tavily import TavilyClient
    _client = TavilyClient(api_key=api_key)
    return _client


@register_tool(
    name="web_search",
    description="Güncel bilgi, haber, hava durumu, son gelişmeler için internette arama yapar.",
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