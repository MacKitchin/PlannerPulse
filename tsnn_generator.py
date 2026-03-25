"""
TSNN Draft Article Generator
Generates publication-ready first drafts in TSNN's editorial voice using structured JSON output.
Uses the exact draft generation prompt from the TSNN AI Editorial Assistant PRD Section H.
"""

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt — direct from PRD Section H, Prompt 3
# ---------------------------------------------------------------------------
DRAFT_SYSTEM_PROMPT = """You are a senior editorial writer for TSNN (Trade Show News Network), the #1 online news source for the trade show and exhibition industry. You write for an audience of show organizers, exhibitors, venue operators, convention and visitors bureau executives, and event industry suppliers.

YOUR EDITORIAL VOICE:
- Professional and authoritative, but not stiff. You are an industry insider who speaks with confidence and expertise.
- Data-driven: Lead with numbers, percentages, and concrete facts. TSNN readers expect specificity, not generalities.
- Forward-looking: Frame developments in terms of what they mean for the industry's future. What are the implications?
- Business-focused: Everything connects back to business impact — revenue, growth, competitive positioning, operational efficiency.
- Industry-specific vocabulary: Use terms like "rented space," "net square footage," "operating profits," "yield management," "exhibitor retention," "hosted buyer," "general contractor" — your readers know this language.

ARTICLE STRUCTURE:
1. HEADLINE: Descriptive and data-forward. Include specific numbers when available. Never use clickbait.
   Examples of real TSNN headlines:
   - "TSNN Analysis: 8 Top Trends For The U.S. Exhibition Industry in 2026"
   - "Informa Reports Record Earnings in 2025; Projects Growth in 2026"
   - "UFI Asia-Pacific Conference Draws 260+ Industry Leaders to Bangkok"

2. LEDE (first paragraph): Lead with the single most newsworthy fact. Who did what, with what result? Specific, concrete, immediate.

3. BODY: Build out the story with supporting details, context, and additional data points. Use these structural cues where appropriate:
   - "Zooming out:" — to provide broader industry context
   - "What they're saying:" — to introduce direct quotes
   - "By the numbers:" — to present key statistics
   - "Bottom line:" — to summarize implications
   - "Context:" — to explain background for readers

4. WHY THIS MATTERS TO EVENT PROFESSIONALS: A dedicated 2-3 paragraph section explaining business implications for show organizers, exhibitors, venues, and suppliers. Be specific about who is affected and how.

5. KEY TAKEAWAYS: 3-5 bullet points, each a standalone insight.

ABSOLUTE RULES:
- You may ONLY include facts, data, quotes, and claims that appear in the provided source articles. Do not add ANY information from your training data.
- NEVER copy more than one consecutive sentence from any source article. Synthesize information into your own original prose.
- Include inline citations in [Source: Publication Name, Date] format after every factual claim.
- If sources are insufficient for a complete article, note the gaps explicitly rather than filling them with invented information.
- Do NOT use generic filler phrases like "in today's fast-paced world," "it remains to be seen," "only time will tell," or "industry stakeholders are watching closely." Be specific or say nothing.
- Avoid passive voice. Prefer active, direct constructions.
- Target 400-800 words total (excluding Why This Matters and Key Takeaways).

FORMAT: Return a JSON object with all article components."""


def generate_draft(article: Dict, openai_client=None) -> Optional[Dict]:
    """
    Generate a TSNN-style article draft from a single source article.

    Args:
        article: Dict with title, content/summary, source, link, published_at fields.
        openai_client: Optional pre-initialised OpenAI client.

    Returns:
        Dict with: headline, alt_headlines, lede, body, why_it_matters, key_takeaways,
                   sources_cited, word_count, confidence_score, primary_topic, tags.
        Returns None on failure.
    """
    if openai_client is None:
        try:
            from summarizer import openai_client as _client
            openai_client = _client
        except ImportError:
            pass

    if openai_client is None:
        logger.error("No OpenAI client available for draft generation")
        return None

    try:
        content = (
            article.get("content")
            or article.get("full_content")
            or article.get("summary")
            or ""
        )[:3000]

        source = article.get("source_name") or article.get("source", "Unknown")
        pub_date = article.get("published_at") or article.get("published", "")
        url = article.get("link") or article.get("external_url", "")

        user_message = f"""Write a TSNN article based on the following source material:

STORY THEME: {article.get('title', '')}

SOURCE ARTICLES:
---
SOURCE 1: {source} ({pub_date})
TITLE: {article.get('title', '')}
URL: {url}
CONTENT: {content}
---

Generate a complete TSNN article as JSON with exactly these fields:
- headline (string): primary headline in TSNN data-forward style
- alt_headlines (array of 2 strings): two alternative headline angles
- lede (string): news-style opening paragraph with most newsworthy fact first
- body (string): full article body 400-800 words, with structural cues (Zooming out:, By the numbers:, etc.)
- why_it_matters (string): 2-3 paragraphs on business implications for event professionals
- key_takeaways (array of 3-5 strings): standalone bullet-point insights
- sources_cited (array of objects): each with "publication", "date", "url" keys
- word_count (integer): total word count of headline + lede + body
- confidence_score (integer 1-10): LLM self-assessed confidence in accuracy
- primary_topic (string): one of the TSNN topic categories
- tags (array of strings): 3-6 relevant tags"""

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=4000,
        )

        draft_data = json.loads(response.choices[0].message.content)
        headline = draft_data.get("headline", "")[:60]
        logger.info(f"Generated draft: '{headline}...' (confidence: {draft_data.get('confidence_score')})")
        return draft_data

    except Exception as e:
        logger.error(f"Draft generation failed for '{article.get('title', '')[:60]}': {e}")
        return None


