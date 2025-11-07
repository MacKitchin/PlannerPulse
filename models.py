"""
Database models for Planner Pulse newsletter system
"""

import os
from pathlib import Path
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class Article(Base):
    """Model for storing articles and their metadata"""
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    link = Column(String(1000), unique=True, nullable=False)
    summary = Column(Text)
    full_content = Column(Text)
    source = Column(String(200))
    published_date = Column(String(200))
    content_hash = Column(String(32))  # MD5 hash for duplicate detection
    
    # Processing metadata
    processed_at = Column(DateTime, default=datetime.utcnow)
    ai_summary = Column(Text)
    included_in_newsletters = relationship("NewsletterArticle", back_populates="article")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes for performance optimization
    __table_args__ = (
        Index('idx_article_content_hash', 'content_hash'),  # For duplicate detection
        Index('idx_article_source', 'source'),  # For filtering by source
        Index('idx_article_processed_at', 'processed_at'),  # For sorting by date
    )

    def __repr__(self):
        return f"<Article(id={self.id}, title='{self.title[:50]}...')>"

class Newsletter(Base):
    """Model for storing generated newsletters"""
    __tablename__ = 'newsletters'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    subject_line = Column(String(200))
    generation_date = Column(DateTime, default=datetime.utcnow)
    
    # Newsletter content
    html_content = Column(Text)
    markdown_content = Column(Text)
    text_content = Column(Text)
    
    # Metadata
    article_count = Column(Integer, default=0)
    sponsor_name = Column(String(200))
    sponsor_data = Column(JSON)  # Store complete sponsor information
    
    # Statistics
    sent_at = Column(DateTime)
    recipient_count = Column(Integer, default=0)
    open_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    
    # Relationships
    articles = relationship("NewsletterArticle", back_populates="newsletter")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes for performance optimization
    __table_args__ = (
        Index('idx_newsletter_generation_date', 'generation_date'),  # For sorting by date
        Index('idx_newsletter_sent_at', 'sent_at'),  # For filtering sent newsletters
    )

    def __repr__(self):
        return f"<Newsletter(id={self.id}, title='{self.title}', date={self.generation_date})>"

class NewsletterArticle(Base):
    """Association table for many-to-many relationship between newsletters and articles"""
    __tablename__ = 'newsletter_articles'
    
    id = Column(Integer, primary_key=True)
    newsletter_id = Column(Integer, ForeignKey('newsletters.id'), nullable=False)
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=False)
    
    # Position in newsletter
    position = Column(Integer, default=0)
    
    # Custom summary for this newsletter (if different from default)
    custom_summary = Column(Text)
    
    newsletter = relationship("Newsletter", back_populates="articles")
    article = relationship("Article", back_populates="included_in_newsletters")

    created_at = Column(DateTime, default=datetime.utcnow)

    # Indexes for performance optimization
    __table_args__ = (
        Index('idx_newsletter_article_newsletter_id', 'newsletter_id'),  # For join performance
        Index('idx_newsletter_article_article_id', 'article_id'),  # For join performance
    )

class Sponsor(Base):
    """Model for managing sponsors"""
    __tablename__ = 'sponsors'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    message = Column(Text, nullable=False)
    link = Column(String(500))
    
    # Sponsor management
    active = Column(Boolean, default=True)
    priority = Column(Integer, default=1)  # Higher numbers = higher priority
    
    # Usage tracking
    total_appearances = Column(Integer, default=0)
    last_used = Column(DateTime)
    
    # Contact and billing information
    contact_email = Column(String(200))
    contact_name = Column(String(200))
    billing_info = Column(JSON)  # Store billing details
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes for performance optimization
    __table_args__ = (
        Index('idx_sponsor_active_priority', 'active', 'priority', 'last_used'),  # For sponsor rotation query
    )

    def __repr__(self):
        return f"<Sponsor(id={self.id}, name='{self.name}', active={self.active})>"

