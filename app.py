#!/usr/bin/env python3
"""
Flask web interface for Planner Pulse newsletter generator
Provides preview and management capabilities with database integration
"""

import json
import logging
import os
import secrets
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

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
    secret_key = secrets.token_hex(32)
    logger.warning("No SECRET_KEY environment variable found. Generated a random key for this session. "
                   "For production, set the SECRET_KEY environment variable to a secure random value.")

app.secret_key = secret_key

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

@app.route('/api/stats')
def api_stats():
    """API endpoint for dashboard statistics with database integration"""
    try:
        config = load_config()
        
        # Initialize database managers with context managers
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
def reset_article_history():
    """Reset article history (for testing) - database version"""
    try:
        with DatabaseArticleManager() as article_manager:
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
def rotate_sponsor():
    """Manually rotate to next sponsor - database version"""
    try:
        with DatabaseSponsorManager() as sponsor_manager:
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
            with DatabaseRSSManager() as rss_manager:
                rss_manager.add_source(url)
            
            flash(f'Added RSS source: {url}', 'success')
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'RSS source already exists'}), 400
            
    except Exception as e:
        logger.error(f"Error adding RSS source: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/rss', methods=['DELETE'])
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
            with DatabaseRSSManager() as rss_manager:
                rss_manager.deactivate_source(url)
            
            flash(f'Removed RSS source: {url}', 'success')
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'RSS source not found'}), 404
            
    except Exception as e:
        logger.error(f"Error removing RSS source: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/sponsor', methods=['POST'])
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
        with DatabaseSponsorManager() as sponsor_manager:
            sponsor_manager.add_sponsor(new_sponsor)
        
        flash(f'Added sponsor: {name}', 'success')
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error adding sponsor: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/sponsor', methods=['DELETE'])
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
        with DatabaseSponsorManager() as sponsor_manager:
            sponsor_manager.deactivate_sponsor(name)
        
        flash(f'Removed sponsor: {name}', 'success')
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error removing sponsor: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/sponsor/toggle', methods=['POST'])
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
                with DatabaseSponsorManager() as sponsor_manager:
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
def api_key_status():
    """Check if API key is configured"""
    try:
        config = load_config()
        api_key = config.get('openai_api_key')
        
        return jsonify({
            'configured': bool(api_key and api_key.strip()),
            'masked_key': f"sk-...{api_key[-4:]}" if api_key else None
        })
        
    except Exception as e:
        logger.error(f"Error checking API key status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/test-api', methods=['POST'])
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

if __name__ == '__main__':
    # Ensure output directory exists
    os.makedirs('output', exist_ok=True)
    os.makedirs('data', exist_ok=True)

    # Configuration from environment variables with secure defaults
    host = os.environ.get('FLASK_HOST', '127.0.0.1')  # Default to localhost for security
    port = int(os.environ.get('FLASK_PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')

    if debug:
        logger.warning("Running in DEBUG mode. This should NOT be used in production!")

    logger.info(f"Starting Flask server on {host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
