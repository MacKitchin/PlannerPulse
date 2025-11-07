"""
Database integration layer for Planner Pulse
Provides database-backed versions of existing JSON-based functionality
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import desc, func
from models import (
    get_session, Article, Newsletter, NewsletterArticle, Sponsor,
    SponsorRotation, RSSSource
)
from contextlib import contextmanager

logger = logging.getLogger(__name__)

@contextmanager
def get_db_session():
    """Context manager for database sessions"""
    session = get_session()
    try:
        yield session
    finally:
        session.close()

class DatabaseArticleManager:
    """Database-backed article management replacing JSON-based deduplicator"""

    def __init__(self):
        self._session = None

    @property
    def session(self):
        """Lazy session initialization"""
        if self._session is None:
            self._session = get_session()
        return self._session

    def close_session(self):
        """Close the database session"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_session()

    def __del__(self):
        """Cleanup method to close session when object is destroyed"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception:
                pass
    
    def is_duplicate(self, article: Dict) -> bool:
        """Check if article already exists in database"""
        try:
            # Check by URL
            if 'link' in article:
                existing = self.session.query(Article).filter(
                    Article.link == article['link']
                ).first()
                if existing:
                    return True
            
            # Check by content hash if available
            if 'content_hash' in article:
                existing = self.session.query(Article).filter(
                    Article.content_hash == article['content_hash']
                ).first()
                if existing:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error checking for duplicate: {e}")
            return False
    
    def save_article(self, article_data: Dict) -> Optional[Article]:
        """Save article to database"""
        try:
            article = Article(
                title=article_data.get('title', ''),
                link=article_data.get('link', ''),
                summary=article_data.get('summary', ''),
                full_content=article_data.get('full_content', ''),
                source=article_data.get('source', ''),
                published_date=article_data.get('published', ''),
                content_hash=article_data.get('content_hash', ''),
                ai_summary=article_data.get('ai_summary', '')
            )
            
            self.session.add(article)
            self.session.commit()
            
            logger.info(f"Saved article: {article.title}")
            return article
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error saving article: {e}")
            return None
    
    def filter_new_articles(self, articles: List[Dict]) -> List[Dict]:
        """Filter out articles that already exist in database"""
        new_articles = []
        duplicates_found = 0
        
        for article in articles:
            if not self.is_duplicate(article):
                new_articles.append(article)
            else:
                duplicates_found += 1
        
        logger.info(f"Filtered out {duplicates_found} duplicate articles")
        logger.info(f"Found {len(new_articles)} new articles")
        
        return new_articles
    
    def get_recent_articles(self, limit: int = 50) -> List[Article]:
        """Get recently processed articles"""
        try:
            return self.session.query(Article).order_by(
                desc(Article.created_at)
            ).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting recent articles: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Get article statistics"""
        try:
            total_articles = self.session.query(Article).count()
            articles_today = self.session.query(Article).filter(
                func.date(Article.created_at) == datetime.utcnow().date()
            ).count()
            
            return {
                'total_articles': total_articles,
                'articles_today': articles_today
            }
        except Exception as e:
            logger.error(f"Error getting article stats: {e}")
            return {'total_articles': 0, 'articles_today': 0}

