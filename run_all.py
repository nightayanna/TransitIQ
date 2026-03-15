"""
run_all.py — TransIQ Master Runner (Jodel's module)
=========================================================
Starts everything with a single command:
  1. Initialises the database
  2. Seeds synthetic data (fallback baseline)
  3. Runs all live scrapers (TA routes, TA fares, JUTC, traffic, weather)
  4. Starts the 15-minute auto-refresh scheduler in background
  5. Starts the REST API server on port 5050

Usage:
    python run_all.py                  # full start
    python run_all.py --seed-only      # just seed the DB and exit
    python run_all.py --scrape-only    # scrape once and exit (no API server)
    python run_all.py --api-only       # start API only (skip scraping)
    python run_all.py --no-scheduler   # start API without background refresh
"""

import sys
import os
import logging
import argparse
import time

# Configure logging before any imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("transiq.main")

# Try to also log to file
try:
    from config import LOG_FILE
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logging.getLogger().addHandler(logging.FileHandler(LOG_FILE))
except Exception:
    pass


def main():
    parser = argparse.ArgumentParser(description="TransIQ Data Pipeline — Jodel's Module")
    parser.add_argument("--seed-only",    action="store_true", help="Seed DB and exit")
    parser.add_argument("--scrape-only",  action="store_true", help="Run scrapers once and exit")
    parser.add_argument("--api-only",     action="store_true", help="Start API without scraping")
    parser.add_argument("--no-scheduler", action="store_true", help="No background refresh")
    parser.add_argument("--port",         type=int, default=None, help="Override API port")
    args = parser.parse_args()

    from storage.db import init_db
    from config import API_PORT

    port = args.port or API_PORT

    print("\n" + "=" * 60)
    print("  TransIQ Data Pipeline — Jodel's Module")
    print("  Intellibus Hackathon 2026")
    print("=" * 60 + "\n")

    # Step 1: Init DB
    logger.info("Initialising database...")
    init_db()

    # Step 2: Seed synthetic data (always — provides safe fallback baseline)
    logger.info("Seeding synthetic fallback data...")
    from synthetic.seed_synthetic import seed_all
    seed_all(clear_first=False)

    if args.seed_only:
        print("✅ Seed complete. Exiting.")
        return

    # Step 3: Live scrape
    if not args.api_only:
        logger.info("Running live scrapers...")
        from scheduler.auto_refresh import run_all_scrapers
        results = run_all_scrapers()
        print("\nLive scrape results:")
        for k, v in results.items():
            status = "✅" if v > 0 else "⚠️ "
            print(f"  {status} {k:15s}: {v} records")
        print()

    if args.scrape_only:
        print("✅ Scrape complete. Exiting.")
        return

    # Step 4: Start background scheduler
    if not args.no_scheduler:
        from scheduler.auto_refresh import start_scheduler_thread
        scheduler_thread = start_scheduler_thread()
        logger.info("Background scheduler started (15-min refresh)")

    # Step 5: Start API server
    from config import API_HOST
    from api.data_api import run_server

    print("\n" + "─" * 60)
    print(f"  🚀 TransIQ Data API live at http://localhost:{port}")
    print(f"  📡 Endpoints:")
    print(f"     GET  http://localhost:{port}/api/health")
    print(f"     GET  http://localhost:{port}/api/routes")
    print(f"     GET  http://localhost:{port}/api/fares")
    print(f"     GET  http://localhost:{port}/api/traffic")
    print(f"     GET  http://localhost:{port}/api/weather")
    print(f"     GET  http://localhost:{port}/api/hubs")
    print(f"     POST http://localhost:{port}/api/plan")
    print("─" * 60 + "\n")

    run_server(API_HOST, port)


if __name__ == "__main__":
    main()
