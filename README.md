# PlannerPulse

**AI-Powered Newsletter Generator & Editorial Assistant for the Meetings Industry**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1+-green.svg)](https://flask.palletsprojects.com)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-orange.svg)](https://openai.com)
[![SQLite / PostgreSQL](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-336791.svg)](https://postgresql.org)

PlannerPulse is an internal editorial intelligence tool for the meetings and events industry, built for Informa Connect. It combines automated news ingestion, AI-powered relevance classification, TSNN-style draft article generation, and a full editorial review workflow — all in a single Flask web application.

---

## What It Does

PlannerPulse runs two parallel workflows:

**Newsletter Generator** — Fetches articles from configured RSS feeds, summarises them with GPT-4o, applies source-diversity balancing, and produces a professionally formatted HTML/Markdown/text newsletter ready for Beehiiv, Mailchimp, or any HTML email editor.

**TSNN AI Editorial Assistant** — An internal newsroom tool that monitors industry sources, scores every article for TSNN relevance (0–100), generates publication-ready first drafts in TSNN's editorial voice, and presents them in a review dashboard with approve / reject / regenerate / export / AI feedback actions.

---

## Features

### Editorial Pipeline (TSNN AI Assistant)

- **Relevance Classification** — GPT-4o-mini scores every ingested article 0–100 against TSNN's topic taxonomy (Trade Show Operations, Venues & Convention Centers, Event Technology, Industry Organisations, Major Organisers, M&A, Market Data). Only articles scoring 75+ proceed to draft generation.
- **TSNN-Style Draft Generation** — GPT-4o generates full articles using the TSNN AI Editorial Assistant PRD prompts: data-forward headline, news lede, structured body (`Zooming out:`, `By the numbers:`, `Bottom line:`), *Why This Matters to Event Professionals*, and 3–5 key takeaway bullets with inline source citations.
- **Alternative Headlines** — Every draft includes 2 alternative headline angles selectable with one click.
- **Editorial Review Queue** — Split-panel dashboard (queue left, full article detail right). Filter by Pending / Approved / Rejected.
- **Approve / Reject / Edit / Regenerate** — One-click approve; reject with categorised reason (Not relevant, Inaccurate, Tone mismatch, Already covered, etc.); inline headline + body editing; regenerate with free-text editor instructions.
- **AI Editorial Feedback** — "AI Feedback" button sends the draft to GPT-4o for a structured quality review: Overall score, TSNN Voice score, Strengths, Issues (with severity), Missing Context, and Suggested Improvements.
- **Export** — Approved drafts export as CMS-ready HTML, Markdown, or plain text.
- **URL-Based Deduplication** — Articles already in the database are skipped; previously unclassified articles are picked up and classified on subsequent runs.
- **NewsData.io Integration** — Optional: set `NEWSDATA_API_KEY` to add 87,000+ licensed news sources alongside RSS feeds.

### Automation & Scheduling

- **APScheduler** — Pipeline runs automatically at 6:00 AM, 12:00 PM, and 6:00 PM ET when the app is running.
- **Manual Trigger** — "Run Pipeline" button in the Editorial Queue fires an on-demand run with a live terminal-style log.

### Daily Digest

`/digest` — An editorial morning briefing showing all pending drafts with relevance scores, source attribution, next scheduled run times, and direct review links. Approved articles ready for export are listed separately.

### Analytics Dashboard

`/analytics` — Pipeline performance with Chart.js charts:
- Approval rate and total reviewed
- Drafts generated over the last 14 days
- Topic distribution (donut chart)
- Top sources by article volume
- Rejection reason breakdown
- Average relevance score

### Newsletter Generator

- RSS scraping from 7+ industry publications
- Source diversity filter — round-robin interleaving (max 2 articles per outlet)
- GPT-4o summarisation with key takeaway extraction
- AI-generated subject lines
- Sponsor rotation with CVB/DMO support
- Professional HTML output using Informa Connect brand styling (Georgia serif masthead, editorial article layout)

### Authentication

- Flask-Login session-based auth protecting all editorial tools
- Credentials configured via environment variables
- Login page at `/login`; sign-out in every sidebar

---

## Quick Start

### Prerequisites

- Python 3.11+
- OpenAI API key
- NewsData.io API key (optional)

### Installation

```bash
git clone https://github.com/MacKitchin/PlannerPulse.git
cd PlannerPulse

# Install dependencies
uv sync
# or: pip install -e .

# Initialise the database
DATABASE_URL=sqlite:///planner_pulse.db python models.py
```

### Environment Variables

Create a `.env` file:

```
# Required
OPENAI_API_KEY=sk-...

# Database (SQLite for local dev, PostgreSQL for production)
DATABASE_URL=sqlite:///planner_pulse.db

# Editorial login
ADMIN_EMAIL=admin@plannerpulse.com
ADMIN_PASSWORD=changeme
ADMIN_NAME=Editorial Team

# Optional
NEWSDATA_API_KEY=...
SECRET_KEY=change-in-production
FLASK_PORT=5002
```

### Run

```bash
DATABASE_URL=sqlite:///planner_pulse.db FLASK_PORT=5002 python app.py
```

| URL | Description |
|---|---|
| `http://localhost:5002/` | Newsletter Dashboard |
| `http://localhost:5002/editorial` | Editorial Queue *(login required)* |
| `http://localhost:5002/analytics` | Analytics Dashboard *(login required)* |
| `http://localhost:5002/digest` | Daily Digest *(login required)* |

---

## Project Structure

```
PlannerPulse/
│
├── app.py                   # Flask application — all routes
├── main.py                  # Newsletter generation orchestrator
│
├── # Editorial pipeline
├── classifier.py            # TSNN relevance classifier (GPT-4o-mini, 0-100)
├── tsnn_generator.py        # TSNN draft generator (GPT-4o, structured JSON)
├── ingestion_pipeline.py    # Full pipeline: fetch → dedup → classify → draft
├── newsdata_fetcher.py      # NewsData.io API integration
├── scheduler.py             # APScheduler — 6 AM / 12 PM / 6 PM ET
│
├── # Newsletter generation
├── scraper.py               # RSS feed scraper
├── summarizer.py            # GPT-4o article summarisation
├── builder.py               # HTML / Markdown / text builder
├── deduplicator.py          # Article deduplication
├── sponsor_manager.py       # Sponsor rotation
│
├── # Data layer
├── models.py                # SQLAlchemy models (incl. IngestedArticle, Draft, EditorialReview)
├── database.py              # Database managers (incl. DraftManager)
│
├── templates/
│   ├── base_template.html   # Newsletter HTML (Informa Connect brand)
│   ├── preview.html         # Newsletter dashboard
│   ├── editorial.html       # Editorial review queue & draft detail
│   ├── analytics.html       # Analytics dashboard
│   ├── digest.html          # Daily editorial digest
│   └── login.html           # Auth page
│
├── static/style.css         # Informa Connect design system
├── config.json              # Sources, sponsors, thresholds, topic taxonomy
└── output/                  # Generated newsletter files
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `ingested_articles` | Every fetched article with relevance score, topic tags, and processing status |
| `drafts` | AI-generated article drafts with full content, quality scores, and editorial status |
| `editorial_reviews` | Audit trail of every approve / reject / edit / regenerate action |
| `articles` | Newsletter-pipeline article history |
| `newsletters` | Generated newsletter archive |
| `sponsors` | Sponsor rotation data |
| `rss_sources` | Configured feed sources |

---

## API Reference

### Newsletter
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Newsletter dashboard |
| `POST` | `/generate` | Generate new newsletter |
| `GET` | `/preview` | Preview latest newsletter HTML |
| `GET` | `/output/<file>` | Serve newsletter file |

### Editorial Pipeline
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/editorial` | Editorial review queue *(auth)* |
| `GET` | `/api/editorial/drafts` | List drafts (`?status=all/draft/approved/rejected`) |
| `GET` | `/api/editorial/draft/<id>` | Full draft detail |
| `POST` | `/api/editorial/approve/<id>` | Approve draft |
| `POST` | `/api/editorial/reject/<id>` | Reject with reason |
| `POST` | `/api/editorial/edit/<id>` | Save inline edits |
| `POST` | `/api/editorial/regenerate/<id>` | Regenerate with instructions |
| `POST` | `/api/editorial/assist/<id>` | AI editorial quality feedback |
| `GET` | `/api/editorial/export/<id>/<fmt>` | Export as `html` / `markdown` / `text` |
| `POST` | `/api/editorial/ingest` | Trigger manual pipeline run *(auth)* |

### Pages
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/analytics` | Analytics dashboard *(auth)* |
| `GET` | `/digest` | Daily editorial digest *(auth)* |
| `GET/POST` | `/login` | Sign in |
| `GET` | `/logout` | Sign out |

---

## Configuration (`config.json`)

Key settings:

```json
{
  "relevance_threshold": 60,
  "draft_threshold": 75,
  "newsdata_api_key": "",
  "content_settings": { "articles_per_newsletter": 8 }
}
```

- `relevance_threshold: 60` — Articles below this are archived
- `draft_threshold: 75` — Articles at or above this get a full TSNN draft

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.1+ |
| Auth | Flask-Login |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (dev) / PostgreSQL (prod) |
| AI — classification | GPT-4o-mini |
| AI — draft generation | GPT-4o |
| AI — editorial assist | GPT-4o |
| Scheduling | APScheduler 3.x |
| RSS parsing | feedparser |
| Full-text extraction | Trafilatura |
| Charts | Chart.js 4 |
| Frontend | Bootstrap 5 + vanilla JS |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*PlannerPulse — Built for Informa Connect Meetings & Events Intelligence*