class SponsorRotation(Base):
    """Track sponsor rotation history"""
    __tablename__ = 'sponsor_rotations'
    
    id = Column(Integer, primary_key=True)
    sponsor_id = Column(Integer, ForeignKey('sponsors.id'), nullable=False)
    newsletter_id = Column(Integer, ForeignKey('newsletters.id'), nullable=False)
    
    # Rotation metadata
    rotation_date = Column(DateTime, default=datetime.utcnow)
    rotation_type = Column(String(50), default='automatic')  # automatic, manual, priority
    
    sponsor = relationship("Sponsor")
    newsletter = relationship("Newsletter")

class RSSSource(Base):
    """Model for managing RSS feed sources"""
    __tablename__ = 'rss_sources'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    url = Column(String(500), nullable=False, unique=True)
    
    # Source configuration
    active = Column(Boolean, default=True)
    max_articles = Column(Integer, default=5)
    priority = Column(Integer, default=1)
    
    # Source statistics
    total_articles_fetched = Column(Integer, default=0)
    last_fetch_date = Column(DateTime)
    last_fetch_status = Column(String(50))  # success, error, timeout
    last_error_message = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<RSSSource(id={self.id}, name='{self.name}', active={self.active})>"

class SystemSettings(Base):
    """Store system-wide configuration settings"""
    __tablename__ = 'system_settings'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    data_type = Column(String(20), default='string')  # string, integer, boolean, json
    description = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<SystemSettings(key='{self.key}', value='{self.value}')>"

# Database setup and utilities
def get_database_url():
    """Get database URL from environment"""
    env_url = os.environ.get('DATABASE_URL')
    if env_url:
        return env_url

    default_db_path = Path('data') / 'planner_pulse.db'
    try:
        default_db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Directory may already exist or creation may fail in restricted environments,
        # but we still fall back to the SQLite URL.
        pass

    return f"sqlite:///{default_db_path.resolve()}"

def create_engine_instance():
    """Create SQLAlchemy engine"""
    database_url = get_database_url()
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False  # Set to True for SQL debugging
    )
    return engine

def get_session():
    """Get database session"""
    engine = create_engine_instance()
    Session = sessionmaker(bind=engine)
    return Session()

def init_database():
    """Initialize database tables"""
    engine = create_engine_instance()
    Base.metadata.create_all(engine)
    print("Database tables created successfully")

def migrate_from_json():
    """Migrate existing JSON data to database"""
    from deduplicator import ArticleDeduplicator
    import json
    
    session = get_session()
    
    try:
        # Migrate article history
        dedup = ArticleDeduplicator()
        for url, metadata in dedup.article_metadata.items():
            existing = session.query(Article).filter(Article.link == url).first()
            if not existing:
                article = Article(
                    title=metadata.get('title', 'Unknown'),
                    link=url,
                    source=metadata.get('source', 'Unknown'),
                    processed_at=datetime.fromisoformat(metadata.get('processed_at', datetime.utcnow().isoformat()))
                )
                session.add(article)
        
        # Migrate sponsors from config
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        for sponsor_data in config.get('sponsors', []):
            existing = session.query(Sponsor).filter(Sponsor.name == sponsor_data['name']).first()
            if not existing:
                sponsor = Sponsor(
                    name=sponsor_data['name'],
                    message=sponsor_data['message'],
                    link=sponsor_data.get('link'),
                    active=sponsor_data.get('active', True)
                )
                session.add(sponsor)
        
        # Migrate RSS sources
        for source_url in config.get('sources', []):
            existing = session.query(RSSSource).filter(RSSSource.url == source_url).first()
            if not existing:
                # Extract name from URL
                name = source_url.split('/')[-2] if '/' in source_url else source_url
                rss_source = RSSSource(
                    name=name,
                    url=source_url,
                    active=True
                )
                session.add(rss_source)
        
        session.commit()
        print("Successfully migrated JSON data to database")
        
    except Exception as e:
        session.rollback()
        print(f"Error migrating data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    # Initialize database when run directly
    init_database()
    print("Database initialized successfully")