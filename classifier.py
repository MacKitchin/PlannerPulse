"""
TSNN Relevance Classifier
Scores ingested articles 0-100 for relevance to the trade show / exhibition industry.
Uses the exact classification prompt defined in the TSNN AI Editorial Assistant PRD.
"""

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt — direct from PRD Section H
# ---------------------------------------------------------------------------
CLASSIFIER_SYSTEM_PROMPT = """You are a news relevance classifier for TSNN (Trade Show News Network), the #1 online news source for the trade show and exhibition industry. Your job is to evaluate whether a given article is relevant to TSNN's editorial coverage area.

TSNN covers:

PRIMARY TOPICS (high relevance):
- Trade shows, exhibitions, expos, conventions (announcements, attendance, results, launches, cancellations)
- Exhibition industry business (revenue, growth, market data, forecasts)
- Major show organizers (Informa, RX, Emerald, Clarion, Messe Frankfurt, Messe Muenchen, Koelnmesse)
- Venue and convention center developments (new builds, renovations, expansions, financing)
- Industry organizations (IAEE, UFI, SISO, CEIR, PCMA, MPI, EXHIBITOR)
- Industry research and data (CEIR Index, UFI Global Barometer)

SECONDARY TOPICS (moderate relevance):
- Event technology (registration, lead retrieval, event apps, AI in events)
- Experiential marketing and brand activations
- Personnel changes at major exhibition companies
- M&A activity in the events sector
- Service providers (Freeman, GES, general contractors, AV companies)
- Hotel/hospitality developments affecting convention markets
- Government policies affecting trade shows (travel, tariffs, regulations)

LOW RELEVANCE (score below 40):
- General corporate news that merely mentions a trade show tangentially
- Restaurant/retail openings near convention centers
- Consumer events or festivals (unless they have B2B exhibition components)
- Sports events without a trade show connection
- General technology news without events industry application
- Tourism marketing without convention/meetings focus

Score each article 0-100 based on how relevant it is to TSNN's audience of show organizers, exhibitors, venue operators, and event suppliers. Return a JSON object with your analysis."""


def classify_article(article: Dict, openai_client=None) -> Optional[Dict]:
    """
    Classify an article's relevance to TSNN's editorial mission.

    Args:
        article: Dict with keys: title, summary/content, source/source_name, published/published_at
        openai_client: Optional pre-initialised OpenAI client; falls back to summarizer module client.

    Returns:
        Dict with: relevance_score (0-100), primary_topic, secondary_topics, justification,
                   key_entities, confidence, is_breaking, suggested_angle
        Returns None on failure.
    """
    if openai_client is None:
        try:
            from summarizer import openai_client as _client
            openai_client = _client
        except ImportError:
            pass

    if openai_client is None:
        logger.error("No OpenAI client available for classification")
        return None

    try:
        content_preview = (
            article.get("content") or article.get("full_content") or article.get("summary") or ""
        )[:500]

        source = article.get("source_name") or article.get("source", "Unknown")
        pub_date = article.get("published_at") or article.get("published", "")

        user_message = (
            f"Evaluate the following article for TSNN relevance:\n\n"
            f"TITLE: {article.get('title', '')}\n"
            f"SOURCE: {source} ({pub_date})\n"
            f"CONTENT: {content_preview}\n\n"
            f"Return your analysis as JSON."
        )

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )

        result = json.loads(response.choices[0].message.content)
        score = result.get("relevance_score", 0)
        logger.info(
            f"Classified '{article.get('title', '')[:60]}' → score: {score} "
            f"({result.get('primary_topic', 'Unknown')})"
        )
        return result

    except Exception as e:
        logger.error(f"Classification failed for '{article.get('title', '')[:60]}': {e}")
        return None


def score_label(score: int) -> str:
    """Return a human-readable label for a relevance score."""
    if score >= 90:
        return "Highly Relevant"
    elif score >= 75:
        return "Clearly Relevant"
    elif score >= 60:
        return "Moderately Relevant"
    elif score >= 40:
        return "Borderline"
    else:
        return "Not Relevant"


def score_color_class(score: int) -> str:
    """Return a Bootstrap colour class for a relevance score badge."""
    if score >= 75:
        return "success"
    elif score >= 60:
        return "warning"
    elif score >= 40:
        return "secondary"
    else:
        return "danger"
