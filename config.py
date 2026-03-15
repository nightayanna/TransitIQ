"""
config.py — TransIQ Data Pipeline Configuration
All API keys and environment settings in one place.
"""

import os

# ─── Google Maps API ──────────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyBKltvZeIMbqtUdvoFgqiFhns3jue1RhOo")

# ─── Database ─────────────────────────────────────────────────────────────────
# Local SQLite (development / hackathon fallback)
SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "transiq.db")

# PostgreSQL (production on AWS RDS)
POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://transiq_user:transiq_pass@localhost:5432/transiq"
)

# Set to "sqlite" for local dev, "postgres" for production
DB_MODE = os.getenv("DB_MODE", "sqlite")

# ─── Kafka ────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_TRAFFIC = "traffic-events"
KAFKA_TOPIC_ROUTES  = "route-updates"
KAFKA_TOPIC_TRIPS   = "trip-status"

# ─── Scraper Settings ─────────────────────────────────────────────────────────
SCRAPE_INTERVAL_MINUTES = 15
REQUEST_TIMEOUT         = 15  # seconds
REQUEST_DELAY_SECONDS   = 1.5  # polite delay between requests

# Target URLs
TA_ROUTES_URL      = "https://ta.org.jm/available-routes"
TA_FARES_URL       = "https://ta.org.jm/routes-and-fares"
JUTC_ROUTES_URL    = "https://jutc.gov.jm/routes"
JUTC_SCHEDULES_URL = "https://jutc.gov.jm/schedules"
MET_WEATHER_URL    = "https://metservice.gov.jm/forecasts"

# Google Maps Distance Matrix / Traffic
GMAPS_TRAFFIC_URL   = "https://maps.googleapis.com/maps/api/distancematrix/json"
GMAPS_GEOCODE_URL   = "https://maps.googleapis.com/maps/api/geocode/json"

# ─── API Server ───────────────────────────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 5050

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE  = os.path.join(os.path.dirname(__file__), "data", "scraper.log")