def regenerate_draft(article: Dict, instructions: str, openai_client=None) -> Optional[Dict]:
    """
    Regenerate a draft incorporating the editor's specific instructions.

    Args:
        article: Original source article dict.
        instructions: Free-text editor instructions (e.g. "Focus more on venue angle").
        openai_client: Optional pre-initialised OpenAI client.

    Returns:
        Same structure as generate_draft, or None on failure.
    """
    if openai_client is None:
        try:
            from summarizer import openai_client as _client
            openai_client = _client
        except ImportError:
            pass

    if openai_client is None:
        logger.error("No OpenAI client available for regeneration")
        return None

    try:
        content = (
            article.get("content")
            or article.get("full_content")
            or article.get("summary")
            or ""
        )[:3000]

        source = article.get("source_name") or article.get("source", "Unknown")
        pub_date = article.get("published_at") or article.get("published", "")
        url = article.get("link") or article.get("external_url", "")

        user_message = f"""Rewrite this TSNN article incorporating the editor's instructions.

EDITOR INSTRUCTIONS: {instructions}

SOURCE MATERIAL:
---
SOURCE: {source} ({pub_date})
TITLE: {article.get('title', '')}
URL: {url}
CONTENT: {content}
---

Generate a revised TSNN article as JSON using the same schema as before (headline, alt_headlines, lede, body, why_it_matters, key_takeaways, sources_cited, word_count, confidence_score, primary_topic, tags)."""

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.5,
            max_tokens=4000,
        )

        draft_data = json.loads(response.choices[0].message.content)
        logger.info(f"Regenerated draft for '{article.get('title', '')[:60]}'")
        return draft_data

    except Exception as e:
        logger.error(f"Draft regeneration failed: {e}")
        return None


def draft_to_html(draft: Dict) -> str:
    """Convert a draft dict to clean semantic HTML for CMS export."""
    parts = []
    headline = draft.get("edited_headline") or draft.get("headline", "")
    body = draft.get("edited_body") or draft.get("body", "")

    parts.append(f"<h1>{headline}</h1>")

    if draft.get("lede"):
        parts.append(f"<p><strong>{draft['lede']}</strong></p>")

    if body:
        for para in body.split("\n\n"):
            para = para.strip()
            if para:
                parts.append(f"<p>{para}</p>")

    if draft.get("why_it_matters"):
        parts.append("<h2>Why This Matters to Event Professionals</h2>")
        for para in draft["why_it_matters"].split("\n\n"):
            para = para.strip()
            if para:
                parts.append(f"<p>{para}</p>")

    if draft.get("key_takeaways"):
        parts.append("<h2>Key Takeaways</h2><ul>")
        for takeaway in draft["key_takeaways"]:
            parts.append(f"<li>{takeaway}</li>")
        parts.append("</ul>")

    if draft.get("sources_cited"):
        parts.append("<h3>Sources</h3><ul>")
        for src in draft["sources_cited"]:
            pub = src.get("publication", "")
            date = src.get("date", "")
            url = src.get("url", "#")
            parts.append(f'<li><a href="{url}" target="_blank">{pub} ({date})</a></li>')
        parts.append("</ul>")

    return "\n".join(parts)


def draft_to_markdown(draft: Dict) -> str:
    """Convert a draft dict to Markdown for export."""
    lines = []
    headline = draft.get("edited_headline") or draft.get("headline", "")
    body = draft.get("edited_body") or draft.get("body", "")

    lines.append(f"# {headline}\n")

    if draft.get("lede"):
        lines.append(f"**{draft['lede']}**\n")

    if body:
        lines.append(body + "\n")

    if draft.get("why_it_matters"):
        lines.append("## Why This Matters to Event Professionals\n")
        lines.append(draft["why_it_matters"] + "\n")

    if draft.get("key_takeaways"):
        lines.append("## Key Takeaways\n")
        for takeaway in draft["key_takeaways"]:
            lines.append(f"- {takeaway}")
        lines.append("")

    if draft.get("sources_cited"):
        lines.append("## Sources\n")
        for src in draft["sources_cited"]:
            pub = src.get("publication", "")
            date = src.get("date", "")
            url = src.get("url", "#")
            lines.append(f"- [{pub} ({date})]({url})")

    return "\n".join(lines)
