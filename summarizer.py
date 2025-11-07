"""
AI-powered article summarization and subject line generation using OpenAI GPT-4o
Includes rate limiting and caching to control costs
"""

import os
import logging
import json
import hashlib
from typing import Dict, List, Optional
from openai import OpenAI
from cachetools import TTLCache
import time

logger = logging.getLogger(__name__)

# Configuration constants
MIN_CONTENT_LENGTH_FOR_SUMMARY = 200
MAX_TOKENS_SUMMARY = 300
MAX_TOKENS_SUBJECT_LINE = 100
OPENAI_MODEL = "gpt-4o"
OPENAI_TEMPERATURE_SUMMARY = 0.7
OPENAI_TEMPERATURE_SUBJECT = 0.8  # Slightly higher for more creative subject lines

# Rate limiting and caching
MAX_API_CALLS_PER_RUN = int(os.environ.get('MAX_OPENAI_CALLS_PER_RUN', '100'))
SUMMARY_CACHE_TTL = 86400  # 24 hours
summary_cache = TTLCache(maxsize=1000, ttl=SUMMARY_CACHE_TTL)
api_call_count = 0
api_call_start_time = None

# Global OpenAI client - will be initialized when API key is provided
openai_client = None

def get_api_key():
    """Get API key from environment variable only (SECURITY: not from config file)"""
    # Only use environment variable for security reasons
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return api_key

    # SECURITY: Do not load API key from config.json to prevent accidental commits
    # If API key was previously stored in config.json, it will be ignored
    logger.warning("No OPENAI_API_KEY found in environment. "
                  "Set OPENAI_API_KEY environment variable to configure API access.")
    return None

def initialize_openai_client(api_key=None):
    """Initialize the OpenAI client with the provided or configured API key"""
    global openai_client
    
    if api_key is None:
        api_key = get_api_key()
    
    if not api_key:
        logger.warning("No OpenAI API key found in environment or config")
        return False
    
    try:
        openai_client = OpenAI(api_key=api_key)
        logger.info("OpenAI client initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return False

def test_api_connection(api_key=None):
    """Test the OpenAI API connection"""
    try:
        if api_key:
            test_client = OpenAI(api_key=api_key)
        else:
            if not openai_client:
                initialize_openai_client()
            test_client = openai_client
        
        if not test_client:
            return False, "No API client available"
        
        # Test with a simple completion
        response = test_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=1
        )
        
        return True, f"gpt-4o-mini"
    except Exception as e:
        logger.error(f"API connection test failed: {e}")
        return False, str(e)

# Try to initialize on import
if not initialize_openai_client():
    logger.warning("OpenAI client not initialized - API key required for summarization features")

def reset_api_call_counter():
    """Reset the API call counter for a new run"""
    global api_call_count, api_call_start_time
    api_call_count = 0
    api_call_start_time = time.time()
    logger.info("API call counter reset")

def check_rate_limit() -> bool:
    """Check if we're within the rate limit"""
    global api_call_count
    if api_call_count >= MAX_API_CALLS_PER_RUN:
        logger.warning(f"API call limit reached: {api_call_count}/{MAX_API_CALLS_PER_RUN}")
        return False
    return True

def increment_api_calls():
    """Increment API call counter and log stats"""
    global api_call_count, api_call_start_time
    api_call_count += 1
    if api_call_start_time:
        elapsed = time.time() - api_call_start_time
        rate = api_call_count / elapsed if elapsed > 0 else 0
        logger.debug(f"API calls: {api_call_count}/{MAX_API_CALLS_PER_RUN} ({rate:.2f}/sec)")

