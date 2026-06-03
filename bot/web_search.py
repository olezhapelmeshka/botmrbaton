"""
Веб-поиск через DuckDuckGo HTML — без API-ключа.

Если поиск падает — возвращаем понятное сообщение, не пробрасываем
исключение наружу, чтобы агент мог это обработать как обычный
результат tool.
"""

from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup

from bot.config import WEB_SEARCH_RESULTS_LIMIT, WEB_SEARCH_TIMEOUT
from bot.logger import get_logger


logger = get_logger("web_search")

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
}


def search(query: str, limit: int | None = None) -> dict[str, Any]:
    """Возвращает {'query', 'results': [{title, url, snippet}, ...]}."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "results": [], "error": "Пустой запрос"}

    n = limit or WEB_SEARCH_RESULTS_LIMIT
    n = max(1, min(n, 10))

    try:
        resp = requests.post(
            _DDG_URL,
            data={"q": query},
            headers=_HEADERS,
            timeout=WEB_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Веб-поиск не удался: %s", e)
        return {"query": query, "results": [], "error": f"Сеть недоступна: {e.__class__.__name__}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, str]] = []
    for block in soup.select(".result")[: n * 2]:
        title_el = block.select_one(".result__title")
        snippet_el = block.select_one(".result__snippet")
        link_el = block.select_one(".result__url")
        if not (title_el and snippet_el):
            continue
        results.append(
            {
                "title": title_el.get_text(" ", strip=True),
                "snippet": snippet_el.get_text(" ", strip=True),
                "url": (link_el.get_text(strip=True) if link_el else "").strip(),
            }
        )
        if len(results) >= n:
            break

    logger.info("web_search '%s' → %d результатов", query, len(results))
    return {"query": query, "results": results}
