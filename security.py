"""
Security utilities for PlannerPulse
Handles HTML sanitization, URL validation, and input cleaning
"""

import bleach
import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import re

logger = logging.getLogger(__name__)

# HTML sanitization configuration
# Only allow safe tags and attributes to prevent XSS
ALLOWED_HTML_TAGS = [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u', 'a', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'code', 'pre'
]

ALLOWED_HTML_ATTRIBUTES = {
    'a': ['href', 'title'],
    'img': [],  # No images allowed in sanitized content
}

# URL validation patterns
ALLOWED_URL_SCHEMES = ['http', 'https']
DISALLOWED_HOSTS = [
    'localhost', '127.0.0.1', '0.0.0.0',
    '10.', '172.16.', '192.168.',  # Private IP ranges
    'file://', 'data:', 'javascript:',  # Dangerous schemes
]

# Content length limits to prevent DoS
MAX_TEXT_LENGTH = 100000  # 100KB
MAX_HTML_LENGTH = 200000  # 200KB
MAX_URL_LENGTH = 2000


def sanitize_html(html_content: str, max_length: int = MAX_HTML_LENGTH) -> str:
    """
    Sanitize HTML content to prevent XSS attacks

    Args:
        html_content: Raw HTML content from untrusted source
        max_length: Maximum allowed length

    Returns:
        Sanitized HTML with only safe tags and attributes
    """
    if not html_content:
        return ""

    # Enforce length limit to prevent DoS
    if len(html_content) > max_length:
        logger.warning(f"HTML content truncated from {len(html_content)} to {max_length} chars")
        html_content = html_content[:max_length]

    try:
        # Use bleach to sanitize HTML
        cleaned = bleach.clean(
            html_content,
            tags=ALLOWED_HTML_TAGS,
            attributes=ALLOWED_HTML_ATTRIBUTES,
            strip=True,  # Strip disallowed tags instead of escaping
            strip_comments=True  # Remove HTML comments
        )

        # Additional cleaning: remove multiple whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned)

        return cleaned.strip()

    except Exception as e:
        logger.error(f"Error sanitizing HTML: {e}")
        # On error, return empty string (fail secure)
        return ""


def sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """
    Sanitize plain text content

    Args:
        text: Raw text from untrusted source
        max_length: Maximum allowed length

    Returns:
        Sanitized text
    """
    if not text:
        return ""

    # Enforce length limit
    if len(text) > max_length:
        logger.warning(f"Text content truncated from {len(text)} to {max_length} chars")
        text = text[:max_length]

    # Remove control characters except newline and tab
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def normalize_url(url: str) -> str:
    """
    Normalize URL for deduplication

    Args:
        url: URL to normalize

    Returns:
        Normalized URL (lowercase scheme/host, sorted query params, no fragment)
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url.strip())

        # Lowercase scheme and hostname
        scheme = parsed.scheme.lower() if parsed.scheme else ''
        netloc = parsed.netloc.lower() if parsed.netloc else ''

        # Remove fragment (everything after #)
        fragment = ''

        # Sort query parameters for consistent comparison
        if parsed.query:
            query_params = parse_qs(parsed.query, keep_blank_values=True)
            # Remove common tracking parameters
            tracking_params = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
                             'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid']
            for param in tracking_params:
                query_params.pop(param, None)
            # Sort remaining params
            sorted_query = urlencode(sorted(query_params.items()), doseq=True)
        else:
            sorted_query = ''

        # Remove trailing slash from path (except for root)
        path = parsed.path.rstrip('/') if parsed.path != '/' else parsed.path

        # Reconstruct URL
        normalized = urlunparse((scheme, netloc, path, parsed.params, sorted_query, fragment))

        return normalized

    except Exception as e:
        logger.error(f"Error normalizing URL {url}: {e}")
        return url


def validate_external_url(url: str) -> tuple[bool, str]:
    """
    Validate URL before fetching to prevent SSRF attacks

    Args:
        url: URL to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return False, "URL is required"

    if len(url) > MAX_URL_LENGTH:
        return False, f"URL exceeds maximum length of {MAX_URL_LENGTH}"

    try:
        parsed = urlparse(url)

        # Check scheme
        if parsed.scheme not in ALLOWED_URL_SCHEMES:
            return False, f"URL scheme must be {' or '.join(ALLOWED_URL_SCHEMES)}"

        # Check for dangerous hosts
        host = parsed.netloc.lower()
        for disallowed in DISALLOWED_HOSTS:
            if disallowed in host:
                return False, f"Access to {host} is not allowed"

        # Check for IPv4 private ranges
        if re.match(r'^(\d{1,3}\.){3}\d{1,3}', host):
            octets = host.split('.')
            if len(octets) == 4:
                first_octet = int(octets[0])
                # Block private IP ranges
                if first_octet in [10, 127] or (first_octet == 172 and 16 <= int(octets[1]) <= 31) or (first_octet == 192 and int(octets[1]) == 168):
                    return False, "Private IP addresses are not allowed"

        return True, url

    except Exception as e:
        return False, f"Invalid URL format: {str(e)}"


def sanitize_article_content(article: dict) -> dict:
    """
    Sanitize all content fields in an article dictionary

    Args:
        article: Article dictionary with potentially unsafe content

    Returns:
        Article dictionary with sanitized content
    """
    sanitized = article.copy()

    # Sanitize text fields
    if 'title' in sanitized:
        sanitized['title'] = sanitize_text(sanitized['title'], max_length=500)

    if 'summary' in sanitized:
        # RSS summaries may contain HTML
        sanitized['summary'] = sanitize_html(sanitized['summary'], max_length=5000)

    if 'full_content' in sanitized:
        sanitized['full_content'] = sanitize_html(sanitized['full_content'], max_length=100000)

    if 'source' in sanitized:
        sanitized['source'] = sanitize_text(sanitized['source'], max_length=200)

    # Normalize and validate URL
    if 'link' in sanitized and sanitized['link']:
        normalized = normalize_url(sanitized['link'])
        is_valid, result = validate_external_url(normalized)
        if is_valid:
            sanitized['link'] = result
        else:
            logger.warning(f"Invalid article URL removed: {sanitized['link']} - {result}")
            sanitized['link'] = ''

    return sanitized


def truncate_for_llm(text: str, max_length: int = 4000) -> str:
    """
    Truncate text for LLM input to prevent prompt injection and control costs

    Args:
        text: Text to truncate
        max_length: Maximum character length

    Returns:
        Truncated text with indication if truncated
    """
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    # Truncate and add indicator
    truncated = text[:max_length].rsplit(' ', 1)[0]  # Don't cut mid-word
    return truncated + "... [truncated]"
