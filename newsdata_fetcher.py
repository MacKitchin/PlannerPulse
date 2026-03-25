"""
NewsData.io API integration for TSNN editorial assistant.
Fetches trade show / exhibitions industry news and normalises to the same
article dict format used by the RSS scraper.

Requires NEWSDATA_API_KEY environment variable or api_key parameter.
Free tier: 200 credits/day. Paid plans from $69/month.
Sign up at https://newsdata.io
"""

import os
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

NEWSDATA_API_URL = "https://newsdata.io/api/1/latest"

# Default query targeting trade show / exhibition industry
DEFAULT_QUERY = (
    '"trade show" OR "exhibition" OR "expo" OR "convention center" OR '
    '"tradeshow" OR "IAEE" OR "UFI" OR "CEIR" OR "trade fair"'
)


def fetch_newsdata_articles(
    api_key: Optional[str] = None,
    query: str = DEFAULT_QUERY,
    max_results: int = 10,
) -> List[Dict]:
    """
    Fetch articles from NewsData.io matching the given query.

    Args:
        api_key:     NewsData.io API key. Falls back to NEWSDATA_API_KEY env var.
        query:       Boolean search query string.
        max_results: Maximum number of articles to return (API max per page = 10).

    Returns:
        List of article dicts normalised to the same schema as the RSS scraper.
    """
    resolved_key = api_key or os.environ.get("NEWSDATA_API_KEY", "")
    if not resolved_key:
        logger.warning(
            "NewsData.io API key not found. "
            "Set NEWSDATA_API_KEY environment variable to enable this source."
        )
        return []

    try:
        params = {
            "apikey": resolved_key,
            "q": query,
            "language": "en",
            "size": min(max_results, 10),  # API caps at 10 per page
        }

        response = requests.get(NEWSDATA_API_URL, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "success":
            logger.error(
                f"NewsData.io API error: {data.get('message', 'Unknown error')}"
            )
            return []

        articles = []
        for item in data.get("results", []):
            # Normalise to the same shape used by RSS scraper and ingestion pipeline
            article = {
                "title": item.get("title") or "",
                "link": item.get("link") or "",
                "external_url": item.get("link") or "",
                "summary": item.get("description") or "",
                "content": item.get("content") or item.get("description") or "",
                "author": ", ".join(item.get("creator") or []),
                "source_name": item.get("source_id") or item.get("source_url") or "",
                "source": item.get("source_id") or "",
                "published_at": item.get("pubDate") or "",
                "published": item.get("pubDate") or "",
            }
            if article["title"] and article["link"]:
                articles.append(article)

        logger.info(f"Fetched {len(articles)} articles from NewsData.io")
        return articles

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            logger.error("NewsData.io: Invalid API key (401 Unauthorized)")
        elif e.response is not None and e.response.status_code == 429:
            logger.warning("NewsData.io: Rate limit exceeded (429). Try again later.")
        else:
            logger.error(f"NewsData.io HTTP error: {e}")
        return []
    except Exception as e:
        logger.error(f"NewsData.io fetch failed: {e}")
        return []
