#!/usr/bin/env python3
"""
Flask web interface for Planner Pulse newsletter generator
Provides preview and management capabilities with database integration
"""

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import url_has_allowed_host_and_scheme

from main import run_newsletter_generation, load_config
from database import (
    DatabaseArticleManager, DatabaseSponsorManager, 
    DatabaseNewsletterManager, DatabaseRSSManager
)
from models import get_database_url

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Input validation constants
MAX_URL_LENGTH = 2000
MAX_NAME_LENGTH = 200
MAX_MESSAGE_LENGTH = 5000
MAX_EMAIL_LENGTH = 320  # RFC 5321
MAX_SUBJECT_LENGTH = 998  # RFC 2822

def validate_url(url: str, max_length: int = MAX_URL_LENGTH) -> tuple[bool, str]:
    """Validate URL format and length"""
    if not url or not isinstance(url, str):
        return False, "URL is required"

    url = url.strip()
    if len(url) > max_length:
        return False, f"URL exceeds maximum length of {max_length} characters"

    if not url.startswith(('http://', 'https://')):
        return False, "URL must start with http:// or https://"

    # Basic URL structure validation
    if ' ' in url:
        return False, "URL contains invalid spaces"

    return True, url

def validate_string(value: str, field_name: str, max_length: int, required: bool = True) -> tuple[bool, str]:
    """Validate string input"""
    if not value or not isinstance(value, str):
        if required:
            return False, f"{field_name} is required"
        return True, ""

    value = value.strip()
    if required and not value:
        return False, f"{field_name} cannot be empty"

    if len(value) > max_length:
        return False, f"{field_name} exceeds maximum length of {max_length} characters"

    return True, value

def sanitize_json_input(data: dict) -> bool:
    """Validate that input is a valid dictionary"""
    return isinstance(data, dict)

app = Flask(__name__)
# Secure secret key handling
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    import secrets
    secret_key = secrets.token_hex(32)
    logger.warning("No SECRET_KEY environment variable found. Generated a random key for this session. "
                   "For production, set the SECRET_KEY environment variable to a secure random value.")

app.secret_key = secret_key

# Session cookie security hardening
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Enable SESSION_COOKIE_SECURE only when not in debug mode (requires HTTPS in production)
app.config['SESSION_COOKIE_SECURE'] = not os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = get_database_url()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_size': 5,  # Maximum number of permanent connections
    'max_overflow': 10,  # Maximum number of overflow connections
}

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# ── Flask-Login setup ─────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to access the editorial dashboard.'
login_manager.login_message_category = 'error'

# Single-user model — credentials sourced from environment variables
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@plannerpulse.com')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', '')  # bcrypt hash
ADMIN_PASSWORD_PLAIN = os.environ.get('ADMIN_PASSWORD', '')  # plain text fallback (dev only)

class EditorUser(UserMixin):
    """In-memory user object (single-user for MVP)."""
    id = '1'
    email = ADMIN_EMAIL
    role = 'editor'
    name = os.environ.get('ADMIN_NAME', 'Editor')

_editor_user = EditorUser()

@login_manager.user_loader
def load_user(user_id):
    if user_id == '1':
        return _editor_user
    return None

