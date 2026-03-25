"""
TSNN Editorial Ingestion Pipeline
Orchestrates the full pipeline:
  1. Fetch articles from RSS feeds + optionally NewsData.io
  2. Deduplicate by URL
  3. Classify each article for TSNN relevance (0-100)
  4. Generate TSNN-style drafts for articles scoring >= draft_threshold (default 75)
  5. Persist everything to the database

Returns a stats dict for reporting in the UI.
"""

import logging
import os
from datetime import datetime
from typing import Dict, List

from scraper import fetch_articles
from classifier import classify_article
from tsnn_generator import generate_draft

logger = logging.getLogger(__name__)


def run_editorial_pipeline(config: Dict) -> Dict:
    """
    Execute the full TSNN editorial ingestion pipeline.

    Args:
        config: The application config dict (from config.json).

    Returns:
        Dict with pipeline stats:
          articles_fetched, duplicates_skipped, classified,
          queued_for_draft, drafts_generated, errors (list of str)
    """
    # Lazy import to avoid circular dependency at module load time
    from database import DraftManager

    stats: Dict = {
        "articles_fetched": 0,
        "duplicates_skipped": 0,
        "classified": 0,
        "queued_for_draft": 0,
        "drafts_generated": 0,
        "errors": [],
        "started_at": datetime.utcnow().isoformat(),
    }

    relevance_threshold: int = config.get("relevance_threshold", 60)
    draft_threshold: int = config.get("draft_threshold", 75)

    # ------------------------------------------------------------------
    # Step 1 — Fetch from RSS feeds
    # ------------------------------------------------------------------
    rss_sources: List[str] = config.get("sources", [])
    articles: List[Dict] = []

    if rss_sources:
        try:
            rss_articles = fetch_articles(rss_sources, max_per_feed=config.get("max_articles_per_feed", 5))
            articles.extend(rss_articles)
            logger.info(f"RSS: fetched {len(rss_articles)} articles from {len(rss_sources)} feeds")
        except Exception as e:
            msg = f"RSS fetch error: {e}"
            logger.error(msg)
            stats["errors"].append(msg)

    # ------------------------------------------------------------------
    # Step 2 — Optionally fetch from NewsData.io
    # ------------------------------------------------------------------
    newsdata_key = os.environ.get("NEWSDATA_API_KEY") or config.get("newsdata_api_key", "")
    if newsdata_key:
        try:
            from newsdata_fetcher import fetch_newsdata_articles
            nd_query = config.get("newsdata_query", "")
            nd_articles = fetch_newsdata_articles(api_key=newsdata_key, query=nd_query or None)
            articles.extend(nd_articles)
            logger.info(f"NewsData.io: fetched {len(nd_articles)} articles")
        except Exception as e:
            msg = f"NewsData.io fetch error: {e}"
            logger.error(msg)
            stats["errors"].append(msg)

    stats["articles_fetched"] = len(articles)

    if not articles:
        logger.warning("No articles fetched — pipeline complete with zero results")
        stats["completed_at"] = datetime.utcnow().isoformat()
        return stats

    # ------------------------------------------------------------------
    # Step 3 — Deduplicate and persist IngestedArticles
    # ------------------------------------------------------------------
    draft_manager = DraftManager()
    new_article_records: List = []  # list of (IngestedArticle, raw_dict)

    for raw in articles:
        url = raw.get("link") or raw.get("external_url", "")
        if not url:
            continue
        if draft_manager.is_duplicate_url(url):
            stats["duplicates_skipped"] += 1
            continue
        record = draft_manager.save_ingested_article(raw)
        if record:
            new_article_records.append((record, raw))

    logger.info(
        f"Dedup: {stats['duplicates_skipped']} skipped, "
        f"{len(new_article_records)} new articles saved"
    )

    # ------------------------------------------------------------------
    # Step 3b — Also pick up any previously ingested articles that are
    # still in 'pending' status (e.g. saved before API key was configured)
    # ------------------------------------------------------------------
    from models import IngestedArticle, get_session
    _session = get_session()
    try:
        already_saved_ids = {r.id for r, _ in new_article_records}
        pending_records = (
            _session.query(IngestedArticle)
            .filter(IngestedArticle.status == 'pending')
            .all()
        )
        for rec in pending_records:
            if rec.id not in already_saved_ids:
                article_dict = {
                    'title': rec.title,
                    'content': rec.content or rec.summary,
                    'summary': rec.summary,
                    'source_name': rec.source_name,
                    'published_at': rec.published_at,
                    'link': rec.external_url,
                    'external_url': rec.external_url,
                }
                new_article_records.append((rec, article_dict))
        if pending_records:
            logger.info(f"Picked up {len(pending_records)} previously unclassified pending articles")
    finally:
        _session.close()

    if not new_article_records:
        stats["completed_at"] = datetime.utcnow().isoformat()
        return stats

    # ------------------------------------------------------------------
    # Step 4 — Classify each new article
    # ------------------------------------------------------------------
    draft_candidates: List = []  # (IngestedArticle, raw_dict, score)

    for record, raw in new_article_records:
        try:
            classification = classify_article(raw)
            if classification:
                score = int(classification.get("relevance_score", 0))
                draft_manager.update_classification(record.id, classification)
                stats["classified"] += 1

                if score >= draft_threshold:
                    draft_candidates.append((record, raw, score))
                    logger.info(
                        f"Queued for draft (score={score}): {raw.get('title', '')[:60]}"
                    )
                elif score >= relevance_threshold:
                    logger.info(
                        f"Relevant but below draft threshold (score={score}): "
                        f"{raw.get('title', '')[:60]}"
                    )
                else:
                    draft_manager.archive_article(record.id)
            else:
                logger.warning(f"Classification returned None for: {raw.get('title', '')[:60]}")
        except Exception as e:
            msg = f"Classification error for '{raw.get('title', '')[:50]}': {e}"
            logger.error(msg)
            stats["errors"].append(msg)

    stats["queued_for_draft"] = len(draft_candidates)

    # ------------------------------------------------------------------
    # Step 5 — Generate TSNN-style drafts
    # ------------------------------------------------------------------
    for record, raw, score in draft_candidates:
        try:
            draft_data = generate_draft(raw)
            if draft_data:
                draft_manager.save_draft(record.id, draft_data, relevance_score=score)
                stats["drafts_generated"] += 1
            else:
                logger.warning(f"Draft generation returned None for: {raw.get('title', '')[:60]}")
        except Exception as e:
            msg = f"Draft generation error for '{raw.get('title', '')[:50]}': {e}"
            logger.error(msg)
            stats["errors"].append(msg)

    stats["completed_at"] = datetime.utcnow().isoformat()
    logger.info(
        f"Pipeline complete — fetched: {stats['articles_fetched']}, "
        f"classified: {stats['classified']}, "
        f"drafts: {stats['drafts_generated']}"
    )
    return stats