def get_content_hash(content: str) -> str:
    """Generate hash of content for caching"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def get_cached_summary(content_hash: str) -> Optional[str]:
    """Get cached summary if available"""
    if content_hash in summary_cache:
        logger.debug(f"Cache hit for summary {content_hash[:8]}...")
        return summary_cache[content_hash]
    return None

def cache_summary(content_hash: str, summary: str):
    """Cache summary for future use"""
    summary_cache[content_hash] = summary
    logger.debug(f"Cached summary {content_hash[:8]}...")

def summarize_article(article: Dict) -> Optional[Dict[str, str]]:
    """
    Summarize an article for newsletter inclusion using GPT-4o
    Includes caching and rate limiting

    Args:
        article: Dictionary containing article data (title, summary, full_content, etc.)

    Returns:
        Formatted summary string or None if failed
    """
    global openai_client

    # Check if client is initialized
    if not openai_client:
        if not initialize_openai_client():
            logger.error("Cannot summarize article: OpenAI client not initialized")
            return None

    # Check rate limit
    if not check_rate_limit():
        logger.error(f"API rate limit exceeded ({MAX_API_CALLS_PER_RUN} calls)")
        return None

    try:
        # Prepare content for summarization
        content_to_summarize = article.get('summary', '')

        # Use full content if available and summary is short
        if article.get('full_content') and len(content_to_summarize) < MIN_CONTENT_LENGTH_FOR_SUMMARY:
            content_to_summarize = article['full_content']

        if not content_to_summarize.strip():
            logger.warning(f"No content to summarize for article: {article.get('title', 'Unknown')}")
            return None

        # Check cache first
        content_hash = get_content_hash(content_to_summarize)
        cached = get_cached_summary(content_hash)
        if cached:
            logger.info(f"Using cached summary for: {article.get('title', 'Unknown')[:50]}...")
            return cached

        # SECURITY: Truncate content for LLM to prevent prompt injection
        from security import truncate_for_llm
        content_to_summarize = truncate_for_llm(content_to_summarize, max_length=4000)
        
        # Craft prompt for meeting planner audience
        prompt = f"""
You are writing for a newsletter targeted at meeting planners and event professionals. 

Please summarize this article in a format suitable for a professional newsletter:

**Article Title:** {article.get('title', 'Unknown')}
**Source:** {article.get('source', 'Unknown')}

**Content:**
{content_to_summarize}

**Instructions:**
1. Write a summary in NO MORE THAN 3 SHORT SENTENCES (max 60 words total)
2. AVOID repeating the title or quoting full sentences from the article
3. Focus on NEW information not already in the title
4. Emphasize what's relevant to meeting planners and event professionals
5. Include ONE key takeaway marked with 🔑 (max 15 words)

**Format your response EXACTLY like this:**
[2-3 short sentences summarizing the key points - max 60 words total]
🔑 **Key Takeaway:** [One actionable insight - max 15 words]
"""

        # Call GPT-4o for summarization
        # Using OpenAI GPT-4o model (released May 13, 2024)
        logger.info(f"Calling OpenAI API to summarize: {article.get('title', 'Unknown')[:50]}...")
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert content curator for meeting and event industry professionals. You specialize in creating engaging, informative newsletter content."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=OPENAI_TEMPERATURE_SUMMARY,
            max_tokens=MAX_TOKENS_SUMMARY
        )

        # Increment API call counter
        increment_api_calls()

        summary_text = response.choices[0].message.content.strip()

        if summary_text:
            logger.info(f"Successfully summarized: {article.get('title', 'Unknown')}")

            # Parse the summary to extract takeaway
            lines = summary_text.split('\n')
            summary = ""
            takeaway = ""

            for line in lines:
                if '🔑' in line or 'Key Takeaway:' in line:
                    # Extract takeaway
                    takeaway = line.replace('🔑', '').replace('**Key Takeaway:**', '').strip()
                    takeaway = takeaway.replace('**', '').strip()
                else:
                    summary += line + " "

            # Create result
            result = {
                'summary': summary.strip(),
                'takeaway': takeaway
            }

            # Cache the result
            cache_summary(content_hash, result)

            return result
        else:
            logger.warning(f"Empty summary returned for: {article.get('title', 'Unknown')}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to summarize article '{article.get('title', 'Unknown')}': {e}")
        return None

def generate_subject_line(summaries: List[Dict], newsletter_title: str) -> str:
    """
    Generate compelling subject line for the newsletter using GPT-4o
    
    Args:
        summaries: List of article summaries
        newsletter_title: Newsletter brand name
    
    Returns:
        Generated subject line
    """
    global openai_client
    
    # Check if client is initialized
    if not openai_client:
        if not initialize_openai_client():
            logger.error("Cannot generate subject line: OpenAI client not initialized")
            # Return a fallback subject line
            from datetime import datetime
            return f"{newsletter_title} - {datetime.now().strftime('%B %d, %Y')}"
    
    try:
        # Extract key topics from summaries
        topics = []
        for summary in summaries[:5]:  # Use first 5 summaries for subject line
            if isinstance(summary, dict):
                topics.append(summary.get('title', ''))
                if 'summary' in summary:
                    topics.append(summary['summary'])
            else:
                topics.append(str(summary))
        
        topics_text = "\n".join(topics)
        
        prompt = f"""