class DatabaseSponsorManager:
    """Database-backed sponsor management"""

    def __init__(self):
        self._session = None

    @property
    def session(self):
        """Lazy session initialization"""
        if self._session is None:
            self._session = get_session()
        return self._session

    def close_session(self):
        """Close the database session"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_session()

    def __del__(self):
        """Cleanup method to close session when object is destroyed"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception:
                pass
    
    def get_current_sponsor(self) -> Optional[Dict]:
        """Get the current sponsor based on rotation logic"""
        try:
            # Get active sponsors ordered by priority and least recently used
            sponsors = self.session.query(Sponsor).filter(
                Sponsor.active == True
            ).order_by(
                desc(Sponsor.priority),
                Sponsor.last_used.asc().nullsfirst()
            ).all()
            
            if not sponsors:
                return None
            
            current_sponsor = sponsors[0]
            
            return {
                'id': current_sponsor.id,
                'name': current_sponsor.name,
                'message': current_sponsor.message,
                'link': current_sponsor.link,
                'active': current_sponsor.active
            }
            
        except Exception as e:
            logger.error(f"Error getting current sponsor: {e}")
            return None
    
    def rotate_sponsor(self, newsletter_id: Optional[int] = None) -> Optional[Dict]:
        """Rotate to next sponsor and record rotation"""
        try:
            current = self.get_current_sponsor()
            if not current:
                return None
            
            current_id = current['id']
            sponsor = self.session.get(Sponsor, current_id)
            if not sponsor:
                logger.warning(f"Current sponsor with ID {current_id} could not be found during rotation")
                return None

            # Determine the next sponsor before committing changes
            next_sponsor = self._get_next_sponsor_excluding(current_id)
            
            # Update usage metrics for the current sponsor
            sponsor.last_used = datetime.utcnow()
            sponsor.total_appearances = (sponsor.total_appearances or 0) + 1
            
            if newsletter_id:
                rotation = SponsorRotation(
                    sponsor_id=sponsor.id,
                    newsletter_id=newsletter_id,
                    rotation_type='automatic'
                )
                self.session.add(rotation)
            
            self.session.commit()
            
            if not next_sponsor:
                next_sponsor = current
            
            logger.info(
                "Rotated sponsor: %s -> %s",
                current.get('name', 'None'),
                next_sponsor.get('name', 'None')
            )
            
            return next_sponsor
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error rotating sponsor: {e}")
            return None
    
    def _get_next_sponsor_excluding(self, exclude_id: int) -> Optional[Dict]:
        """Get the next sponsor excluding the specified sponsor ID"""
        try:
            # Get active sponsors ordered by priority and least recently used, excluding the current one
            sponsors = self.session.query(Sponsor).filter(
                Sponsor.active == True,
                Sponsor.id != exclude_id
            ).order_by(
                desc(Sponsor.priority),
                Sponsor.last_used.asc().nullsfirst()
            ).all()
            
            if not sponsors:
                # If no other sponsors available, return None
                return None
            
            next_sponsor = sponsors[0]
            
            return {
                'id': next_sponsor.id,
                'name': next_sponsor.name,
                'message': next_sponsor.message,
                'link': next_sponsor.link,
                'active': next_sponsor.active
            }
            
        except Exception as e:
            logger.error(f"Error getting next sponsor: {e}")
            return None
    
    def add_sponsor(self, sponsor_data: Dict) -> Optional[Sponsor]:
        """Add new sponsor to database"""
        try:
            sponsor = Sponsor(
                name=sponsor_data['name'],
                message=sponsor_data['message'],
                link=sponsor_data.get('link'),
                active=sponsor_data.get('active', True),
                priority=sponsor_data.get('priority', 1),
                contact_email=sponsor_data.get('contact_email'),
                contact_name=sponsor_data.get('contact_name')
            )
            
            self.session.add(sponsor)
            self.session.commit()
            
            logger.info(f"Added sponsor: {sponsor.name}")
            return sponsor
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error adding sponsor: {e}")
            return None
    
    def get_sponsor_stats(self) -> Dict:
        """Get sponsor statistics"""
        try:
            total_sponsors = self.session.query(Sponsor).count()
            active_sponsors = self.session.query(Sponsor).filter(
                Sponsor.active == True
            ).count()
            
            return {
                'total_sponsors': total_sponsors,
                'active_sponsors': active_sponsors
            }
        except Exception as e:
            logger.error(f"Error getting sponsor stats: {e}")
            return {'total_sponsors': 0, 'active_sponsors': 0}
    
    def activate_sponsor(self, name: str) -> bool:
        """Activate a sponsor by name"""
        try:
            sponsor = self.session.query(Sponsor).filter(
                Sponsor.name == name
            ).first()
            
            if sponsor:
                sponsor.active = True
                self.session.commit()
                logger.info(f"Activated sponsor: {name}")
                return True
            
            logger.warning(f"Sponsor not found: {name}")
            return False
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error activating sponsor: {e}")
            return False
    
    def deactivate_sponsor(self, name: str) -> bool:
        """Deactivate a sponsor by name"""
        try:
            sponsor = self.session.query(Sponsor).filter(
                Sponsor.name == name
            ).first()
            
            if sponsor:
                sponsor.active = False
                self.session.commit()
                logger.info(f"Deactivated sponsor: {name}")
                return True
            
            logger.warning(f"Sponsor not found: {name}")
            return False
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error deactivating sponsor: {e}")
            return False