def _check_password(plain: str) -> bool:
    if ADMIN_PASSWORD_HASH:
        import bcrypt
        return bcrypt.checkpw(plain.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8'))
    if not ADMIN_PASSWORD_PLAIN:
        logger.error(
            "No admin password configured. "
            "Set ADMIN_PASSWORD_HASH (bcrypt hash) or ADMIN_PASSWORD environment variable."
        )
        return False
    return plain == ADMIN_PASSWORD_PLAIN

@login_manager.unauthorized_handler
def unauthorized():
    """Return JSON for API routes; redirect to login for browser routes."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Authentication required'}), 401
    return redirect(url_for('login', next=request.url))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if email == ADMIN_EMAIL.lower() and _check_password(password):
            login_user(_editor_user, remember=True)
            next_page = request.args.get('next')
            # Validate redirect target to prevent open-redirect attacks
            if not next_page or not url_has_allowed_host_and_scheme(next_page, {request.host}):
                next_page = url_for('index')
            return redirect(next_page)
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been signed out.', 'success')
    return redirect(url_for('login'))

@app.route('/')
def index():
    """Main dashboard with database integration"""
    try:
        config = load_config()
        
        # Initialize database managers using context managers
        with DatabaseArticleManager() as article_manager, \
             DatabaseSponsorManager() as sponsor_manager, \
             DatabaseNewsletterManager() as newsletter_manager:
            
            # Get database statistics
            article_stats = article_manager.get_stats()
            sponsor_stats = sponsor_manager.get_sponsor_stats()
            newsletter_stats = newsletter_manager.get_newsletter_stats()
            
            stats = {
                'total_processed': article_stats.get('total_articles', 0),
                'total_sponsors': sponsor_stats.get('total_sponsors', 0),
                'current_sponsor': sponsor_manager.get_current_sponsor(),
                'rss_sources': len(config.get("sources", [])),
                'articles_today': article_stats.get('articles_today', 0),
                'newsletters_today': newsletter_stats.get('newsletters_today', 0),
                'total_newsletters': newsletter_stats.get('total_newsletters', 0)
            }
        
        # Check if recent newsletter exists
        recent_newsletter = None
        if os.path.exists('output/newsletter.html'):
            stat = os.stat('output/newsletter.html')
            recent_newsletter = {
                'exists': True,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            }
        
        return render_template('preview.html', 
                             config=config, 
                             stats=stats, 
                             recent_newsletter=recent_newsletter)
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        flash(f"Error loading dashboard: {e}", 'error')
        return render_template('preview.html', config={}, stats={}, recent_newsletter=None)

@app.route('/generate', methods=['POST'])
@login_required
def generate_newsletter():
    """Generate new newsletter"""
    try:
        success = run_newsletter_generation()
        if success:
            flash('Newsletter generated successfully!', 'success')
        else:
            flash('Newsletter generation failed. Check logs for details.', 'error')
    except Exception as e:
        logger.error(f"Error generating newsletter: {e}")
        flash(f'Error generating newsletter: {e}', 'error')
    
    return redirect(url_for('index'))

@app.route('/preview')
def preview_newsletter():
    """Preview generated newsletter"""
    try:
        if os.path.exists('output/newsletter.html'):
            with open('output/newsletter.html', 'r', encoding='utf-8') as f:
                html_content = f.read()
            return html_content
        else:
            return "<h1>No newsletter found</h1><p>Generate a newsletter first.</p>"
    except Exception as e:
        logger.error(f"Error loading newsletter preview: {e}")
        return f"<h1>Error</h1><p>Failed to load newsletter: {e}</p>"

@app.route('/output/<filename>')
def serve_output_file(filename):
    """Serve generated newsletter files (HTML, Markdown, Text)"""
    try:
        # Security: only allow specific file types
        allowed_extensions = {'html', 'md', 'txt'}
        if not filename or '.' not in filename:
            return "<h1>Invalid file</h1>", 400
        
        file_ext = filename.rsplit('.', 1)[-1].lower()
        if file_ext not in allowed_extensions:
            return "<h1>Invalid file type</h1>", 400
        
        filepath = os.path.join('output', filename)
        
        # Prevent directory traversal
        if not os.path.abspath(filepath).startswith(os.path.abspath('output')):
            return "<h1>Access denied</h1>", 403
        
        if not os.path.exists(filepath):
            return "<h1>File not found</h1><p>Generate a newsletter first.</p>", 404
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Set appropriate content type
        if file_ext == 'html':
            return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        elif file_ext == 'md':
            return content, 200, {'Content-Type': 'text/markdown; charset=utf-8'}
        else:  # txt
            return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
            
    except Exception as e:
        logger.error(f"Error serving output file: {e}")
        return f"<h1>Error</h1><p>Failed to load file: {e}</p>", 500

@app.route('/api/stats')
def api_stats():
    """API endpoint for dashboard statistics with database integration"""
    try:
        config = load_config()
        
        # Initialize database managers
        article_manager = DatabaseArticleManager()
        sponsor_manager = DatabaseSponsorManager()
        newsletter_manager = DatabaseNewsletterManager()
        
        # Get database statistics
        article_stats = article_manager.get_stats()
        sponsor_stats = sponsor_manager.get_sponsor_stats()
        newsletter_stats = newsletter_manager.get_newsletter_stats()
        
        stats = {
            'total_processed': article_stats.get('total_articles', 0),
            'total_sponsors': sponsor_stats.get('total_sponsors', 0),
            'current_sponsor': sponsor_manager.get_current_sponsor(),
            'rss_sources': len(config.get("sources", [])),
            'last_generated': None,
            'articles_today': article_stats.get('articles_today', 0),
            'newsletters_today': newsletter_stats.get('newsletters_today', 0),
            'total_newsletters': newsletter_stats.get('total_newsletters', 0)
        }
        
        if os.path.exists('output/newsletter.html'):
            stat = os.stat('output/newsletter.html')
            stats['last_generated'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset-history', methods=['POST'])
@login_required
def reset_article_history():
    """Reset article history (for testing) - database version"""
    try:
        article_manager = DatabaseArticleManager()
        # Clear all articles from database
        from models import Article
        article_manager.session.query(Article).delete()
        article_manager.session.commit()
        flash('Article history reset successfully!', 'success')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error resetting history: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rotate-sponsor', methods=['POST'])
@login_required
def rotate_sponsor():
    """Manually rotate to next sponsor - database version"""
    try:
        sponsor_manager = DatabaseSponsorManager()
        new_sponsor = sponsor_manager.rotate_sponsor()
        if new_sponsor:
            flash(f'Rotated to sponsor: {new_sponsor.get("name", "None")}', 'success')
            return jsonify({'success': True, 'sponsor': new_sponsor})
        else:
            flash('Rotated sponsor, but no active sponsor found to rotate to.', 'warning')
            return jsonify({'success': True, 'sponsor': None})
    except Exception as e:
        logger.error(f"Error rotating sponsor: {e}")
        return jsonify({'error': str(e)}), 500

# Settings API endpoints
@app.route('/api/settings/rss', methods=['POST'])
@login_required
def add_rss_source():
    """Add a new RSS source"""
    try:
        data = request.get_json()
        if not sanitize_json_input(data):
            return jsonify({'error': 'Invalid request format'}), 400

        url = data.get('url', '')

        # Validate URL
        is_valid, result = validate_url(url)
        if not is_valid:
            return jsonify({'error': result}), 400

        url = result  # Use sanitized URL

        # Load config and add source
        config = load_config()
        if url not in config['sources']:
            config['sources'].append(url)
            
            # Save config
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=2)
                
            # Also add to database
            rss_manager = DatabaseRSSManager()
            rss_manager.add_source(url)
            
            flash(f'Added RSS source: {url}', 'success')
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'RSS source already exists'}), 400
            
    except Exception as e:
        logger.error(f"Error adding RSS source: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/rss', methods=['DELETE'])
@login_required
def remove_rss_source():
    """Remove an RSS source"""
    try:
        data = request.get_json()
        if not sanitize_json_input(data):
            return jsonify({'error': 'Invalid request format'}), 400

        url = data.get('url', '')

        # Validate URL
        is_valid, result = validate_url(url)
        if not is_valid:
            return jsonify({'error': result}), 400

        url = result  # Use sanitized URL

        # Load config and remove source
        config = load_config()
        if url in config['sources']:
            config['sources'].remove(url)
            
            # Save config
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=2)
                
            # Also remove from database
            rss_manager = DatabaseRSSManager()
            rss_manager.deactivate_source(url)
            
            flash(f'Removed RSS source: {url}', 'success')
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'RSS source not found'}), 404
            
    except Exception as e:
        logger.error(f"Error removing RSS source: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/sponsor', methods=['POST'])
@login_required
def add_sponsor():
    """Add a new sponsor"""
    try:
        data = request.get_json()
        if not sanitize_json_input(data):
            return jsonify({'error': 'Invalid request format'}), 400

        # Validate name
        is_valid, name = validate_string(data.get('name', ''), 'Sponsor name', MAX_NAME_LENGTH)
        if not is_valid:
            return jsonify({'error': name}), 400

        # Validate message
        is_valid, message = validate_string(data.get('message', ''), 'Sponsor message', MAX_MESSAGE_LENGTH)
        if not is_valid:
            return jsonify({'error': message}), 400

        # Validate link (optional)
        link = data.get('link', '').strip()
        if link:
            is_valid, link = validate_url(link)
            if not is_valid:
                return jsonify({'error': f'Invalid link: {link}'}), 400

        # Load config
        config = load_config()

        # Check if sponsor already exists
        existing_names = [s['name'] for s in config.get('sponsors', [])]
        if name in existing_names:
            return jsonify({'error': 'Sponsor already exists'}), 400

        # Add sponsor to config
        new_sponsor = {
            'name': name,
            'message': message,
            'link': link,
            'active': bool(data.get('active', True))
        }
        config['sponsors'].append(new_sponsor)
        
        # Save config
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
            
        # Also add to database
        sponsor_manager = DatabaseSponsorManager()
        sponsor_manager.add_sponsor(new_sponsor)
        
        flash(f'Added sponsor: {name}', 'success')
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error adding sponsor: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/sponsor', methods=['DELETE'])
@login_required
def remove_sponsor():
    """Remove a sponsor"""
    try:
        data = request.get_json()
        if not sanitize_json_input(data):
            return jsonify({'error': 'Invalid request format'}), 400

        # Validate name
        is_valid, name = validate_string(data.get('name', ''), 'Sponsor name', MAX_NAME_LENGTH)
        if not is_valid:
            return jsonify({'error': name}), 400

        # Load config
        config = load_config()
        
        # Find and remove sponsor
        sponsors = config.get('sponsors', [])
        config['sponsors'] = [s for s in sponsors if s['name'] != name]
        
        if len(sponsors) == len(config['sponsors']):
            return jsonify({'error': 'Sponsor not found'}), 404
            
        # Save config
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
            
        # Also remove from database
        sponsor_manager = DatabaseSponsorManager()
        sponsor_manager.deactivate_sponsor(name)
        
        flash(f'Removed sponsor: {name}', 'success')
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error removing sponsor: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/sponsor/toggle', methods=['POST'])
@login_required
def toggle_sponsor():
    """Toggle sponsor active status"""
    try:
        data = request.get_json()
        if not sanitize_json_input(data):
            return jsonify({'error': 'Invalid request format'}), 400

        # Validate name
        is_valid, name = validate_string(data.get('name', ''), 'Sponsor name', MAX_NAME_LENGTH)
        if not is_valid:
            return jsonify({'error': name}), 400

        # Load config
        config = load_config()
        
        # Find and toggle sponsor
        for sponsor in config.get('sponsors', []):
            if sponsor['name'] == name:
                sponsor['active'] = not sponsor.get('active', True)
                
                # Save config
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=2)
                    
                # Also update in database
                sponsor_manager = DatabaseSponsorManager()
                if sponsor['active']:
                    sponsor_manager.activate_sponsor(name)
                else:
                    sponsor_manager.deactivate_sponsor(name)
                    
                flash(f'Toggled sponsor: {name}', 'success')
                return jsonify({'success': True})
                
        return jsonify({'error': 'Sponsor not found'}), 404
        
    except Exception as e:
        logger.error(f"Error toggling sponsor: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/email', methods=['POST'])
@login_required
def update_email_settings():
    """Update email and content settings"""
    try:
        data = request.get_json()
        
        # Load config
        config = load_config()
        
        # Update settings
        if 'subject_line_max_length' in data:
            config['email_settings']['subject_line_max_length'] = data['subject_line_max_length']
        if 'preview_text_length' in data:
            config['email_settings']['preview_text_length'] = data['preview_text_length']
        if 'articles_per_newsletter' in data:
            config['content_settings']['articles_per_newsletter'] = data['articles_per_newsletter']
            
        # Save config
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
            
        flash('Settings updated successfully', 'success')
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/api-key', methods=['POST'])
@login_required
def save_api_key():
    """Save OpenAI API key to configuration"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        
        if not api_key:
            return jsonify({'error': 'API key is required'}), 400

        if not api_key.startswith('sk-'):
            return jsonify({'error': 'Invalid API key format'}), 400

        # SECURITY: Store API key in environment variable only, NOT in config.json
        # Set the environment variable for the current session
        os.environ['OPENAI_API_KEY'] = api_key

        # Reinitialize the OpenAI client with new key
        from summarizer import initialize_openai_client
        if initialize_openai_client(api_key):
            flash('OpenAI API key saved to environment for this session. '
                  'For persistence, set OPENAI_API_KEY environment variable.', 'success')
            return jsonify({'success': True,
                          'message': 'API key configured for current session only. '
                                   'Set OPENAI_API_KEY environment variable for persistence.'})
        else:
            return jsonify({'error': 'Failed to initialize OpenAI client'}), 500
            
    except Exception as e:
        logger.error(f"Error saving API key: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/api-key-status')
@login_required
def api_key_status():
    """Check if API key is configured and not a placeholder"""
    try:
        # Prefer environment variable
        api_key = os.environ.get('OPENAI_API_KEY', '')
        # Treat placeholder values as unconfigured
        placeholder = not api_key or api_key in ('sk-demo-key', 'your-key-here', '')
        configured = bool(api_key and not placeholder)
        return jsonify({
            'configured': configured,
            'masked_key': f"sk-...{api_key[-4:]}" if configured else None
        })
    except Exception as e:
        logger.error(f"Error checking API key status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/test-api', methods=['POST'])
@login_required
def test_api_connection():
    """Test OpenAI API connection"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        
        if not api_key:
            return jsonify({'error': 'API key is required'}), 400
            
        # Test the API connection
        from summarizer import test_api_connection
        success, result = test_api_connection(api_key)
        
        if success:
            return jsonify({'success': True, 'model': result})
        else:
            return jsonify({'success': False, 'error': result}), 400
            
    except Exception as e:
        logger.error(f"Error testing API connection: {e}")
        return jsonify({'error': str(e)}), 500

# ──────────────────────────────────────────────────────────────────────────────
# TSNN Editorial Assistant routes
# ──────────────────────────────────────────────────────────────────────────────

def _draft_to_dict(draft, full: bool = False) -> dict:
    """Serialise a Draft ORM object to a JSON-friendly dict."""
    from classifier import score_label, score_color_class
    score = draft.relevance_score or 0
    d = {
        'id': draft.id,
        'headline': draft.edited_headline or draft.headline,
        'original_headline': draft.headline,
        'alt_headlines': draft.alt_headlines or [],
        'lede': draft.lede or '',
        'primary_topic': draft.primary_topic or '',
        'tags': draft.tags or [],
        'relevance_score': score,
        'score_label': score_label(score),
        'score_color': score_color_class(score),
        'confidence_score': draft.confidence_score,
        'word_count': draft.word_count,
        'status': draft.status,
        'generated_at': draft.generated_at.isoformat() if draft.generated_at else '',
        'source_title': '',
        'source_name': '',
        'source_url': '',
    }
    if draft.source_article:
        d['source_title'] = draft.source_article.title or ''
        d['source_name'] = draft.source_article.source_name or ''
        d['source_url'] = draft.source_article.external_url or ''
        d['relevance_justification'] = draft.source_article.relevance_justification or ''
    if full:
        d['body'] = draft.edited_body or draft.body or ''
        d['why_it_matters'] = draft.why_it_matters or ''
        d['key_takeaways'] = draft.key_takeaways or []
        d['sources_cited'] = draft.sources_cited or []
    return d


@app.route('/editorial')
@login_required
def editorial():
    """TSNN Editorial Review Dashboard"""
    from database import DraftManager
    dm = DraftManager()
    stats = dm.get_draft_stats()
    return render_template('editorial.html', stats=stats)


@app.route('/api/editorial/drafts')
@login_required
def api_editorial_drafts():
    """List drafts, optionally filtered by status."""
    from database import DraftManager
    status = request.args.get('status', 'all')
    dm = DraftManager()
    if status == 'all':
        drafts = dm.get_all_drafts(limit=200)
    else:
        drafts = dm.get_draft_queue(status=status)
    return jsonify([_draft_to_dict(d) for d in drafts])


@app.route('/api/editorial/draft/<int:draft_id>')
@login_required
def api_get_draft(draft_id):
    """Full detail for a single draft."""
    from database import DraftManager
    dm = DraftManager()
    draft = dm.get_draft_by_id(draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    return jsonify(_draft_to_dict(draft, full=True))


@app.route('/api/editorial/approve/<int:draft_id>', methods=['POST'])
@login_required
def api_approve_draft(draft_id):
    """Approve a draft."""
    from database import DraftManager
    data = request.get_json() or {}
    dm = DraftManager()
    success = dm.approve_draft(draft_id, notes=data.get('notes', ''))
    return jsonify({'success': success})


@app.route('/api/editorial/reject/<int:draft_id>', methods=['POST'])
@login_required
def api_reject_draft(draft_id):
    """Reject a draft with a reason."""
    from database import DraftManager
    data = request.get_json() or {}
    dm = DraftManager()
    success = dm.reject_draft(
        draft_id,
        reason=data.get('reason', ''),
        notes=data.get('notes', ''),
    )
    return jsonify({'success': success})


@app.route('/api/editorial/edit/<int:draft_id>', methods=['POST'])
@login_required
def api_edit_draft(draft_id):
    """Save editor's inline modifications to headline / body."""
    from database import DraftManager
    data = request.get_json() or {}
    dm = DraftManager()
    success = dm.update_draft_content(
        draft_id,
        headline=data.get('headline', ''),
        body=data.get('body', ''),
    )
    return jsonify({'success': success})


@app.route('/api/editorial/regenerate/<int:draft_id>', methods=['POST'])
@login_required
def api_regenerate_draft(draft_id):
    """Regenerate a draft with editor instructions."""
    from database import DraftManager
    from tsnn_generator import regenerate_draft
    data = request.get_json() or {}
    instructions = data.get('instructions', '')
    dm = DraftManager()
    draft = dm.get_draft_by_id(draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    # Build source article dict from IngestedArticle
    if not draft.source_article:
        return jsonify({'error': 'No source article available for regeneration'}), 400
    src = draft.source_article
    article_dict = {
        'title': src.title,
        'content': src.content or src.summary,
        'summary': src.summary,
        'source_name': src.source_name,
        'published_at': src.published_at,
        'link': src.external_url,
    }
    new_draft_data = regenerate_draft(article_dict, instructions)
    if not new_draft_data:
        return jsonify({'error': 'Regeneration failed — check OpenAI API key'}), 500
    success = dm.update_draft_after_regeneration(draft_id, new_draft_data)
    if success:
        updated = dm.get_draft_by_id(draft_id)
        return jsonify({'success': True, 'draft': _draft_to_dict(updated, full=True)})
    return jsonify({'error': 'Failed to save regenerated draft'}), 500


@app.route('/api/editorial/export/<int:draft_id>/<fmt>')
@login_required
def api_export_draft(draft_id, fmt):
    """Export an approved draft as html, markdown, or text."""
    from database import DraftManager
    from tsnn_generator import draft_to_html, draft_to_markdown
    dm = DraftManager()
    draft = dm.get_draft_by_id(draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    draft_dict = _draft_to_dict(draft, full=True)
    if fmt == 'html':
        content = draft_to_html(draft_dict)
        return content, 200, {
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Disposition': f'attachment; filename="draft-{draft_id}.html"',
        }
    elif fmt == 'markdown':
        content = draft_to_markdown(draft_dict)
        return content, 200, {
            'Content-Type': 'text/markdown; charset=utf-8',
            'Content-Disposition': f'attachment; filename="draft-{draft_id}.md"',
        }
    else:  # plaintext
        headline = draft_dict.get('headline', '')
        body = draft_dict.get('body', '')
        wim = draft_dict.get('why_it_matters', '')
        takeaways = '\n'.join(f'• {t}' for t in draft_dict.get('key_takeaways', []))
        content = f"{headline}\n\n{draft_dict.get('lede', '')}\n\n{body}\n\nWHY THIS MATTERS\n{wim}\n\nKEY TAKEAWAYS\n{takeaways}"
        return content, 200, {
            'Content-Type': 'text/plain; charset=utf-8',
            'Content-Disposition': f'attachment; filename="draft-{draft_id}.txt"',
        }


@app.route('/api/editorial/ingest', methods=['POST'])
@login_required
def api_run_ingestion():
    """Trigger the full editorial ingestion pipeline manually."""
    try:
        from main import load_config
        from ingestion_pipeline import run_editorial_pipeline
        config = load_config()
        stats = run_editorial_pipeline(config)
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"Ingestion pipeline error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/analytics')
@login_required
def analytics():
    """Editorial analytics dashboard."""
    from database import DraftManager
    from models import Draft, EditorialReview, IngestedArticle, get_session
    from sqlalchemy import func
    from collections import Counter

    session_db = get_session()
    try:
        dm = DraftManager()
        base_stats = dm.get_draft_stats()

        # Approval rate
        total_reviewed = (base_stats['approved'] or 0) + (base_stats['rejected'] or 0)
        approval_rate = round((base_stats['approved'] / total_reviewed * 100) if total_reviewed else 0, 1)

        # Topic distribution
        topic_rows = (
            session_db.query(Draft.primary_topic, func.count(Draft.id))
            .group_by(Draft.primary_topic)
            .order_by(func.count(Draft.id).desc())
            .all()
        )
        topic_labels = [r[0] or 'Uncategorized' for r in topic_rows]
        topic_counts = [r[1] for r in topic_rows]

        # Rejection reasons breakdown
        rejection_rows = (
            session_db.query(EditorialReview.rejection_reason, func.count(EditorialReview.id))
            .filter(EditorialReview.action == 'reject', EditorialReview.rejection_reason != None)
            .group_by(EditorialReview.rejection_reason)
            .order_by(func.count(EditorialReview.id).desc())
            .all()
        )
        rejection_labels = [r[0] for r in rejection_rows]
        rejection_counts = [r[1] for r in rejection_rows]

        # Top sources by article volume
        source_rows = (
            session_db.query(IngestedArticle.source_name, func.count(IngestedArticle.id))
            .group_by(IngestedArticle.source_name)
            .order_by(func.count(IngestedArticle.id).desc())
            .limit(8)
            .all()
        )
        source_labels = [r[0] or 'Unknown' for r in source_rows]
        source_counts = [r[1] for r in source_rows]

        # Average relevance score
        avg_score = session_db.query(func.avg(IngestedArticle.relevance_score)).scalar()
        avg_score = round(float(avg_score), 1) if avg_score else 0

        # Drafts by day (last 14 days)
        from datetime import timedelta
        day_labels = []
        day_counts = []
        today = datetime.utcnow().date()
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            count = session_db.query(Draft).filter(
                func.date(Draft.generated_at) == d
            ).count()
            day_labels.append(d.strftime('%b %d'))
            day_counts.append(count)

        stats = {
            **base_stats,
            'approval_rate': approval_rate,
            'total_reviewed': total_reviewed,
            'avg_relevance_score': avg_score,
        }

        return render_template('analytics.html',
            stats=stats,
            topic_labels=topic_labels,
            topic_counts=topic_counts,
            rejection_labels=rejection_labels,
            rejection_counts=rejection_counts,
            source_labels=source_labels,
            source_counts=source_counts,
            day_labels=day_labels,
            day_counts=day_counts,
        )
    finally:
        session_db.close()


@app.route('/api/editorial/stats')
@login_required
def api_editorial_stats():
    """Draft queue stats for the editorial dashboard header."""
    from database import DraftManager
    dm = DraftManager()
    return jsonify(dm.get_draft_stats())


# ──────────────────────────────────────────────────────────────────────────────
# Daily Digest
# ──────────────────────────────────────────────────────────────────────────────

@app.route('/digest')
@login_required
def daily_digest():
    """Morning editorial digest — top pending drafts formatted as an email preview."""
    from database import DraftManager
    dm = DraftManager()
    pending = dm.get_draft_queue(status='draft')[:10]
    approved_today = dm.get_draft_queue(status='approved')
    stats = dm.get_draft_stats()

    # Next scheduled run times
    try:
        from scheduler import get_next_run_times
        next_runs = get_next_run_times()
    except Exception:
        next_runs = []

    return render_template('digest.html',
        drafts=pending,
        approved_today=approved_today,
        stats=stats,
        next_runs=next_runs,
        generated_at=datetime.now().strftime('%A, %B %d, %Y — %I:%M %p'),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Editor Assist
# ──────────────────────────────────────────────────────────────────────────────

EDITOR_ASSIST_PROMPT = """You are a senior editor at TSNN (Trade Show News Network) reviewing an AI-generated article draft.

Evaluate the draft against TSNN's editorial standards:
- Data-driven reporting with specific numbers and facts
- Industry-insider voice for show organizers, exhibitors, venue operators
- Source attribution for every factual claim
- Clear "Why This Matters" implications for event professionals
- No filler phrases or vague language
- Active voice, specific rather than general

Return a JSON object with:
- overall_score (integer 1-10): overall editorial quality
- strengths (array of strings): what the draft does well (2-4 points)
- issues (array of objects): problems found, each with {severity: "high"|"medium"|"low", description: string}
- missing_context (array of strings): important context or data points absent from the draft
- suggested_improvements (array of strings): specific, actionable edits (3-5 points)
- tsnn_voice_score (integer 1-10): how well it matches TSNN's editorial voice"""


@app.route('/api/editorial/assist/<int:draft_id>', methods=['POST'])
@login_required
def api_editor_assist(draft_id):
    """Run AI quality review on a draft and return structured feedback."""
    from database import DraftManager
    from summarizer import openai_client, initialize_openai_client
    import json as _json

    if not openai_client:
        initialize_openai_client()
    if not openai_client:
        return jsonify({'error': 'OpenAI API key not configured'}), 400

    dm = DraftManager()
    draft = dm.get_draft_by_id(draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404

    headline = draft.edited_headline or draft.headline or ''
    body = draft.edited_body or draft.body or ''
    lede = draft.lede or ''
    why = draft.why_it_matters or ''
    source_name = draft.source_article.source_name if draft.source_article else 'Unknown'

    user_msg = f"""Review this TSNN article draft:

HEADLINE: {headline}

SOURCE: {source_name}
TOPIC: {draft.primary_topic or 'Unknown'}
RELEVANCE SCORE: {draft.relevance_score or 'N/A'}

LEDE:
{lede}

BODY:
{body[:2000]}

WHY THIS MATTERS:
{why[:800]}

Return your editorial review as JSON."""

    try:
        response = openai_client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {'role': 'system', 'content': EDITOR_ASSIST_PROMPT},
                {'role': 'user', 'content': user_msg},
            ],
            response_format={'type': 'json_object'},
            temperature=0.3,
            max_tokens=1500,
        )
        feedback = _json.loads(response.choices[0].message.content)
        return jsonify({'success': True, 'feedback': feedback})
    except Exception as e:
        logger.error(f'Editor assist error: {e}')
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    os.makedirs('output', exist_ok=True)
    os.makedirs('data', exist_ok=True)

    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')

    if debug:
        logger.warning("Running in DEBUG mode. This should NOT be used in production!")

    # Start background scheduler (pipeline runs at 6 AM, 12 PM, 6 PM ET)
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"Could not start scheduler: {e}")

    logger.info(f"Starting Flask server on {host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