Based on these newsletter stories for meeting planners and event professionals, create a compelling email subject line.

**Newsletter Content Topics:**
{topics_text}

**Requirements:**
1. Maximum 90 characters (aim for 60-80)
2. Include the TOP 2-3 stories in a concise format
3. Use pipe (|) or bullet (•) to separate topics
4. Appeal to meeting planners and event professionals
5. Be specific with numbers, locations, or trends when possible
6. Create urgency without clickbait

**Examples of good subject lines:**
- "Vegas Venue Tax Rises 12% | Hybrid Events Boom | Orlando Expansion"
- "Incentives Are Back • Hotel Rates Jump • $600M in New Venues"
- "AI Tools for Planners | Boston Hotels at 90% | Green Meetings Trend"

Generate ONE subject line that summarizes the top 2-3 stories. Return only the subject line, no explanation.
"""

        # Generate subject line with GPT-4o
        # Using OpenAI GPT-4o model (released May 13, 2024)
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert email marketing specialist for the meetings and events industry."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=OPENAI_TEMPERATURE_SUBJECT,
            max_tokens=MAX_TOKENS_SUBJECT_LINE
        )
        
        subject_line = response.choices[0].message.content.strip()
        
        # Clean up the subject line
        subject_line = subject_line.replace('"', '').replace("'", "").strip()
        
        logger.info(f"Generated subject line: {subject_line}")
        return subject_line
        
    except Exception as e:
        logger.error(f"Failed to generate subject line: {e}")
        # Fallback subject line
        from datetime import datetime
        return f"{newsletter_title} - {datetime.now().strftime('%B %d, %Y')}"

def analyze_content_themes(summaries: List[Dict]) -> Dict:
    """
    Analyze content themes for insights (optional feature)
    
    Args:
        summaries: List of article summaries
    
    Returns:
        Dictionary with theme analysis
    """
    try:
        content_text = "\n\n".join([
            summary.get('summary', '') if isinstance(summary, dict) else str(summary) 
            for summary in summaries
        ])
        
        prompt = f"""
Analyze these meeting industry newsletter stories and identify the main themes:

{content_text}

Return a JSON object with:
1. "primary_themes": List of 3-5 main topics covered
2. "industry_sentiment": "positive", "neutral", or "negative" 
3. "trending_topics": List of 2-3 trending subjects
4. "geographic_focus": List of mentioned locations/regions

Format as valid JSON only.
"""

        # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        analysis = json.loads(response.choices[0].message.content)
        logger.info("Content theme analysis completed")
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to analyze content themes: {e}")
        return {
            "primary_themes": [],
            "industry_sentiment": "neutral",
            "trending_topics": [],
            "geographic_focus": []
        }

if __name__ == "__main__":
    # Test the summarizer
    logging.basicConfig(level=logging.INFO)
    
    test_article = {
        'title': 'Major Hotel Chain Announces New Meeting Spaces',
        'summary': 'Marriott International announced plans to add 500 new meeting rooms across their portfolio by 2025, responding to increased demand for hybrid event capabilities.',
        'source': 'Meetings Today'
    }
    
    summary = summarize_article(test_article)
    if summary:
        print("Generated Summary:")
        print(summary)
        
        subject = generate_subject_line([{'summary': summary}], "Planner Pulse")
        print(f"\nGenerated Subject Line: {subject}")