class DatabaseNewsletterManager:
    """Database-backed newsletter management"""

    def __init__(self):
        self._session = None

    @property
    def session(self):
        """Lazy session initialization"""
        if self._session is None:
            self._session = get_session()
        return self._session

    def close_session(self):
        """Close the database session"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_session()

    def __del__(self):
        """Cleanup method to close session when object is destroyed"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception:
                pass
    
    def save_newsletter(self, newsletter_data: Dict, articles: List[Dict]) -> Optional[Newsletter]:
        """Save newsletter and associated articles to database"""
        try:
            # Create newsletter record
            newsletter = Newsletter(
                title=newsletter_data.get('title', ''),
                subject_line=newsletter_data.get('subject_line', ''),
                html_content=newsletter_data.get('html_content', ''),
                markdown_content=newsletter_data.get('markdown_content', ''),
                text_content=newsletter_data.get('text_content', ''),
                article_count=len(articles),
                sponsor_name=newsletter_data.get('sponsor', {}).get('name', ''),
                sponsor_data=newsletter_data.get('sponsor', {})
            )
            
            self.session.add(newsletter)
            self.session.flush()  # Get the newsletter ID
            
            # Associate articles with newsletter
            article_manager = DatabaseArticleManager()
            for i, article_data in enumerate(articles):
                # Save article if not exists
                if not article_manager.is_duplicate(article_data):
                    article = article_manager.save_article(article_data)
                else:
                    # Get existing article
                    article = self.session.query(Article).filter(
                        Article.link == article_data.get('link')
                    ).first()
                
                if article:
                    newsletter_article = NewsletterArticle(
                        newsletter_id=newsletter.id,
                        article_id=article.id,
                        position=i + 1,
                        custom_summary=article_data.get('ai_summary', '')
                    )
                    self.session.add(newsletter_article)
            
            self.session.commit()
            logger.info(f"Saved newsletter: {newsletter.title}")
            return newsletter
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error saving newsletter: {e}")
            return None
    
    def get_recent_newsletters(self, limit: int = 10) -> List[Newsletter]:
        """Get recent newsletters"""
        try:
            return self.session.query(Newsletter).order_by(
                desc(Newsletter.generation_date)
            ).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting recent newsletters: {e}")
            return []
    
    def get_newsletter_stats(self) -> Dict:
        """Get newsletter statistics"""
        try:
            total_newsletters = self.session.query(Newsletter).count()
            newsletters_today = self.session.query(Newsletter).filter(
                func.date(Newsletter.generation_date) == datetime.utcnow().date()
            ).count()
            
            return {
                'total_newsletters': total_newsletters,
                'newsletters_today': newsletters_today
            }
        except Exception as e:
            logger.error(f"Error getting newsletter stats: {e}")
            return {'total_newsletters': 0, 'newsletters_today': 0}

class DatabaseRSSManager:
    """Database-backed RSS source management"""

    def __init__(self):
        self._session = None

    @property
    def session(self):
        """Lazy session initialization"""
        if self._session is None:
            self._session = get_session()
        return self._session

    def close_session(self):
        """Close the database session"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_session()

    def __del__(self):
        """Cleanup method to close session when object is destroyed"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception:
                pass
    
    def get_active_sources(self) -> List[RSSSource]:
        """Get active RSS sources"""
        try:
            return self.session.query(RSSSource).filter(
                RSSSource.active == True
            ).order_by(desc(RSSSource.priority)).all()
        except Exception as e:
            logger.error(f"Error getting RSS sources: {e}")
            return []
    
    def update_fetch_status(self, source_id: int, status: str, error_message: str = None):
        """Update RSS source fetch status"""
        try:
            source = self.session.query(RSSSource).get(source_id)
            if source:
                source.last_fetch_date = datetime.utcnow()
                source.last_fetch_status = status
                if error_message:
                    source.last_error_message = error_message
                self.session.commit()
        except Exception as e:
            logger.error(f"Error updating fetch status: {e}")
    
    def add_rss_source(self, source_data: Dict) -> Optional[RSSSource]:
        """Add new RSS source"""
        try:
            source = RSSSource(
                name=source_data['name'],
                url=source_data['url'],
                active=source_data.get('active', True),
                max_articles=source_data.get('max_articles', 5),
                priority=source_data.get('priority', 1)
            )
            
            self.session.add(source)
            self.session.commit()
            
            logger.info(f"Added RSS source: {source.name}")
            return source
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error adding RSS source: {e}")
            return None
    
    def add_source(self, url: str) -> bool:
        """Add a new RSS source by URL"""
        try:
            # Extract name from URL
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            name = parsed.netloc or url
            
            # Check if source already exists
            existing = self.session.query(RSSSource).filter(
                RSSSource.url == url
            ).first()
            
            if existing:
                # Reactivate if inactive
                if not existing.active:
                    existing.active = True
                    self.session.commit()
                    logger.info(f"Reactivated RSS source: {url}")
                return True
            
            # Add new source
            source = RSSSource(
                name=name,
                url=url,
                active=True,
                max_articles=5,
                priority=1
            )
            
            self.session.add(source)
            self.session.commit()
            
            logger.info(f"Added RSS source: {url}")
            return True
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error adding RSS source: {e}")
            return False
    
    def deactivate_source(self, url: str) -> bool:
        """Deactivate an RSS source by URL"""
        try:
            source = self.session.query(RSSSource).filter(
                RSSSource.url == url
            ).first()
            
            if source:
                source.active = False
                self.session.commit()
                logger.info(f"Deactivated RSS source: {url}")
                return True
            
            logger.warning(f"RSS source not found: {url}")
            return False
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error deactivating RSS source: {e}")
            return False

def migrate_existing_data():
    """Migrate existing JSON data to database"""
    logger.info("Starting data migration from JSON to database...")
    
    try:
        from models import migrate_from_json
        migrate_from_json()
        
        logger.info("Data migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error during data migration: {e}")
        return False

if __name__ == "__main__":
    # Test database functionality
    logging.basicConfig(level=logging.INFO)
    
    # Initialize database
    from models import init_database
    init_database()
    
    # Test migrations
    migrate_existing_data()