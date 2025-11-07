#!/usr/bin/env python3
"""
Planner Pulse - AI-Powered Newsletter Generator
Main orchestration script for generating newsletters
"""

import json
import logging
import sys
from datetime import datetime

from scraper import fetch_articles
from summarizer import summarize_article, generate_subject_line
from builder import build_newsletter
from database import DatabaseArticleManager, DatabaseSponsorManager, DatabaseNewsletterManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('newsletter.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """Load configuration from config.json"""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        logger.info("Configuration loaded successfully")
        return config
    except FileNotFoundError:
        logger.error("config.json not found")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config.json: {e}")
        raise

def run_newsletter_generation():
    """Main function to orchestrate newsletter generation"""
    try:
        logger.info("Starting newsletter generation process")
        
        # Load configuration
        config = load_config()
        
        # Initialize database components using context managers
        with DatabaseArticleManager() as article_manager, \
             DatabaseSponsorManager() as sponsor_manager, \
             DatabaseNewsletterManager() as newsletter_manager:
            
            # Fetch articles from RSS sources
            logger.info("Fetching articles from RSS sources")
            raw_articles = fetch_articles(config["sources"])
            logger.info(f"Fetched {len(raw_articles)} raw articles")
            
            # Deduplicate articles using database
            logger.info("Deduplicating articles")
            new_articles = article_manager.filter_new_articles(raw_articles)
            logger.info(f"Found {len(new_articles)} new articles after deduplication")
            
            if not new_articles:
                logger.warning("No new articles found. Newsletter generation skipped.")
                return False
            
            # Summarize articles using GPT-4o
            logger.info("Summarizing articles with GPT-4o")
            summaries = []
            successful_summaries = 0
            
            for i, article in enumerate(new_articles):
                try:
                    logger.info(f"Summarizing article {i+1}/{len(new_articles)}: {article['title']}")
                    summary_data = summarize_article(article)
                    if summary_data:
                        # Handle both old string format and new dict format
                        if isinstance(summary_data, dict):
                            summaries.append({
                                **article,
                                'summary': summary_data.get('summary', ''),
                                'takeaway': summary_data.get('takeaway', '')
                            })
                        else:
                            # Legacy string format
                            summaries.append({
                                **article,
                                'summary': summary_data
                            })
                        successful_summaries += 1
                except Exception as e:
                    logger.error(f"Failed to summarize article '{article['title']}': {e}")
                    continue
            
            logger.info(f"Successfully summarized {successful_summaries} articles")
            
            if not summaries:
                logger.error("No articles were successfully summarized")
                return False
        
            # Generate subject line
            logger.info("Generating newsletter subject line")
            try:
                subject_line = generate_subject_line(summaries, config["newsletter_title"])
            except Exception as e:
                logger.error(f"Failed to generate subject line: {e}")
                subject_line = f"{config['newsletter_title']} - {datetime.now().strftime('%B %d, %Y')}"
            
            # Get current sponsor
            current_sponsor = sponsor_manager.get_current_sponsor()
            
            # Build newsletter
            logger.info("Building newsletter")
            newsletter_data = {
                'title': config["newsletter_title"],
                'subject_line': subject_line,
                'stories': summaries,
                'sponsor': current_sponsor,
                'generated_at': datetime.now().isoformat()
            }
            
            success, html_content, markdown_content, text_content = build_newsletter(newsletter_data, config)

            if success:
                # Save newsletter and articles to database
                newsletter_data_db = {
                    'title': f"Planner Pulse - {datetime.now().strftime('%Y-%m-%d')}",
                    'subject_line': subject_line,
                    'html_content': html_content,
                    'markdown_content': markdown_content,
                    'text_content': text_content,
                    'sponsor': current_sponsor
                }
                
                # Save articles to database (they're saved automatically during filter_new_articles)
                saved_newsletter = newsletter_manager.save_newsletter(newsletter_data_db, summaries)
                if saved_newsletter:
                    logger.info(f"Saved newsletter to database with ID: {saved_newsletter.id}")
                
                # Rotate to next sponsor
                old_sponsor = current_sponsor.get('name', 'None') if current_sponsor else 'None'
                next_sponsor = sponsor_manager.rotate_sponsor(saved_newsletter.id if saved_newsletter else None)
                new_sponsor_name = next_sponsor.get('name', 'None') if next_sponsor else 'None'
                logger.info(f"Rotated sponsor: {old_sponsor} -> {new_sponsor_name}")
                
                logger.info("Newsletter generation completed successfully")
                logger.info(f"Subject Line: {subject_line}")
                logger.info(f"Articles included: {len(summaries)}")
                current_sponsor_name = current_sponsor.get('name', 'None') if current_sponsor else 'None'
                logger.info(f"Current sponsor: {current_sponsor_name}")
                
                return True
            else:
                logger.error("Newsletter building failed")
                return False
            
    except Exception as e:
        logger.error(f"Newsletter generation failed: {e}")
        return False

if __name__ == "__main__":
    success = run_newsletter_generation()
    if success:
        print("✅ Newsletter generated successfully! Check /output/ directory")
        sys.exit(0)
    else:
        print("❌ Newsletter generation failed. Check logs for details.")
        sys.exit(1)
