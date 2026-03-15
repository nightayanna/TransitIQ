# TransIQ — Jodel's Data Pipeline Module

Jamaica's AI-Powered Public Transport Intelligence App  
**Intellibus Hackathon 2026**

---

## What's in This Module

This is Jodel's complete Web Scraping & Data Pipeline component for TransIQ.

```
jodel_scraper/
├── scrapers/
│   ├── ta_routes_scraper.py        # Scrapes ta.org.jm/available-routes
│   ├── ta_fares_scraper.py         # Scrapes ta.org.jm/routes-and-fares
│   ├── jutc_scraper.py             # Scrapes JUTC bus schedules & stops
│   ├── weather_scraper.py          # Jamaica Met Service weather alerts
│   └── traffic_scraper.py          # Google Maps live traffic data
├── storage/
│   ├── db.py                       # DB connection (SQLite local / PostgreSQL prod)
│   └── schema.sql                  # Full PostgreSQL schema for production
├── scheduler/
│   └── auto_refresh.py             # 15-minute auto-refresh scheduler
├── api/
│   └── data_api.py                 # REST API server exposing scraped data to backend
├── synthetic/
│   └── seed_synthetic.py           # Fallback synthetic dataset seeder
├── data/                           # Local SQLite DB + JSON exports live here
├── run_all.py                      # Master runner — scrape + seed + start API
├── config.py                       # All config / API keys in one place
└── requirements.txt
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API keys in config.py (or .env)

# 3. Run everything (scrape + load DB + start API)
python run_all.py

# Or run individual scrapers
python scrapers/ta_routes_scraper.py
python scrapers/ta_fares_scraper.py
python scrapers/jutc_scraper.py

# Start the data API only (uses existing DB)
python api/data_api.py
```

---

## API Endpoints (port 5050)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/routes | All transport routes |
| GET | /api/routes?type=taxi | Filter by type (taxi/bus/express) |
| GET | /api/fares | All fare data |
| GET | /api/fares?route_id=X | Fares for a specific route |
| GET | /api/hubs | All transport hubs/stops |
| GET | /api/traffic | Current traffic events |
| GET | /api/weather | Current weather alerts |
| GET | /api/health | Health check + last scrape timestamps |

---

## Database Schema (PostgreSQL — production)

See `storage/schema.sql` for the full schema.  
Tables: `routes`, `hubs`, `route_stops`, `fares`, `traffic_events`, `weather_alerts`, `ml_predictions`, `users`, `trips`

---

## Integration with Backend (Richard's Spring Boot)

The Spring Boot API should call this data API on `http://localhost:5050`.  
In production, set `DATA_API_URL` env var to the deployed URL.

Kafka topics this module publishes to:
- `traffic-events` — new traffic congestion events
- `route-updates` — fare or schedule changes
- `trip-status` — user trip status updates (consumed by safety module)

---

## Fallback Synthetic Dataset

If scrapers fail on hackathon day, run:
```bash
python synthetic/seed_synthetic.py
```
This populates the DB with realistic Jamaica transport data so the app never looks empty.
